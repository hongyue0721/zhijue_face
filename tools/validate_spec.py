#!/usr/bin/env python3
"""Validate this documentation pack. No network, model calls, or app execution.

Dependencies: jsonschema, PyYAML. Run in a separate virtual environment.
This is a specification consistency check, not a business acceptance suite.
"""

from __future__ import annotations

import copy
import importlib.metadata
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import unquote

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
results: list[tuple[str, bool, str]] = []

# 规范包只包含人写的源文件：依赖树、虚拟环境、运行期产物与缓存不属于规范资产。
# toolchain/node24 是解包的 Node 发行包（vendored runtime），其自带文档同样不是规范资产。
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "runtime",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".omp",
    "v",
}
EXCLUDED_PREFIXES = (("toolchain", "node24"),)


def iter_assets(pattern: str) -> list[Path]:
    kept = []
    for path in sorted(ROOT.rglob(pattern)):
        if not path.is_file():
            continue
        parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        if any(parts[: len(prefix)] == prefix for prefix in EXCLUDED_PREFIXES):
            continue
        kept.append(path)
    return kept


def check(name: str, ok: bool, details: str) -> None:
    results.append((name, bool(ok), details))


def load_json(path: str | Path) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def rejects(validator: Draft202012Validator, value: Any) -> bool:
    return bool(list(validator.iter_errors(value)))


