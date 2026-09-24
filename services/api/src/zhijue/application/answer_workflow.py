"""Real openJiuwen orchestration for answer analysis and deterministic policy."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from openjiuwen.core.common.task_manager import get_task_manager
from openjiuwen.core.session.workflow import create_workflow_session
from openjiuwen.core.workflow import (
    End,
    Start,
    Workflow,
    WorkflowCard,
    WorkflowComponent,
    WorkflowExecutionState,
    WorkflowOutput,
)

from zhijue.domain.interview_policy import (
    ObservationValidationError,
    decide_next,
    validate_observation,
)

_ALLOWED_ACTIONS = frozenset({"CLARIFY", "PROBE", "NEXT", "END"})
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens", "cost"})
_OBSERVATION_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "answer_id",
        "question_id",
        "root_question_id",
        "relevance",
        "knowledge_status",
        "criteria",
        "clarification_needed",
        "validation_flags",
    }
)
_DECISION_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "observation_id",
        "root_question_id",
        "action",
        "reason_code",
        "reason_summary",
        "target",
        "policy_version",
    }
)


class AnswerWorkflowError(RuntimeError):
    """The workflow or an analyzer result violated the application contract."""


class ModelRequestError(RuntimeError):
    """The remote model request did not produce a usable response envelope."""


class ModelRequestTimeoutError(ModelRequestError):
    """The remote model request exceeded its configured transport deadline."""


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Untrusted model content plus provider-reported, nullable usage facts."""

    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    # provider 报告的终止原因；缺失只能是 None，不得由实现方猜测。
    # 不进 usage()（生产持久化按固定四键断言），仅供恢复与实验诊断使用。
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("analysis content must be a string")
        for field_name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer or null")
        if self.cost is not None and (
            isinstance(self.cost, bool)
            or not isinstance(self.cost, (int, float))
            or not math.isfinite(self.cost)
            or self.cost < 0
        ):
            raise ValueError("cost must be a finite non-negative number or null")
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise TypeError("finish_reason must be a string or null")

    def usage(self) -> dict[str, int | float | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
        }


@runtime_checkable
class AnswerAnalyzer(Protocol):
    """Port for producing an untrusted Observation candidate, never an action."""

    async def analyze(
        self,
        *,
        observation_id: str,
        answer_id: str,
        question_id: str,
        root_question_id: str,
        question_text: str,
        answer_text: str,
        rubric_snapshot: dict[str, Any],
        reference_material: Any,
    ) -> AnalysisResult: ...


class _AnalyzerComponent(WorkflowComponent):
    def __init__(self, analyzer: AnswerAnalyzer) -> None:
        super().__init__()
        self._analyzer = analyzer

    async def invoke(self, inputs, session, context):
        result = await self._analyzer.analyze(
            observation_id=inputs["observation_id"],
            answer_id=inputs["answer_id"],
            question_id=inputs["question_id"],
            root_question_id=inputs["root_question_id"],
            question_text=inputs["question_text"],
            answer_text=inputs["answer_text"],
            rubric_snapshot=inputs["rubric_snapshot"],
            reference_material=inputs["reference_material"],
        )
        if not isinstance(result, AnalysisResult):
            raise AnswerWorkflowError("analyzer must return AnalysisResult")
        return {"content": result.content, "usage": result.usage()}


class _SemanticValidationComponent(WorkflowComponent):
    async def invoke(self, inputs, session, context):
        try:
            raw = _parse_json_object(inputs["content"])
            observation = validate_observation(
                raw,
                observation_id=inputs["observation_id"],
                answer_id=inputs["answer_id"],
                question_id=inputs["question_id"],
                root_question_id=inputs["root_question_id"],
                answer_text=inputs["answer_text"],
                rubric_snapshot=inputs["rubric_snapshot"],
            )
        except (AnswerWorkflowError, ObservationValidationError):
            # openJiuwen records component exceptions. Keep untrusted model text
            # out of those logs while preserving a typed workflow failure.
            raise AnswerWorkflowError(
                "analyzer output failed contract validation"
            ) from None
        if not isinstance(observation, dict):
            raise AnswerWorkflowError("observation validator returned a non-object")
        return {"observation": observation, "usage": inputs["usage"]}


class _DeterministicPolicyComponent(WorkflowComponent):
    async def invoke(self, inputs, session, context):
        decision = decide_next(
            observation=inputs["observation"],
            competency_id=inputs["competency_id"],
            followup_count=inputs["followup_count"],
            remaining_roots=inputs["remaining_roots"],
            allowed_followup_intents=inputs["allowed_followup_intents"],
            decision_id=inputs["decision_id"],
        )
        if not isinstance(decision, dict):
            raise AnswerWorkflowError("policy returned a non-object decision")
        return {
            "observation": inputs["observation"],
            "decision": decision,
            "usage": inputs["usage"],
        }


