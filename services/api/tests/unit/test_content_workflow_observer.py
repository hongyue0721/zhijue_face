"""R1：只读观察者与可注入校验策略；observer=None 时生产行为必须逐字不变。"""

from __future__ import annotations

import asyncio
import json

import pytest

from zhijue.application.answer_workflow import AnalysisResult
from zhijue.application.content_workflow import (
    ContentWorkflowError,
    run_grounded_content_workflow,
)

ANSWER_TEXT = "我先记录复现条件，再对照 UART 日志区分串口与数据处理。"
CLAIM_TEXT = "使用 FreeRTOS Queue 在 ESP32-S3 项目中传递任务间消息。"

PAYLOAD = {
    "report_id": "report_demo",
    "answers_by_root": {"question_root": {"answer_demo": ANSWER_TEXT}},
    "root_questions": {"question_root": "请描述一次串口错帧排查。"},
    "allowed_claims": {"claim_demo": CLAIM_TEXT},
}


def _coaching_content(rewritten: str, *, claim_id: str = "claim_demo") -> str:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "report_id": "report_demo",
            "items": [
                {
                    "root_question_id": "question_root",
                    "rewritten_answer": rewritten,
                    "segments": [
                        {
                            "text": rewritten,
                            "source_refs": [{"type": "claim", "claim_id": claim_id}],
                        }
                    ],
                    "used_claim_ids": [claim_id],
                    "changes": ["调整表达顺序"],
                    "missing_facts": [],
                    "cautions": [],
                }
            ],
        },
        ensure_ascii=False,
    )


class ScriptedGenerator:
    """返回固定模型原文的 ContentGenerator（真实 openJiuwen 图内的模型替身）。"""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def generate(self, *, task, payload) -> AnalysisResult:
        del task, payload
        self.calls += 1
        return AnalysisResult(
            content=self.content,
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            finish_reason="stop",
        )


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def _record(self, name: str, **fields) -> None:
        self.events.append((name, fields))

    def on_generation_input(self, event) -> None:
        self._record("input", task=event.task, payload=dict(event.payload))

    def on_raw_generation(self, event) -> None:
        self._record(
            "raw",
            task=event.task,
            content=event.content,
            usage=dict(event.usage),
            finish_reason=event.finish_reason,
        )

    def on_validation_success(self, event) -> None:
        self._record("ok", candidate=event.candidate, content=event.content)

    def on_validation_failure(self, event) -> None:
        self._record(
            "fail",
            code=event.reason_code,
            detail=event.reason_detail,
            content=event.content,
        )

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def field(self, name: str, key: str):
        for event_name, fields in self.events:
            if event_name == name:
                return fields[key]
        raise AssertionError(f"missing event {name}")


def _run(generator, **kwargs):
    return asyncio.run(
        run_grounded_content_workflow(
            generator=generator,
            task="coach_answers",
            payload=dict(PAYLOAD),
            timeout_seconds=30,
            **kwargs,
        )
    )


def test_observer_sees_four_stage_flow_on_success() -> None:
    observer = RecordingObserver()
    content = _coaching_content("我按复现条件、日志对照、边界判定的顺序处理错帧。")
    result = _run(ScriptedGenerator(content), observer=observer)

    assert observer.names() == ["input", "raw", "ok"]
    assert observer.field("input", "payload")["report_id"] == "report_demo"
    assert observer.field("raw", "content") == content
    assert observer.field("raw", "usage") == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "cost": None,
    }
    assert observer.field("raw", "finish_reason") == "stop"
    assert result["candidate"] == dict(observer.field("ok", "candidate"))