def main() -> int:
    required = [
        "README.md",
        "AGENTS.md",
        "api.md",
        "process.md",
        "CHANGELOG.md",
        "config/demo.yaml",
        "config/environment.env.example",
        "docs/00-owner-guide.md",
        "docs/14-sources-and-rules.md",
        "ai-prompts/01-start.md",
        "templates/handoff.md",
    ]
    missing = [p for p in required if not (ROOT / p).is_file()]
    check("关键文件存在", not missing, ", ".join(missing) or f"{len(required)} 项存在")

    text_files = [
        p for p in iter_assets("*") if p.suffix in {".md", ".json", ".yaml", ".py"}
    ]
    bad_encoding: list[str] = []
    for path in text_files:
        raw = path.read_bytes()
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            bad_encoding.append(str(path.relative_to(ROOT)))
            continue
        if b"\r\n" in raw or "\ufffd" in txt or "\x00" in txt:
            bad_encoding.append(str(path.relative_to(ROOT)))
    check(
        "UTF-8 与 LF",
        not bad_encoding,
        ", ".join(bad_encoding) or f"{len(text_files)} 文件检查通过",
    )

    markdown_files = iter_assets("*.md")
    semantic_markdown_files = [
        path for path in markdown_files if path != ROOT / "validation-report.md"
    ]
    broken_links: list[str] = []
    checked_links = 0
    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if re.match(r"^(https?://|mailto:|#)", target):
                continue
            file_part = unquote(target.split("#", 1)[0])
            if not file_part:
                continue
            checked_links += 1
            if not (path.parent / file_part).exists():
                broken_links.append(f"{path.relative_to(ROOT)} -> {file_part}")
    check(
        "Markdown 本地链接",
        not broken_links,
        "; ".join(broken_links) or f"{checked_links} 条路径存在",
    )

    registry = (ROOT / "docs/14-sources-and-rules.md").read_text(encoding="utf-8")
    known_sources = set(re.findall(r"\| (S\d{2}) \|", registry))
    used_sources: set[str] = set()
    for path in semantic_markdown_files:
        used_sources |= set(
            re.findall(r"\[(S\d{2})\]", path.read_text(encoding="utf-8"))
        )
    check(
        "来源编号",
        used_sources <= known_sources,
        f"引用 {len(used_sources)} 种；登记 {len(known_sources)} 种；未登记 {sorted(used_sources - known_sources)}",
    )

    prd = (ROOT / "docs/01-prd.md").read_text(encoding="utf-8")
    tests = (ROOT / "docs/07-test-and-acceptance.md").read_text(encoding="utf-8")
    known_r = set(re.findall(r"\| (R\d{2}) \|", prd))
    known_t = set(re.findall(r"\| (T\d{2}) \|", tests))
    used_r: set[str] = set()
    used_t: set[str] = set()
    for path in semantic_markdown_files:
        text = path.read_text(encoding="utf-8")
        used_r |= set(re.findall(r"\bR\d{2}\b(?!-)", text))
        used_t |= set(re.findall(r"\bT\d{2}\b(?!-)", text))
    check(
        "需求和测试编号",
        used_r <= known_r and used_t <= known_t,
        f"需求 {len(known_r)}，测试 {len(known_t)}；未知 {sorted((used_r - known_r) | (used_t - known_t))}",
    )

    process = (ROOT / "process.md").read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| (M\d-\d{2}) \| ([^|]+) \| (\w+) \| ([^|]*)\|", process, flags=re.M
    )
    graph = {task: set(re.findall(r"M\d-\d{2}", deps)) for task, deps, _, _ in rows}
    known_tasks = set(graph)
    errors: list[str] = []
    for task, deps in graph.items():
        if not deps <= known_tasks:
            errors.append(f"{task}: unknown dependency")
    visited: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            errors.append(f"cycle: {node}")
            return
        if node in visited or node not in graph:
            return
        active.add(node)
        for dep in graph[node]:
            visit(dep)
        active.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    check(
        "任务依赖无悬空/环",
        not errors and len(rows) == len(graph),
        "; ".join(errors) or f"{len(graph)} 个任务，无环",
    )
    # 施工期检查：状态只能是枚举内的词；VERIFIED/ACCEPTED 必须伴随证据说明，
    # 不允许把 PLANNED 任务标成 VERIFIED/ACCEPTED 却写空产物。规划期的
    # "全部 PLANNED" 基线断言已随施工开始退役（不为通过校验把已完成任务退回 PLANNED）。
    allowed_status = {
        "PLANNED",
        "IN_PROGRESS",
        "IMPLEMENTED",
        "VERIFIED",
        "ACCEPTED",
        "BLOCKED",
    }
    bad_status = [
        f"{task}:{status}"
        for task, _, status, _ in rows
        if status not in allowed_status
    ]
    unsupported = [
        f"{task}:{status}"
        for task, _, status, evidence in rows
        if status in {"VERIFIED", "ACCEPTED"} and not evidence.strip()
    ]
    check(
        "任务状态与证据一致",
        not bad_status and not unsupported,
        "; ".join(bad_status + unsupported)
        or f"{len(rows)} 个任务状态合法且完成项均带产物说明",
    )

    validators: dict[str, Draft202012Validator] = {}
    for path in sorted((ROOT / "contracts").glob("*.schema.json")):
        relative = str(path.relative_to(ROOT))
        sch = load_json(relative)
        try:
            Draft202012Validator.check_schema(sch)
            validators[relative] = Draft202012Validator(sch)
            check(f"Schema: {path.name}", True, "Draft 2020-12 结构合法")
        except Exception as exc:
            check(f"Schema: {path.name}", False, str(exc))

    mapping = load_json("examples/validation-map.json")
    for entry in mapping:
        path, sch = entry["example"], entry["schema"]
        errors_found = list(validators[sch].iter_errors(load_json(path)))
        check(
            f"示例: {Path(path).name}",
            not errors_found,
            "; ".join(e.message for e in errors_found) or "结构通过；不是业务实测结果",
        )

    vobs = validators["contracts/observation.schema.json"]
    invalid = load_json("examples/observation-unknown.json")
    invalid["criteria"][0]["level"] = 3
    check(
        "负例：未知项不能有等级",
        rejects(vobs, invalid),
        "not_assessable + level=3 必须拒绝",
    )
    invalid = load_json("examples/observation-supported.json")
    invalid["confidence"] = 0.94
    check(
        "负例：禁止新增伪置信度",
        rejects(vobs, invalid),
        "闭合对象拒绝未声明 confidence",
    )
    invalid = load_json("examples/policy-decision.json")
    invalid["action"] = "CHALLENGE"
    check(
        "负例：策略动作有界",
        rejects(validators["contracts/policy-decision.schema.json"], invalid),
        "P0 没有 CHALLENGE 动作",
    )
    invalid = load_json("examples/seed_project_ownership.json")
    invalid["review_status"] = "approved"
    check(
        "负例：未记录审核不能批准",
        rejects(validators["contracts/seed.schema.json"], invalid),
        "approved 不允许 null review_record_id",
    )
    vseed = validators["contracts/seed.schema.json"]
    invalid = load_json("examples/seed_rtos_shared_resource.json")
    invalid["reference_points"][0]["reference_ids"] = []
    check(
        "负例：技术参考要点必须带来源",
        rejects(vseed, invalid),
        "technical 参考要点没有 reference_ids 时必须拒绝（模型知识不能充当技术结论）",
    )
    invalid = load_json("examples/seed_rtos_shared_resource.json")
    invalid["red_flags"][0]["requires_followup"] = False
    check(
        "负例：red flag 不能自动扣分",
        rejects(vseed, invalid),
        "requires_followup 恒为 true，结构上禁止 red flag→扣分映射",
    )
    invalid = load_json("examples/seed_rtos_shared_resource.json")
    invalid["review_status"] = "approved"
    invalid["review_record_id"] = "review_demo_01"
    invalid["review_levels"]["level2"]["status"] = "pending"
    check(
        "负例：两级审核未完成不能批准",
        rejects(vseed, invalid),
        "Level 2 未通过时不允许 approved",
    )
    invalid = load_json("examples/seed_rtos_shared_resource.json")
    invalid["review_status"] = "technical_review"
    invalid["review_levels"]["level1"]["status"] = "pending"
    check(
        "负例：technical_review 必须有 Level 1 结果",
        rejects(vseed, invalid),
        "technical_review 只表示 Level 1 已通过，不能空着",
    )
    invalid = load_json("examples/seed_rtos_shared_resource.json")
    invalid["follow_up_strategy"]["max_followups"] = 3
    check(
        "负例：追问上限不得超 P0 约束",
        rejects(vseed, invalid),
        "P0 每个根问题最多一次补充（docs/04 §8）",
    )

    # 种子可追溯性：reference_ids 必须能映射回 docs/14 的来源登记（M2-01）。
    # Schema 只能保证"有引用"，这里保证"引用不是悬空的"。
    registry_text = (ROOT / "docs/14-sources-and-rules.md").read_text(encoding="utf-8")
    id_map = dict(
        re.findall(r"^\| `([a-z0-9_]+)` \| (S\d{2}) \|", registry_text, flags=re.M)
    )
    known_sources = set(re.findall(r"^\| (S\d{2}) \|", registry_text, flags=re.M))
    dangling: list[str] = []
    seeds_checked = 0
    seed_payloads: dict[str, dict] = {}
    for seed_path in sorted((ROOT / "data" / "seeds").glob("*.json")):
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        seeds_checked += 1
        seed_payloads[seed["id"]] = seed
        for ref in set(seed["reference_ids"]) | {
            r for point in seed["reference_points"] for r in point["reference_ids"]
        }:
            mapped = id_map.get(ref)
            if mapped is None or mapped not in known_sources:
                dangling.append(f"{seed_path.name}:{ref}")
    check(
        "种子引用可追溯",
        not dangling and seeds_checked > 0,
        "; ".join(dangling)
        or f"{seeds_checked} 条种子的 reference_id 均映射到已登记来源",
    )
    required_peripheral_sources = {
        "rm0090_stm32f4",
        "rm0440_stm32g4",
        "rm0433_stm32h7",
    }
    platform_gaps: list[str] = []
    for seed_id in (
        "seed_embedded_uart_dma_debug",
        "seed_embedded_spi_i2c_selection",
    ):
        seed = seed_payloads.get(seed_id)
        if seed is None:
            platform_gaps.append(f"{seed_id}:missing")
            continue
        if not required_peripheral_sources.issubset(seed["reference_ids"]):
            platform_gaps.append(f"{seed_id}:top-level")
        for point in seed["reference_points"]:
            if point[
                "kind"
            ] == "technical" and not required_peripheral_sources.issubset(
                point["reference_ids"]
            ):
                platform_gaps.append(f"{seed_id}:{point['point_id']}")
    check(
        "主演示外设种子平台来源闭合",
        not platform_gaps,
        "; ".join(platform_gaps)
        or "UART/DMA 与 SPI/I2C 技术要点均覆盖 F4/G4/H7 已登记来源",
    )
    vslot = validators["contracts/interview-slot.schema.json"]
    slots_doc = load_json("examples/interview-slots-no-resume.json")
    invalid = copy.deepcopy(slots_doc["slots"][0])
    invalid["candidate_evidence_ids"] = ["claim_should_not_exist"]
    check(
        "负例：unknown 槽位不得附证据",
        rejects(vslot, invalid),
        "材料未体现的槽位必须 evidence 为空，避免把缺失写成有依据",
    )
    invalid = copy.deepcopy(slots_doc["slots"][0])
    invalid["seed_id"] = "seed_embedded_freertos_queue_mechanism"
    check(
        "负例：计划不得绑定未批准种子",
        rejects(vslot, invalid),
        "M2-02 阶段 seed_id 必须为 null（AGENTS §11.5）",
    )
    invalid = copy.deepcopy(slots_doc["slots"][0])
    invalid["question_wording"] = "请解释 RTOS 队列"
    check(
        "负例：计划不得含题目文本",
        rejects(vslot, invalid),
        "五题计划只声明验证目标，题目由已批准种子库实例化",
    )
    plan_slots = slots_doc["slots"]
    check(
        "五题计划结构",
        len(plan_slots) == 5
        and len({s["competency"] for s in plan_slots}) >= 3
        and all(s["seed_id"] is None for s in plan_slots)
        and all(
            "不作负面推断" in s["verification_goal"]
            for s in plan_slots
            if s["current_verification_status"] == "unknown"
        ),
        f"{len(plan_slots)} 个槽位 / {len({s['competency'] for s in plan_slots})} 个能力维度",
    )

    invalid = load_json("examples/operation-event.json")
    invalid["payload"]["action"] = "HIRE"
    check(
        "负例：事件 payload 同步动作枚举",
        rejects(validators["contracts/operation-event.schema.json"], invalid),
        "拒绝未知事件动作",
    )

    blocks = {b["id"]: b["text"] for b in load_json("examples/source-blocks.json")}
    c = load_json("examples/claim.json")
    good_quotes = all(
        q["source_block_id"] in blocks
        and q["exact_quote"] in blocks[q["source_block_id"]]
        for q in c["source_quotes"]
    )
    check("Claim 原文定位", good_quotes, "精确子串存在；语义支持另审")
    answers = {a["id"]: a["raw_text"] for a in load_json("examples/answers.json")}
    good_quotes = True
    for p in (
        "examples/observation-supported.json",
        "examples/observation-unknown.json",
    ):
        for cr in load_json(p)["criteria"]:
            for q in cr["answer_quotes"]:
                good_quotes &= (
                    q["answer_id"] in answers
                    and q["exact_quote"] in answers[q["answer_id"]]
                )
    check(
        "Observation 原文定位", good_quotes, "回答引用精确子串存在；不是技术真实性验证"
    )

    cfg = yaml.safe_load((ROOT / "config/demo.yaml").read_text(encoding="utf-8"))
    check(
        "Demo 上限一致",
        cfg["interview"]["root_question_count"] == 5
        and cfg["interview"]["max_supplementary_per_root"] == 1
        and cfg["seed_bank"]["bootstrap_approved_count"] == 6
        and cfg["seed_bank"]["release_target_approved_count"] == 24
        and cfg["limits"]["max_upload_bytes"] == 10 * 1024 * 1024
        and cfg["model"]["max_attempts_per_logical_operation"] == 3
        and cfg["scoring"]["minimum_root_coverage"] == 0.60
        and cfg["scoring"]["minimum_scored_roots_for_overall"] == 3,
        "5 主问题/1 补充/6→24 种子/10MiB/3 尝试/0.60 覆盖/3 根问题",
    )
    check(
        "P1 默认未开启",
        not any(
            cfg["features"][k]
            for k in [
                "ocr_enabled",
                "memory_enabled",
                "external_web_enabled",
                "remote_public_access_enabled",
            ]
        ),
        "OCR、跨场记忆、Web、公网均关闭",
    )
    check(
        "本轮示例不冒充审核题库",
        all(
            load_json(e["example"])["review_status"] == "draft"
            for e in mapping
            if e["schema"] == "contracts/seed.schema.json"
        ),
        "三个题目种子均 draft",
    )

    env = (ROOT / "config/environment.env.example").read_text(encoding="utf-8")
    secret_names = ("API_KEY", "EMBEDDING_API_KEY")
    empty_secrets = all(re.search(rf"^{name}=\s*$", env, re.M) for name in secret_names)
    check(
        "密钥模板不含真实凭据",
        empty_secrets
        and "EMBEDDING_SSL_VERIFY=true" in env
        and not re.search(r"^VITE_[^=]*KEY=", env, re.M)
        and not re.search(r"=\s*(sk-|Bearer\s)", env, re.M),
        "API_KEY/EMBEDDING_API_KEY 留空，TLS 校验开启，无前端密钥变量与显式密钥值；不是完整安全扫描",
    )

    failed = sum(not ok for _, ok, _ in results)
    lines = [
        "# 文档包静态校验记录",
        "",
        "校验性质：规范资产检查，不是业务软件验收。",
        "",
        f"结果：**{len(results) - failed}/{len(results)} 项通过；{failed} 项失败。**",
        "",
        "实际命令：`python tools/validate_spec.py`",
        "",
        f"环境：Python {sys.version.split()[0]}；jsonschema {importlib.metadata.version('jsonschema')}；PyYAML {importlib.metadata.version('PyYAML')}。",
        "",
        "这是文档校验环境，不是要求应用改用此 Python 版本。业务环境仍按 M0 核验 Python 3.11。",
        "",
        "| 检查 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for name, ok, details in results:
        lines.append(
            f"| {name} | {'PASS' if ok else 'FAIL'} | {details.replace('|', '/')} |"
        )
    lines += [
        "",
        "## 本次没有执行",
        "",
        "没有安装或运行 openJiuwen/Knowledge/Milvus 的业务组合；没有跑前后端 build、数据库迁移、浏览器 E2E 或真实模型；没有审核种子技术答案；没有部署国产操作系统；没有修改或推送用户仓库。",
        "",
        "通过这些检查只证明文件路径、编号、Schema、示例和若干配置约束相互一致，不证明没有设计缺陷，也不证明 Demo 已经完成。人工设计复核和真实集成测试仍是后续里程碑。",
        "",
        "校验器只扫描人写的规范资产：依赖树（node_modules/.venv）、vendored Node runtime（toolchain/node24）与运行期产物（runtime/）不参与，避免依赖自带文档造成假失败。",
        "",
        "任务板检查已从规划期的“全部 PLANNED”基线改为施工期不变量：状态必须在枚举内，且 VERIFIED/ACCEPTED 必须带产物说明；不为通过校验把已完成任务退回 PLANNED。",
        "",
        "本报告每次运行覆盖重写。业务验收状态以 process.md 与 docs/handoffs/ 为准，本报告不构成业务验收。",
        "",
    ]
    (ROOT / "validation-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Checks: {len(results) - failed}/{len(results)} passed; {failed} failed")
    for name, ok, details in results:
        if not ok:
            print(f"FAIL {name}: {details}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
