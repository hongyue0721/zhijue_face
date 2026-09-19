"""M2-02 真实 Live 验收测试（Demo Resume v1 + 合成 Demo JD 全链路闭环）：

执行完整链路：
真实 PDF 解析 (pypdf) -> Document/SourceBlock 入库 -> 真实 Evidence 抽取 ->
Proposed Claims -> 用户确认 -> 不可变 ProfileSnapshot -> 真实 openJiuwen Knowledge 向量化激活 ->
显式 SYNTHETIC_DEMO_JD 导入 -> Requirement 抽取 (带 unicode_code_point 单位与 UTF-16 偏移) ->
Candidate Coverage Map 构建 (严格核查 UART/DMA、ownership、Git、RTOS、Linux 边界) ->
五题 Slot Planning (纯业务优先级，无题型偏见，seed_id 为空) -> HTTP 视图查看。

断言全部契约、业务不变量与真机验收要求，生成去敏存证 JSON。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]
SERVICES_DIR = WORKSPACE / "services" / "api"
sys.path.insert(0, str(SERVICES_DIR / "src"))

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pypdf import PdfReader

from zhijue.api.app import create_default_app


def extract_resume_facts(text: str) -> list[dict[str, str]]:
    """从真实简历文本中按结构化段落抽取事实声明（不凭空编造，100% 回指原文）。"""
    sections = [
        ("教育经历", "education"),
        ("专业技能", "skill"),
        ("竞赛经历", "award"),
        ("项目经历", "project"),
        ("个人总结", "other"),
    ]
    facts: list[dict[str, str]] = []
    lines = text.splitlines()
    current_sec = "other"
    current_buf: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        matched_sec = None
        for name, key in sections:
            if stripped == name or stripped.startswith(name):
                matched_sec = key
                break
        if matched_sec:
            if current_buf:
                t = " ".join(current_buf).strip()
                t = re.sub(r"^[\x00\•\-\*\·\s]+", "", t)
                if len(t) >= 8:
                    facts.append({"section": current_sec, "text": t})
                current_buf = []
            current_sec = matched_sec
        else:
            is_bullet = stripped.startswith(("\x00", "•", "-", "*", "·"))
            is_proj = any(p in stripped for p in ["项目｜", "竞赛｜", "大赛", "基于 "])
            if (is_bullet or is_proj) and current_buf:
                t = " ".join(current_buf).strip()
                t = re.sub(r"^[\x00\•\-\*\·\s]+", "", t)
                if len(t) >= 8:
                    facts.append({"section": current_sec, "text": t})
                current_buf = [stripped]
            else:
                current_buf.append(stripped)

    if current_buf:
        t = " ".join(current_buf).strip()
        t = re.sub(r"^[\x00\•\-\*\·\s]+", "", t)
        if len(t) >= 8:
            facts.append({"section": current_sec, "text": t})

    return facts


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"必须显式设置 {name}，不从工作站目录猜测私有输入。")
    return value


def run_live_verification():
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"=== M2-02 Live 真实 Demo 闭环验证开始 ({started_at}) ===")
    print(f"模式: {os.environ.get('ZHIJUE_RUN_MODE')}")
    print("存储与模型配置：已从私密环境加载，路径和值不写入日志。")

    # 私有材料只能由操作者显式提供；仓库不保存工作站路径、文件名或指纹。
    pdf_path = Path(_required_env("ZHIJUE_DEMO_RESUME_PATH")).expanduser()
    expected_sha256 = _required_env("ZHIJUE_DEMO_RESUME_SHA256").lower()
    expected_characters = int(_required_env("ZHIJUE_DEMO_RESUME_EXPECTED_CHARACTERS"))
    if not pdf_path.is_file():
        raise FileNotFoundError("显式配置的 Demo Resume v1 私有文件不存在。")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("ZHIJUE_DEMO_RESUME_SHA256 必须是 64 位小写十六进制。")
    if expected_characters < 1:
        raise ValueError("ZHIJUE_DEMO_RESUME_EXPECTED_CHARACTERS 必须为正整数。")

    pdf_bytes = pdf_path.read_bytes()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    assert pdf_sha256 == expected_sha256, "私有 Demo Resume v1 指纹不匹配。"
    print(f"1. 私有 PDF 已定位并通过指纹校验（{len(pdf_bytes)} 字节）。")

    reader = PdfReader(pdf_path)
    extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(extracted_text) == expected_characters, (
        f"文本字符数期望 {expected_characters}，实际为 {len(extracted_text)}"
    )
    print(f"   pypdf 解析通过: {len(reader.pages)} 页, {len(extracted_text)} 字符")

    app = create_default_app()
    client = TestClient(app)

    # 2. 健康检查
    health = client.get("/api/v1/health/ready").json()
    assert (
        health["data"]["status"] == "ok" and health["data"]["knowledge"] == "configured"
    ), f"服务未就绪: {health}"
    print("2. 健康检查: 业务库与真实 openJiuwen Knowledge 基础设施就绪")

    # 3. 创建 Profile
    res = client.post(
        "/api/v1/profiles",
        json={"display_name": "Demo Resume v1", "synthetic": False},
    )
    assert res.status_code == 201, res.text
    profile = res.json()["data"]
    profile_id = profile["id"]
    print(f"3. 创建 Profile 成功: id={profile_id}, rev={profile['revision']}")

    # 4. 上传真实 PDF 文档
    upload_res = client.post(
        f"/api/v1/profiles/{profile_id}/documents",
        files={
            "file": (
                "demo-resume-v1.pdf",
                pdf_bytes,
                "application/pdf",
            )
        },
        data={"kind": "resume", "expected_revision": profile["revision"]},
        headers={"Idempotency-Key": f"doc-upload-{int(time.time())}"},
    )
    assert upload_res.status_code == 202, upload_res.text
    doc_op = upload_res.json()["data"]
    doc_op_id = doc_op["operation_id"]
    for _ in range(30):
        time.sleep(0.3)
        op = client.get(f"/api/v1/operations/{doc_op_id}").json()["data"]
        if op["status"] in ("succeeded", "failed"):
            break
    assert op["status"] == "succeeded", f"文档解析操作失败: {op}"
    doc_id = op["result"]["document_id"]
    doc_view = client.get(f"/api/v1/documents/{doc_id}").json()["data"]
    assert doc_view["extract_status"] == "parsed"
    assert doc_view["page_count"] == 1
    blocks_res = client.get(f"/api/v1/documents/{doc_id}/blocks").json()["data"]
    assert len(blocks_res["items"]) >= 1
    pdf_page_text = blocks_res["items"][0]["text"]
    assert len(pdf_page_text) == 1655
    print(
        f"4. 真实 PDF 上传与落库解析成功: doc_id={doc_id}, 块字符数={len(pdf_page_text)}"
    )

    # 5. 从解析块中进行 Evidence 抽取
    extracted_facts = extract_resume_facts(pdf_page_text)
    print(f"5. Evidence 抽取完成: 共抽取 {len(extracted_facts)} 条事实，严格回溯原文")
    assert len(extracted_facts) >= 20

    # 写入事实并产生 proposed claims
    profile = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    facts_res = client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": profile["revision"], "items": extracted_facts},
    )
    assert facts_res.status_code == 201, facts_res.text
    profile = facts_res.json()["data"]
    claims = profile["proposed_claims"]
    assert len(claims) == len(extracted_facts)

    # 6. 用户确认事实并触发真实 openJiuwen Knowledge 向量化入库
    confirm_key = f"confirm-live-m202-{int(time.time())}"
    confirm_payload = {
        "expected_revision": profile["revision"],
        "decisions": [{"claim_id": c["id"], "action": "accept"} for c in claims],
    }
    t0 = time.perf_counter()
    res = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json=confirm_payload,
        headers={"Idempotency-Key": confirm_key},
    )
    assert res.status_code == 202, res.text
    confirm_op_id = res.json()["data"]["operation_id"]

    for _ in range(40):
        time.sleep(0.5)
        op = client.get(f"/api/v1/operations/{confirm_op_id}").json()["data"]
        if op["status"] in ("succeeded", "failed"):
            break

    elapsed_confirm = time.perf_counter() - t0
    assert op["status"] == "succeeded", f"确认事实与 Knowledge 索引操作失败: {op}"
    profile = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    snapshot_id = profile["latest_snapshot_id"]
    assert snapshot_id is not None
    print(
        f"6. 确认事实与 Knowledge 向量化成功: 耗时 {elapsed_confirm:.2f}s, 快照={snapshot_id}, 确认条数={len(profile['confirmed_claims'])}"
    )

    # 7. 不提供 jd_text，验证服务端只会加载显式标注的合成 Demo JD。
    preset_jd_path = WORKSPACE / "data" / "jd" / "preset_embedded_junior.txt"
    assert preset_jd_path.is_file(), f"缺少合成 Demo JD: {preset_jd_path}"
    preset_jd_text = preset_jd_path.read_text(encoding="utf-8").strip()

    interview_key = f"interview-live-m202-{int(time.time())}"
    interview_req = {
        "profile_id": profile_id,
        "profile_revision": profile["revision"],
        "role_preset": "embedded_junior",
    }
    res = client.post(
        "/api/v1/interviews",
        json=interview_req,
        headers={"Idempotency-Key": interview_key},
    )
    assert res.status_code == 202, res.text
    plan_op = res.json()["data"]
    plan_op_id = plan_op["operation_id"]
    planned_interview_id = plan_op["resource_id"]

    for _ in range(20):
        time.sleep(0.3)
        op = client.get(f"/api/v1/operations/{plan_op_id}").json()["data"]
        if op["status"] in ("succeeded", "failed"):
            break

    elapsed_plan = time.perf_counter() - t0
    assert op["status"] == "succeeded", f"五题计划生成失败: {op}"
    print(
        f"7. 五题计划生成成功: 耗时 {elapsed_plan:.2f}s, interview_id={planned_interview_id}"
    )

    # 8. 获取 InterviewView 并断言
    view = client.get(f"/api/v1/interviews/{planned_interview_id}").json()["data"]
    assert view["status"] == "ready"

    # 校验契约 Schema
    schema_path = WORKSPACE / "contracts" / "interview-slot.schema.json"
    validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    )
    validation_payload = {"slots": view["root_plan"]["slots"]}
    errors = sorted(validator.iter_errors(validation_payload), key=str)
    assert not errors, f"五题计划契约校验失败: {errors[0].message if errors else ''}"
    print(
        "8. 契约 Schema 校验: 5 个 Slots 100% 符合 contracts/interview-slot.schema.json"
    )

    # 9. 核心业务与事实完整性断言（特别核查要求 4, 5, 6, 7）
    # (a) JD 来源元数据：本地演示配置必须诚实标记 synthetic。
    jd_source = view["jd_source"]
    assert jd_source["source_type"] == "synthetic_demo_jd", jd_source
    assert jd_source["source_name"] == "SYNTHETIC_DEMO_JD_preset_embedded_junior"
    assert jd_source["is_synthetic"] is True
    assert jd_source["source_url"] is None
    assert jd_source["upstream_url"] is None
    assert jd_source["content_hash"]
    print(
        f"9. JD 来源元数据校验通过: source_type={jd_source['source_type']}, is_synthetic={jd_source['is_synthetic']}"
    )

    # (b) Requirement source_span 单位
    requirements = view["jd_requirements"]
    assert len(requirements) >= 5, (
        f"期望至少 5 条 requirement，实际 {len(requirements)}"
    )
    for req in requirements:
        span = req["source_span"]
        assert span["unit"] == "unicode_code_point"
        assert "utf16_start" in span and "utf16_end" in span
        quote = span["quote"]
        cp_start = span["start"]
        cp_end = span["end"]
        assert preset_jd_text[cp_start:cp_end] == quote
    print(
        f"10. Requirement 抽取校验通过: {len(requirements)} 条要求均带 unicode_code_point 单位与 UTF-16 偏移"
    )

    # (c) Coverage Map 特别核查（信息无损失）
    cov_entries = {e["competency_id"]: e for e in view["coverage_map"]}

    # (c.1) 中断 Evidence Mapping 事实性核查（P0：严禁将 TIM/输入捕获直接作为中断证据）
    interrupt_entry = cov_entries.get("embedded.mcu.interrupt")
    assert interrupt_entry is not None, "缺少 interrupt 维度"
    assert interrupt_entry["status"] == "unknown", (
        f"简历无中断自述/经历，interrupt 必须为 unknown: {interrupt_entry}"
    )
    assert interrupt_entry["relation"] == "related_context", (
        f"interrupt relation 必须为 related_context: {interrupt_entry}"
    )
    assert interrupt_entry["evidence_ids"] == [], "相关上下文严禁冒充直接证据"
    assert len(interrupt_entry["related_context_ids"]) >= 1, (
        "TIM/输入捕获必须作为上下文保留"
    )
    print(
        "11. 中断 Evidence Mapping 核查通过: status=unknown, relation=related_context，上下文未伪装成直接证据"
    )

    # (c.2) UART / DMA 与负向回归（绝对不含"双缓冲"）
    uart_entry = cov_entries.get("embedded.peripheral.uart_dma")
    assert uart_entry is not None, "缺少 UART/DMA 维度"
    assert uart_entry["status"] == "unverified", (
        f"UART/DMA 不应为 unknown: {uart_entry}"
    )
    assert uart_entry["relation"] == "direct_experience"
    assert len(uart_entry["evidence_ids"]) >= 1, "UART/DMA 必须关联到候选人证据"
    # 负向检查：确认所有关联证据正文中绝对不包含"双缓冲"
    confirmed_claims_map = {c["id"]: c["text"] for c in profile["confirmed_claims"]}
    for eid in uart_entry["evidence_ids"]:
        c_text = confirmed_claims_map.get(eid, "")
        assert "双缓冲" not in c_text, (
            f"严重缺陷：证据 {eid} 包含未声明词汇'双缓冲': {c_text}"
        )
    print("12. UART/DMA 事实性与负向核查通过: 证据链完整，确认绝对不含'双缓冲'")

    # (c.3) Project Ownership
    owner_entry = cov_entries.get("project.ownership")
    assert owner_entry is not None, "缺少 project.ownership 维度"
    assert owner_entry["status"] == "unverified", (
        f"project ownership 不应为 unknown: {owner_entry}"
    )
    assert owner_entry["relation"] == "direct_experience"
    assert len(owner_entry["evidence_ids"]) >= 1, (
        "project ownership 必须关联到候选人证据"
    )

    # (c.4) Git / Version Control
    git_entry = cov_entries.get("engineering.tooling.version_control")
    assert git_entry is not None, "缺少 version_control 维度"
    assert git_entry["status"] == "unverified", f"Git 不应为 unknown: {git_entry}"
    assert len(git_entry["evidence_ids"]) >= 1, "Git 必须关联到候选人证据"

    # (c.5) FreeRTOS / Queue & Debugging
    rtos_entry = cov_entries.get("embedded.rtos.fundamentals")
    assert rtos_entry is not None, "缺少 rtos 维度"
    assert rtos_entry["status"] == "unverified"
    debug_entry = cov_entries.get("engineering.verification")
    assert debug_entry is not None, "缺少 verification 维度"
    assert debug_entry["status"] == "unverified"

    # (c.6) Embedded Linux 驱动保持声明/学习中，未证实能力
    linux_entry = cov_entries.get("embedded.linux.basics")
    if linux_entry:
        assert linux_entry["status"] in ("unverified", "unknown")

    print(
        "13. Coverage Map 事实完整性校验通过: UART/DMA、ownership、Git、RTOS、debugging 证据链完整，无信息丢失！"
    )

    # (d) Demo Critical Fact Checklist 召回率测试（拒绝主观绝对宣称，采用客观可测量召回）
    checklist = [
        ("CF01_STM32_PLATFORM", ["STM32", "HAL"]),
        ("CF02_UART_DMA_FRAMING_DEBUG", ["串口", "错帧"]),
        ("CF03_FREERTOS_MULTITASK", ["FreeRTOS", "任务"]),
        ("CF04_QUEUE_DATA_TRANSFER", ["Queue"]),
        ("CF05_CAN_BUS_CONGESTION", ["CAN", "拥塞"]),
        ("CF06_GIT_VERSION_CONTROL", ["Git"]),
        ("CF07_PROJECT_OWNERSHIP", ["主要负责"]),
        ("CF08_LINUX_LEARNING_BOUNDARY", ["Linux", "学习中"]),
    ]
    all_claims_text = " ".join(c["text"] for c in profile["confirmed_claims"])
    recalled_count = 0
    for cf_id, terms in checklist:
        matched = all(term.lower() in all_claims_text.lower() for term in terms)
        assert matched, f"关键事实 {cf_id} 召回失败，关键词: {terms}"
        recalled_count += 1
    recall_rate = (recalled_count / len(checklist)) * 100
    print(
        f"14. Demo 关键事实检查集召回率: {recalled_count}/{len(checklist)} ({recall_rate:.1f}%)"
    )

    # (d) 5 Interview Slots 断言
    slots = view["root_plan"]["slots"]
    assert len(slots) == 5
    competencies = [s["competency"] for s in slots]
    assert len(set(competencies)) >= 3
    assert all(s["seed_id"] is None for s in slots), "种子审核通过前禁止绑定 seed_id"
    assert "question_wording" not in view["root_plan"], "严禁生成题目文本"

    print(f"12. 五题 Slot 规划完成: 覆盖能力 {competencies}")
    for idx, s in enumerate(slots):
        print(
            f"    Slot {idx + 1}: [{s['competency']}] status={s['current_verification_status']}, priority={s['priority']}, reason={s['reason_code']}"
        )
        print(f"            goal: {s['verification_goal']}")

    # 10. 保存存证
    finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    evidence_dir = WORKSPACE / "runtime" / "evidence" / "m2-02"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_payload = {
        "task_id": "M2-02",
        "status": "VERIFIED",
        "run_mode": "live",
        "data_mode": "demo_resume_v1_and_synthetic_demo_jd",
        "started_at": started_at,
        "finished_at": finished_at,
        "profile_id": profile_id,
        "profile_snapshot_id": snapshot_id,
        "interview_id": planned_interview_id,
        "resume_evidence": {
            "source": "private_demo_asset",
            "source_fingerprint_verified": True,
            "extracted_characters": len(extracted_text),
            "facts_count": len(extracted_facts),
        },
        "jd_source": jd_source,
        "requirements_count": len(requirements),
        "coverage_map": view["coverage_map"],
        "plan_slots": slots,
        "limitations": view["limitations"],
        "performance": {
            "confirm_seconds": round(elapsed_confirm, 3),
            "planning_seconds": round(elapsed_plan, 3),
        },
    }
    evidence_json = json.dumps(evidence_payload, ensure_ascii=False, indent=2) + "\n"
    evidence_path = evidence_dir / "m2-02-live-verification.json"
    evidence_path.write_text(evidence_json, encoding="utf-8")
    sha256_val = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
    print(
        "13. 去敏存证已持久化: "
        f"{evidence_path.relative_to(WORKSPACE)} (SHA256: {sha256_val})"
    )
    print("=== M2-02 真实 Demo 闭环验证全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(run_live_verification())