def test_observer_gets_structured_code_before_production_message_is_fuzzed() -> None:
    observer = RecordingObserver()
    # 引用快照外的 claim：validator 会拒绝，但观察者拿到具体分类与模型原文。
    content = _coaching_content("我使用 Queue 传递消息。", claim_id="claim_foreign")

    with pytest.raises(ContentWorkflowError) as caught:
        _run(ScriptedGenerator(content), observer=observer)

    assert str(caught.value) == "generated content failed contract validation"
    assert observer.names() == ["input", "raw", "fail"]
    assert observer.field("fail", "code") == "CLAIM_OUTSIDE_SNAPSHOT"
    assert observer.field("fail", "content") == content
    assert "claim_foreign" not in str(caught.value)


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ("not json at all", "SCHEMA_INVALID"),
        (json.dumps(["array"]), "SCHEMA_INVALID"),
        (
            json.dumps(
                {
                    "schema_version": "9.9.9",
                    "report_id": "report_demo",
                    "items": [],
                }
            ),
            "SCHEMA_INVALID",
        ),
        # items 为空违反 JSON Schema（minItems=1），因此先于 report_id 判定。
        (
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "report_id": "report_other",
                    "items": [],
                }
            ),
            "SCHEMA_INVALID",
        ),
    ],
)
def test_failure_codes_cover_schema_paths(content: str, expected_code: str) -> None:
    observer = RecordingObserver()
    with pytest.raises(ContentWorkflowError):
        _run(ScriptedGenerator(content), observer=observer)
    assert observer.field("fail", "code") == expected_code


def test_report_id_mismatch_is_reported_before_item_checks() -> None:
    content = json.loads(_coaching_content("我按复现、日志、判定三步处理。"))
    content["report_id"] = "report_foreign"
    observer = RecordingObserver()
    with pytest.raises(ContentWorkflowError):
        _run(
            ScriptedGenerator(json.dumps(content, ensure_ascii=False)),
            observer=observer,
        )
    assert observer.field("fail", "code") == "REPORT_ID_MISMATCH"


def test_observer_exception_never_changes_business_result() -> None:
    class ExplosiveObserver(RecordingObserver):
        def on_generation_input(self, event) -> None:
            raise RuntimeError("observer crashed")

        def on_raw_generation(self, event) -> None:
            raise RuntimeError("observer crashed")

        def on_validation_success(self, event) -> None:
            raise RuntimeError("observer crashed")

    content = _coaching_content("我先复现，再对照日志，最后判定边界。")
    baseline = _run(ScriptedGenerator(content))
    with_explosions = _run(ScriptedGenerator(content), observer=ExplosiveObserver())

    assert with_explosions == baseline


def test_observer_cannot_mutate_workflow_payload() -> None:
    class TamperingObserver(RecordingObserver):
        def on_generation_input(self, event) -> None:
            event.payload["allowed_claims"] = {}  # type: ignore[call-overload]

    payload_before = json.dumps(PAYLOAD, sort_keys=True, ensure_ascii=False)
    _run(
        ScriptedGenerator(_coaching_content("我按复现、日志、判定三步处理。")),
        observer=TamperingObserver(),
    )
    assert json.dumps(PAYLOAD, sort_keys=True, ensure_ascii=False) == payload_before


class PassthroughValidator:
    """研究 M0-M2 的策略：只保证是 JSON 对象，不做事实校验。"""

    def validate(self, *, task, payload, candidate):
        del task, payload
        return candidate


def test_validator_strategy_skips_grounding_without_touching_transport_usage() -> None:
    observer = RecordingObserver()
    # allowed_claims 里没有该 claim，生产 validator 会拒绝；passthrough 不拒。
    content = _coaching_content("我会补充一条无来源的说法。", claim_id="claim_foreign")
    result = _run(
        ScriptedGenerator(content), validator=PassthroughValidator(), observer=observer
    )

    assert result["candidate"]["items"][0]["used_claim_ids"] == ["claim_foreign"]
    assert result["usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "cost": None,
    }
    assert observer.names() == ["input", "raw", "ok"]


def test_default_validator_still_rejects_ungrounded_candidate() -> None:
    generator = ScriptedGenerator(
        _coaching_content("我会补充一条无来源的说法。", claim_id="claim_foreign")
    )
    with pytest.raises(ContentWorkflowError):
        _run(generator)
    assert generator.calls == 1
