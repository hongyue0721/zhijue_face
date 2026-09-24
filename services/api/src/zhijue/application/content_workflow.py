"""Real openJiuwen workflow for grounded coaching and resume generation.

扩展边界（研究分支 R1）：本模块只允许两种注入，且默认值即生产行为——
`observer` 只读观测（异常一律被吞，不改输入/输出/状态），`validator` 决定
SemanticValidation 节点用哪种确定性策略（默认仍是逐字保留的 grounding 校验）。
研究约束差异走 Strategy，不引入通用 callback/plugin 机制。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable
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

from zhijue.application.answer_workflow import (
    AnalysisResult,
    ModelRequestError,
    ModelRequestTimeoutError,
)
from zhijue.domain.grounded_content import (
    GroundedContentValidationError,
    validate_claim_extraction_candidate,
    validate_coaching_candidate,
    validate_resume_candidate,
)

ContentTask = Literal["extract_claims", "coach_answers", "compose_resume"]
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens", "cost"})


class ContentWorkflowError(RuntimeError):
    """The workflow or generated candidate violated the application contract."""


logger = logging.getLogger("zhijue.content_workflow")


@runtime_checkable
class ContentGenerator(Protocol):
    """Port for one untrusted content candidate, never a persisted resource."""

    async def generate(
        self, *, task: ContentTask, payload: dict[str, Any]
    ) -> AnalysisResult: ...


@runtime_checkable
class ContentValidator(Protocol):
    """Strategy port for the SemanticValidation node.

    生产默认实现是 `validate_grounded_content_candidate`（确定性来源校验）；
    研究 M0-M2 传入"只保证是 JSON 对象、不做事实校验"的策略。
    抛任何异常都按既有规则折叠成固定契约错误，模型原文不进异常记录。
    """

    def validate(
        self, *, task: str, payload: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class GenerationInputEvent:
    """观察者看到的模型输入：task 与即将序列化进 user content 的 payload。"""

    task: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RawGenerationEvent:
    """模型原文与 usage；即使随后校验失败也必须先被观察到。"""

    task: str
    payload: Mapping[str, Any]
    content: str
    usage: Mapping[str, Any]
    finish_reason: str | None


@dataclass(frozen=True, slots=True)
class ValidationSuccessEvent:
    task: str
    payload: Mapping[str, Any]
    content: str
    candidate: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ValidationFailureEvent:
    """结构化失败分类。

    `reason_code` 是机器可读诊断（如 `INVALID_ANSWER_QUOTE`），只流向观察者；
    生产异常仍是不含模型文本的固定消息。
    """

    task: str
    payload: Mapping[str, Any]
    content: str
    reason_code: str
    reason_detail: str


@runtime_checkable
class ContentWorkflowObserver(Protocol):
    """只读旁路。禁止修改 payload/content/candidate，也禁止抛回业务。"""

    def on_generation_input(self, event: GenerationInputEvent) -> None: ...

    def on_raw_generation(self, event: RawGenerationEvent) -> None: ...

    def on_validation_success(self, event: ValidationSuccessEvent) -> None: ...

    def on_validation_failure(self, event: ValidationFailureEvent) -> None: ...


def _notify(observer: ContentWorkflowObserver | None, hook: str, event: Any) -> None:
    """观察者异常永不影响 Workflow；只记录钩子名与异常类型，不落任何业务内容。"""

    if observer is None:
        return
    try:
        getattr(observer, hook)(event)
    except Exception as exc:  # noqa: BLE001 - 旁路观测不得改变业务结果
        logger.warning(
            "content workflow observer hook %s failed: %s", hook, type(exc).__name__
        )


def _read_only(value: dict[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(value)


class _GeneratorComponent(WorkflowComponent):
    def __init__(
        self, generator: ContentGenerator, observer: ContentWorkflowObserver | None
    ) -> None:
        super().__init__()
        self._generator = generator
        self._observer = observer

    async def invoke(self, inputs, session, context):
        self._notify_input(inputs["task"], inputs["payload"])
        result = await self._generator.generate(
            task=inputs["task"], payload=inputs["payload"]
        )
        if not isinstance(result, AnalysisResult):
            raise ContentWorkflowError("content generator must return AnalysisResult")
        _notify(
            self._observer,
            "on_raw_generation",
            RawGenerationEvent(
                task=inputs["task"],
                payload=_read_only(inputs["payload"]),
                content=result.content,
                usage=_read_only(dict(result.usage())),
                finish_reason=result.finish_reason,
            ),
        )
        return {"content": result.content, "usage": result.usage()}

    def _notify_input(self, task: str, payload: dict[str, Any]) -> None:
        _notify(
            self._observer,
            "on_generation_input",
            GenerationInputEvent(task=task, payload=_read_only(payload)),
        )


_WORKFLOW_ERROR_CODES = {
    "content generator returned invalid JSON": "SCHEMA_INVALID",
    "content generator output must be one object": "SCHEMA_INVALID",
    "duplicate extraction source block": "DUPLICATE_SOURCE_BLOCK",
    "unsupported content task": "UNSUPPORTED_TASK",
}


def _reason_code(exc: BaseException) -> str:
    """把内部失败分类成稳定 code，仅供观察者使用。

    生产不返回这些值，也不改变折叠后的固定消息；未登记的内部错误明确落到
    UNCLASSIFIED_*，不猜成别的分类。
    """

    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(exc, ContentWorkflowError):
        return _WORKFLOW_ERROR_CODES.get(str(exc), "UNCLASSIFIED_WORKFLOW_FAILURE")
    if isinstance(exc, KeyError):
        return "PAYLOAD_KEY_MISSING"
    if isinstance(exc, TypeError):
        return "PAYLOAD_TYPE_INVALID"
    return "UNCLASSIFIED_WORKFLOW_FAILURE"


class GroundingContentValidator:
    """生产默认确定性来源校验（与 d91023a 的判定顺序逐条一致）。"""

    def validate(
        self, *, task: str, payload: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]:
        if task == "extract_claims":
            source_blocks = {
                block["id"]: block["text"] for block in payload["source_blocks"]
            }
            if len(source_blocks) != len(payload["source_blocks"]):
                raise ContentWorkflowError("duplicate extraction source block")
            return validate_claim_extraction_candidate(
                candidate,
                source_blocks=source_blocks,
            )
        if task == "coach_answers":
            return validate_coaching_candidate(
                candidate,
                report_id=payload["report_id"],
                answers_by_root=payload["answers_by_root"],
                allowed_claims=payload["allowed_claims"],
            )
        if task == "compose_resume":
            return validate_resume_candidate(
                candidate,
                draft_id=payload["draft_id"],
                allowed_claims=payload["allowed_claims"],
            )
        raise ContentWorkflowError("unsupported content task")


_GROUNDING_CONTENT_VALIDATOR = GroundingContentValidator()


class _GroundingValidationComponent(WorkflowComponent):
    """SemanticValidation 节点。

    折叠行为保持不变：任何具体失败对外仍只有一条不含模型文本的固定消息；
    差别仅在于观察者拿到的是折叠之前的结构化分类。
    """

    def __init__(
        self,
        validator: ContentValidator,
        observer: ContentWorkflowObserver | None,
    ) -> None:
        super().__init__()
        self._validator = validator
        self._observer = observer

    async def invoke(self, inputs, session, context):
        task = inputs["task"]
        payload = inputs["payload"]
        content = inputs["content"]
        try:
            candidate = _parse_json_object(content)
            validated = self._validator.validate(
                task=task, payload=payload, candidate=candidate
            )
        except (
            ContentWorkflowError,
            GroundedContentValidationError,
            KeyError,
            TypeError,
        ) as exc:
            # Never place raw model content in the SDK exception record.
            _notify(
                self._observer,
                "on_validation_failure",
                ValidationFailureEvent(
                    task=task,
                    payload=_read_only(payload),
                    content=content,
                    reason_code=_reason_code(exc),
                    reason_detail=str(exc),
                ),
            )
            raise ContentWorkflowError(
                "generated content failed contract validation"
            ) from None
        _notify(
            self._observer,
            "on_validation_success",
            ValidationSuccessEvent(
                task=task,
                payload=_read_only(payload),
                content=content,
                candidate=_read_only(dict(validated)),
            ),
        )
        return {"candidate": validated, "usage": inputs["usage"]}


def _parse_json_object(content: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            content,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContentWorkflowError("content generator returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ContentWorkflowError("content generator output must be one object")
    return parsed


def build_grounded_content_workflow(
    generator: ContentGenerator,
    *,
    validator: ContentValidator | None = None,
    observer: ContentWorkflowObserver | None = None,
) -> Workflow:
    """Build the official Start→Generator→SemanticValidation→End graph.

    `validator=None` 与 `observer=None` 就是 d91023a 的生产图：确定性来源校验、
    无旁路观测。图结构、节点名、inputs_schema 与连接顺序均不变。
    """
    card = WorkflowCard(
        id=f"grounded_content_{uuid4().hex}",
        name="grounded_content",
        version="1.0.0",
        input_params={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task": {
                    "type": "string",
                    "enum": ["extract_claims", "coach_answers", "compose_resume"],
                },
                "payload": {"type": "object"},
            },
            "required": ["task", "payload"],
        },
    )
    workflow = Workflow(card=card)
    workflow.set_start_comp(
        "start",
        Start(),
        inputs_schema={"task": "${task}", "payload": "${payload}"},
    )
    workflow.add_workflow_comp(
        "generator",
        _GeneratorComponent(generator, observer),
        inputs_schema={"task": "${start.task}", "payload": "${start.payload}"},
    )
    workflow.add_workflow_comp(
        "semantic_validation",
        _GroundingValidationComponent(
            validator if validator is not None else _GROUNDING_CONTENT_VALIDATOR,
            observer,
        ),
        inputs_schema={
            "task": "${start.task}",
            "payload": "${start.payload}",
            "content": "${generator.content}",
            "usage": "${generator.usage}",
        },
    )
    workflow.set_end_comp(
        "end",
        End(),
        inputs_schema={
            "candidate": "${semantic_validation.candidate}",
            "usage": "${semantic_validation.usage}",
        },
    )
    workflow.add_connection("start", "generator")
    workflow.add_connection("generator", "semantic_validation")
    workflow.add_connection("semantic_validation", "end")
    return workflow


async def _invoke_bounded(invocation, timeout_seconds: float) -> WorkflowOutput:
    error: BaseException | None = None
    async with get_task_manager().task_group() as group:
        try:
            return await asyncio.wait_for(invocation, timeout=timeout_seconds)
        except BaseException as exc:  # noqa: BLE001 - includes cancellation.
            error = exc
        finally:
            group.cancel_scope.cancel()
    if error is None:
        raise AssertionError("bounded content workflow produced no result")
    raise error


def _workflow_contract_error(exc: Exception) -> Exception:
    pending: list[BaseException | None] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(
            current,
            (
                ModelRequestTimeoutError,
                ModelRequestError,
                ContentWorkflowError,
                GroundedContentValidationError,
            ),
        ):
            return current
        pending.extend((current.__cause__, current.__context__))
    return ContentWorkflowError("openJiuwen content workflow execution failed")


def _checked_output(output: WorkflowOutput) -> dict[str, Any]:
    if not isinstance(output, WorkflowOutput):
        raise ContentWorkflowError("openJiuwen did not return WorkflowOutput")
    if output.state != WorkflowExecutionState.COMPLETED:
        raise ContentWorkflowError(
            f"openJiuwen content workflow did not complete: {output.state}"
        )
    if not isinstance(output.result, dict) or set(output.result) != {"output"}:
        raise ContentWorkflowError("content workflow result has an invalid envelope")
    result = output.result["output"]
    if not isinstance(result, dict) or set(result) != {"candidate", "usage"}:
        raise ContentWorkflowError("content workflow result has an invalid shape")
    if not isinstance(result["candidate"], dict):
        raise ContentWorkflowError("content workflow has no validated candidate")
    usage = result["usage"]
    if not isinstance(usage, dict) or set(usage) != _USAGE_KEYS:
        raise ContentWorkflowError("content workflow has invalid usage facts")
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage[key]
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ContentWorkflowError("content workflow has invalid usage facts")
    cost = usage["cost"]
    if cost is not None and (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or cost < 0
    ):
        raise ContentWorkflowError("content workflow has invalid usage facts")
    return result


async def run_grounded_content_workflow(
    *,
    generator: ContentGenerator,
    task: ContentTask,
    payload: dict[str, Any],
    timeout_seconds: float = 60,
    validator: ContentValidator | None = None,
    observer: ContentWorkflowObserver | None = None,
) -> dict[str, Any]:
    """Execute one bounded real-SDK content workflow invocation."""

    if task not in ("extract_claims", "coach_answers", "compose_resume"):
        raise ValueError("unsupported content task")
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be a finite positive number")

    workflow = build_grounded_content_workflow(
        generator, validator=validator, observer=observer
    )
    session = create_workflow_session(session_id=uuid4().hex)
    try:
        output = await _invoke_bounded(
            workflow.invoke({"task": task, "payload": payload}, session),
            float(timeout_seconds),
        )
    except TimeoutError:
        raise
    except Exception as exc:
        raise _workflow_contract_error(exc) from exc
    return _checked_output(output)