def _parse_json_object(content: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON member: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    try:
        parsed = json.loads(
            content,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AnswerWorkflowError("analyzer returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise AnswerWorkflowError("analyzer output must be one JSON object")
    return parsed


def build_handle_answer_workflow(analyzer: AnswerAnalyzer) -> Workflow:
    """Construct the official openJiuwen Start→analyze→validate→policy→End graph."""

    card = WorkflowCard(
        id=f"handle_answer_{uuid4().hex}",
        name="handle_answer",
        version="1.0.0",
        input_params={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "observation_id": {"type": "string"},
                "answer_id": {"type": "string"},
                "question_id": {"type": "string"},
                "root_question_id": {"type": "string"},
                "question_text": {"type": "string"},
                "answer_text": {"type": "string"},
                "rubric_snapshot": {"type": "object"},
                "reference_material": {},
                "competency_id": {"type": "string"},
                "followup_count": {"type": "integer", "minimum": 0},
                "remaining_roots": {"type": "integer", "minimum": 0},
                "allowed_followup_intents": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "decision_id": {"type": "string"},
            },
            "required": [
                "observation_id",
                "answer_id",
                "question_id",
                "root_question_id",
                "question_text",
                "answer_text",
                "rubric_snapshot",
                "reference_material",
                "competency_id",
                "followup_count",
                "remaining_roots",
                "allowed_followup_intents",
                "decision_id",
            ],
        },
    )
    workflow = Workflow(card=card)
    start_inputs = {
        "observation_id": "${observation_id}",
        "answer_id": "${answer_id}",
        "question_id": "${question_id}",
        "root_question_id": "${root_question_id}",
        "question_text": "${question_text}",
        "answer_text": "${answer_text}",
        "rubric_snapshot": "${rubric_snapshot}",
        "reference_material": "${reference_material}",
        "competency_id": "${competency_id}",
        "followup_count": "${followup_count}",
        "remaining_roots": "${remaining_roots}",
        "allowed_followup_intents": "${allowed_followup_intents}",
        "decision_id": "${decision_id}",
    }
    workflow.set_start_comp("start", Start(), inputs_schema=start_inputs)
    workflow.add_workflow_comp(
        "analyzer",
        _AnalyzerComponent(analyzer),
        inputs_schema={
            "observation_id": "${start.observation_id}",
            "answer_id": "${start.answer_id}",
            "question_id": "${start.question_id}",
            "root_question_id": "${start.root_question_id}",
            "question_text": "${start.question_text}",
            "answer_text": "${start.answer_text}",
            "rubric_snapshot": "${start.rubric_snapshot}",
            "reference_material": "${start.reference_material}",
        },
    )
    workflow.add_workflow_comp(
        "semantic_validation",
        _SemanticValidationComponent(),
        inputs_schema={
            "content": "${analyzer.content}",
            "usage": "${analyzer.usage}",
            "observation_id": "${start.observation_id}",
            "answer_id": "${start.answer_id}",
            "question_id": "${start.question_id}",
            "root_question_id": "${start.root_question_id}",
            "answer_text": "${start.answer_text}",
            "rubric_snapshot": "${start.rubric_snapshot}",
        },
    )
    workflow.add_workflow_comp(
        "deterministic_policy",
        _DeterministicPolicyComponent(),
        inputs_schema={
            "observation": "${semantic_validation.observation}",
            "usage": "${semantic_validation.usage}",
            "competency_id": "${start.competency_id}",
            "followup_count": "${start.followup_count}",
            "remaining_roots": "${start.remaining_roots}",
            "allowed_followup_intents": "${start.allowed_followup_intents}",
            "decision_id": "${start.decision_id}",
        },
    )
    workflow.set_end_comp(
        "end",
        End(),
        inputs_schema={
            "observation": "${deterministic_policy.observation}",
            "decision": "${deterministic_policy.decision}",
            "usage": "${deterministic_policy.usage}",
        },
    )
    workflow.add_connection("start", "analyzer")
    workflow.add_connection("analyzer", "semantic_validation")
    workflow.add_connection("semantic_validation", "deterministic_policy")
    workflow.add_connection("deterministic_policy", "end")
    return workflow


async def _invoke_bounded(invocation, timeout_seconds: float) -> WorkflowOutput:
    error: BaseException | None = None
    async with get_task_manager().task_group() as group:
        try:
            return await asyncio.wait_for(invocation, timeout=timeout_seconds)
        except BaseException as exc:  # noqa: BLE001 - includes task cancellation.
            error = exc
        finally:
            # The SDK may create child tasks. They belong to this invocation and
            # must not outlive a timeout, cancellation, or node failure.
            group.cancel_scope.cancel()
    if error is None:
        raise AssertionError("bounded workflow invocation produced no result")
    raise error


def _checked_output(output: WorkflowOutput) -> dict[str, Any]:
    if not isinstance(output, WorkflowOutput):
        raise AnswerWorkflowError("openJiuwen did not return WorkflowOutput")
    if output.state != WorkflowExecutionState.COMPLETED:
        raise AnswerWorkflowError(
            f"openJiuwen workflow did not complete: {output.state}"
        )
    if not isinstance(output.result, dict) or set(output.result) != {"output"}:
        raise AnswerWorkflowError("openJiuwen workflow result has an invalid envelope")
    result = output.result["output"]
    if not isinstance(result, dict) or set(result) != {
        "observation",
        "decision",
        "usage",
    }:
        raise AnswerWorkflowError("openJiuwen workflow result has an invalid shape")
    observation = result["observation"]
    if not isinstance(observation, dict) or set(observation) != _OBSERVATION_KEYS:
        raise AnswerWorkflowError("workflow result has no validated Observation")
    decision = result["decision"]
    if (
        not isinstance(decision, dict)
        or set(decision) != _DECISION_KEYS
        or decision.get("action") not in _ALLOWED_ACTIONS
        or decision.get("observation_id") != observation.get("id")
        or decision.get("root_question_id") != observation.get("root_question_id")
    ):
        raise AnswerWorkflowError("workflow result has no valid policy Decision")
    usage = result["usage"]
    if not isinstance(usage, dict) or set(usage) != _USAGE_KEYS:
        raise AnswerWorkflowError("workflow result has invalid usage facts")
    for field_name in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage[field_name]
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise AnswerWorkflowError("workflow result has invalid usage facts")
    cost = usage["cost"]
    if cost is not None and (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or cost < 0
    ):
        raise AnswerWorkflowError("workflow result has invalid usage facts")
    return result


def _require_nonempty(value: Any, name: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{name} must be at most {max_length} characters")
    return value


def _require_nonnegative_integer(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _workflow_contract_error(exc: Exception) -> Exception:
    """Recover application errors wrapped by the SDK component boundary."""
    pending: list[BaseException | None] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (AnswerWorkflowError, ObservationValidationError)):
            return current
        pending.extend((current.__cause__, current.__context__))
    return AnswerWorkflowError("openJiuwen answer workflow execution failed")


async def run_handle_answer_workflow(
    *,
    analyzer: AnswerAnalyzer,
    observation_id: str,
    answer_id: str,
    question_id: str,
    root_question_id: str,
    question_text: str,
    answer_text: str,
    rubric_snapshot: dict[str, Any],
    competency_id: str,
    followup_count: int,
    remaining_roots: int,
    allowed_followup_intents: Sequence[str],
    decision_id: str,
    reference_material: Any = None,
    timeout_seconds: float = 60,
) -> dict[str, Any]:
    """Execute one bounded real-SDK handle-answer workflow invocation."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be a finite positive number")
    if not isinstance(rubric_snapshot, dict):
        raise TypeError("rubric_snapshot must be an object")
    if isinstance(allowed_followup_intents, (str, bytes)):
        raise TypeError("allowed_followup_intents must be a sequence of strings")
    try:
        intents = list(allowed_followup_intents)
    except TypeError as exc:
        raise ValueError(
            "allowed_followup_intents must be a sequence of strings"
        ) from exc
    if any(not isinstance(intent, str) or not intent for intent in intents):
        raise ValueError("allowed_followup_intents must contain non-empty strings")

    inputs = {
        "observation_id": _require_nonempty(observation_id, "observation_id"),
        "answer_id": _require_nonempty(answer_id, "answer_id"),
        "question_id": _require_nonempty(question_id, "question_id"),
        "root_question_id": _require_nonempty(root_question_id, "root_question_id"),
        "question_text": _require_nonempty(question_text, "question_text"),
        "answer_text": _require_nonempty(answer_text, "answer_text", max_length=6000),
        "rubric_snapshot": rubric_snapshot,
        "reference_material": reference_material,
        "competency_id": _require_nonempty(competency_id, "competency_id"),
        "followup_count": _require_nonnegative_integer(
            followup_count, "followup_count"
        ),
        "remaining_roots": _require_nonnegative_integer(
            remaining_roots, "remaining_roots"
        ),
        "allowed_followup_intents": intents,
        "decision_id": _require_nonempty(decision_id, "decision_id"),
    }
    workflow = build_handle_answer_workflow(analyzer)
    session = create_workflow_session(session_id=uuid4().hex)
    try:
        output = await _invoke_bounded(
            workflow.invoke(inputs, session), float(timeout_seconds)
        )
    except TimeoutError:
        raise
    except Exception as exc:
        raise _workflow_contract_error(exc) from exc
    return _checked_output(output)
