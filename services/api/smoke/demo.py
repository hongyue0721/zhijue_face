"""Explicit, paid live acceptance of the complete five-root demonstration.

Run against an isolated running API. This is synthetic candidate input, not a
fixture model: the server must report live mode and real configured adapters.
The evidence retains failures and retries; an early-ended interview never passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

SYNTHETIC_JD = (
    "SYNTHETIC_DEMO_JD｜合成练习，不是真实招聘广告。\n"
    "必要项：能够编写基础 C 程序；理解 MCU 中断；解释 UART DMA 调试；"
    "说明 SPI I2C CAN 总线选择；解释 FreeRTOS 任务和共享资源。"
)

RESUME_TEXT = """合成演示资料，以下人物与经历均为虚构。
教育：演示大学电子信息工程本科，学习 C 语言与嵌入式系统。
项目：参与 STM32 串口数据采集课程项目，负责 UART 接收与环形缓冲区调试。
过程：使用日志和逻辑分析仪对照帧边界，检查波特率、错误标志与缓冲区读写位置。
验证：记录修改前后相同输入条件的串口日志，没有验证其他负载下的效果。
项目：在 FreeRTOS 课程练习中使用 Queue 传递采样数据，使用互斥量保护共享 I2C 总线。
边界：个人只负责通信与调试部分，未负责整个项目，也没有真实商业上线或量化性能成果。
技能：学习 STM32、C 语言、UART、SPI、I2C、FreeRTOS 任务与同步。
"""

EVIDENCE_ANSWER = (
    "在合成课程项目中，我负责 UART 接收和环形缓冲区调试，不负责整个系统。"
    "我先记录复现输入和日志，再用逻辑分析仪对照帧边界，核对波特率、错误标志与缓冲区读写位置。"
    "修改前后使用相同输入条件对照串口日志；其他负载未验证，不能据此声称性能提升。"
)
TECHNICAL_ANSWERS = {
    "embedded.peripheral.uart_dma": (
        "我先固定发送频率、帧长度和复现条件，确认接收引脚电平与波特率。"
        "用逻辑分析仪对照线上帧和软件日志，检查 UART 错误标志、DMA 剩余计数、"
        "循环缓冲区读写指针和消费速度，区分线路、接收、搬运与消费环节。"
        "再核对中断优先级和回调中的耗时处理，保存修改前后同条件证据。"
        "不同 STM32 系列寄存器细节须查对应参考手册，不能把单次现象直接当成结论。"
    ),
    "embedded.rtos": (
        "采集任务与处理任务之间，小型固定长度数据可以通过 FreeRTOS Queue 按值复制传递。"
        "队列项大小在创建时确定；传指针时队列只复制指针，缓冲区所有权和有效期须由应用保证。"
        "接收任务阻塞等待数据而不是忙轮询，发送设置有限等待并明确队列满时的统计或丢弃策略。"
        "中断使用 FromISR 版本，并按端口要求请求任务切换。共享 I2C 总线使用互斥量，"
        "互斥量的优先级继承缓解优先级反转；信号量用于事件同步，不假定具有同样的继承语义。"
        "周期任务考虑绝对唤醒时间和实际执行耗时，具体优先级、中断限制要核对端口配置。"
    ),
    "embedded.peripheral.serial_bus": (
        "SPI 使用时钟、数据和片选信号，适合较高吞吐及独立片选的设备；"
        "I2C 通过地址选择设备，开漏信号需要合适上拉，便于少引脚连接多个器件。"
        "应按器件支持、吞吐、线长、引脚和可靠性需求选型，不能只凭协议名称判断速度。"
        "我会核对数据手册的时序、电平和地址，再用逻辑分析仪检查握手和波形。"
    ),
    "embedded.mcu.interrupt": (
        "先核对具体 Cortex-M 与 STM32 系列的优先级位数和分组设置，"
        "通常数值较小表示更高的中断紧迫度，抢占与子优先级作用不同。"
        "使用 FreeRTOS 时，调用内核 API 的中断必须符合端口的系统调用优先级限制，"
        "且使用 FromISR 接口；不在中断里阻塞等待。通过 GPIO 打点和日志核对响应时序。"
    ),
    "embedded.c": (
        "练习中我核对数组边界、指针是否为空、指向对象的生命周期和缓冲区容量，"
        "不返回局部变量地址，也不把 volatile 当成互斥或原子性保证。"
        "用编译器告警、调试器和相同输入的日志定位问题；未测过的内存与性能指标不作承诺。"
    ),
}


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def answer_for(question: dict[str, Any]) -> str:
    competency = question["basis"]["competency_id"]
    for prefix, answer in TECHNICAL_ANSWERS.items():
        if competency.startswith(prefix):
            return answer
    return EVIDENCE_ANSWER


class DemoAcceptance:
    def __init__(self, base_url: str, evidence: dict[str, Any]) -> None:
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=30, trust_env=False
        )
        self.evidence = evidence

    def step(self, name: str, **details: Any) -> None:
        self.evidence["steps"].append({"step": name, **details})
        print(json.dumps({"step": name, **details}, ensure_ascii=False), flush=True)

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "POST":
            kwargs.setdefault("headers", {"Idempotency-Key": "demo-" + uuid4().hex})
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()["data"]

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def settle(
        self, accepted: dict[str, Any], revision_path: str | None
    ) -> dict[str, Any]:
        for attempt in range(3):
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                operation = self.get("/operations/" + accepted["operation_id"])
                if operation["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("operation did not settle within 240 seconds")
            self.step("operation", **operation)
            if operation["status"] == "succeeded":
                return operation
            error = operation.get("error") or {}
            if not error.get("retryable") or revision_path is None or attempt == 2:
                raise RuntimeError(f"{operation['kind']} failed: {error.get('code')}")
            revision = self.get(revision_path)["revision"]
            accepted = self.request(
                "POST",
                "/operations/" + operation["id"] + "/retry",
                json={"expected_revision": revision},
            )
        raise AssertionError("unreachable operation attempt state")

    def command(
        self, path: str, body: dict[str, Any], revision_path: str | None
    ) -> dict[str, Any]:
        return self.settle(self.request("POST", path, json=body), revision_path)

    def prepare(self) -> tuple[str, str]:
        ready = self.get("/health/ready")
        if ready["run_mode"] != "live" or ready["knowledge"] != "configured":
            raise RuntimeError("acceptance requires live mode and configured Knowledge")
        self.step("runtime", readiness=ready, info=self.get("/runtime/info"))
        profile = self.request(
            "POST",
            "/profiles",
            json={"display_name": "比赛验收合成候选人", "synthetic": True},
        )
        profile_path = "/profiles/" + profile["id"]
        self.step("profile", profile_id=profile["id"])
        accepted = self.request(
            "POST",
            profile_path + "/documents",
            data={"kind": "resume", "expected_revision": str(profile["revision"])},
            files={"file": ("synthetic-demo.txt", RESUME_TEXT.encode(), "text/plain")},
        )
        self.settle(accepted, None)
        profile = self.get(profile_path)
        claims = profile["proposed_claims"]
        if not claims or any(claim["text"] not in RESUME_TEXT for claim in claims):
            raise RuntimeError(
                "extraction did not retain verbatim synthetic source facts"
            )
        self.command(
            profile_path + "/confirm",
            {
                "expected_revision": profile["revision"],
                "decisions": [
                    {"claim_id": claim["id"], "action": "accept"} for claim in claims
                ],
            },
            profile_path,
        )
        profile = self.get(profile_path)
        if profile["snapshot_activation"]["status"] != "ready":
            raise RuntimeError("real Knowledge activation is not ready")
        self.step("knowledge_ready", activation=profile["snapshot_activation"])
        plan = self.command(
            "/interviews",
            {
                "profile_id": profile["id"],
                "profile_revision": profile["revision"],
                "jd_text": SYNTHETIC_JD,
                "jd_source_name": "SYNTHETIC_DEMO_JD_live_smoke",
            },
            None,
        )
        interview_path = "/interviews/" + plan["resource_id"]
        interview = self.get(interview_path)
        self.command(
            interview_path + "/start",
            {"expected_revision": interview["revision"]},
            interview_path,
        )
        return profile_path, interview_path

    def interview(self, interview_path: str) -> dict[str, Any]:
        roots: dict[str, str] = {}
        followups = 0
        for turn in range(10):
            view = self.get(interview_path)
            question = view.get("current_question")
            if question is None:
                break
            if "rubric_snapshot" in question or "reference_points" in question:
                raise RuntimeError(
                    "candidate question leaked private evaluation content"
                )
            if question["kind"] == "main":
                if question["wording"] in roots.values():
                    raise RuntimeError("duplicate main question wording")
                roots[question["id"]] = question["wording"]
            else:
                followups += 1
            answer = (
                "我参与了课程项目，做了一些调试，结果还可以，具体证据还没有说明。"
                if turn == 0
                else answer_for(question)
            )
            self.step("answer", question=question, answer=answer)
            self.command(
                interview_path + "/answers",
                {
                    "expected_revision": view["revision"],
                    "question_id": question["id"],
                    "client_turn_id": "demo-turn-" + uuid4().hex,
                    "answer_text": answer,
                },
                interview_path,
            )
        view = self.get(interview_path)
        report = self.get(interview_path + "/report")
        coverage = report["coverage"]
        if view["status"] != "completed" or report["completion"] != "complete":
            raise RuntimeError("interview did not naturally complete all roots")
        if coverage["planned_root_count"] != 5 or coverage["answered_root_count"] != 5:
            raise RuntimeError("five submissions are not five completed root questions")
        if len(roots) != 5 or followups < 1 or report["overall_score"] is None:
            raise RuntimeError(
                "five roots, at least one followup and a scored report are required"
            )
        self.step("report", report=report, followup_count=followups)
        return report

    def content(
        self, profile_path: str, interview_path: str, report: dict[str, Any]
    ) -> None:
        report_path = interview_path + "/report"
        self.command(
            report_path + "/improvements",
            {"expected_revision": report["revision"]},
            report_path,
        )
        improved = self.get(report_path)
        expected = {item["root_question_id"] for item in report["root_assessments"]}
        actual = {item["root_question_id"] for item in improved["improved_answers"]}
        if improved["improvements_status"] != "ready" or actual != expected:
            raise RuntimeError("coaching did not cover the complete interview")
        self.step("improvements", report=improved)
        profile = self.get(profile_path)
        accepted = self.request(
            "POST",
            profile_path + "/resume-drafts",
            json={
                "expected_revision": profile["revision"],
                "profile_snapshot_id": profile["latest_snapshot_id"],
                "interview_id": interview_path.rsplit("/", 1)[1],
            },
        )
        draft_path = "/resume-drafts/" + accepted["resource_id"]
        self.settle(accepted, draft_path)
        draft = self.get(draft_path)
        known = {claim["id"] for claim in profile["confirmed_claims"]}
        items = [item for section in draft["sections"] for item in section["items"]]
        if (
            draft["status"] not in {"draft", "accepted"}
            or not items
            or any(
                not item["claim_ids"] or not set(item["claim_ids"]) <= known
                for item in items
            )
        ):
            raise RuntimeError("resume draft did not retain confirmed claim provenance")
        if draft["status"] == "accepted":
            self.step("resume_reused", draft=draft, generation_operation=accepted)
            return
        accepted_draft = self.request(
            "POST",
            draft_path + "/accept",
            json={"expected_revision": draft["revision"]},
        )
        if accepted_draft["status"] != "accepted":
            raise RuntimeError("resume confirmation failed")
        self.step("resume", draft=accepted_draft)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-model-spend", action="store_true", required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; keep previous evidence and choose a new path")
    evidence: dict[str, Any] = {
        "status": "running",
        "started_at": timestamp(),
        "data_mode": "synthetic",
        "steps": [],
        "smoke_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    smoke = DemoAcceptance(args.base_url, evidence)
    started = time.monotonic()
    try:
        profile_path, interview_path = smoke.prepare()
        report = smoke.interview(interview_path)
        smoke.content(profile_path, interview_path, report)
        evidence["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - preserve failed live evidence.
        evidence["status"] = "failed"
        evidence["failure"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        smoke.client.close()
        evidence["finished_at"] = timestamp()
        evidence["duration_seconds"] = round(time.monotonic() - started, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(evidence, output, ensure_ascii=False, indent=2)
            output.write("\n")
        args.output.chmod(0o600)
    print(f"Full demo acceptance: {evidence['status']}")
    raise SystemExit(0 if evidence["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
