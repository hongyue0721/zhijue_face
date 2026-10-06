"""Real openJiuwen workflow for grounded coaching and resume generation."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import uuid4

from openjiuwen.core.common.task_manager import get_task_manager
from openjiuwen.core.session.constants import WORKFLOW_EXECUTE_TIMEOUT
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
    _sdk_timeout_error,
)
from zhijue.application.model_output import unwrap_code_fence
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

    def __init__(
        self, message: str, *, repair_context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        # Deliberately absent from exception args/repr and SDK/public records.
        self.repair_context = repair_context


@runtime_checkable
class ContentGenerator(Protocol):
    """Port for one untrusted content candidate, never a persisted resource."""

    async def generate(
        self, *, task: ContentTask, payload: dict[str, Any]
    ) -> AnalysisResult: ...


class _GeneratorComponent(WorkflowComponent):
    def __init__(
        self,
        generator: ContentGenerator,
        repair_context: dict[str, Any] | None,
        failures: list[Exception],
    ) -> None:
        super().__init__()
        self._generator = generator
        self._repair_context = repair_context
        self._failures = failures

    async def invoke(self, inputs, session, context):
        payload = inputs["payload"]
        if self._repair_context is not None:
            payload = {**payload, "repair_context": self._repair_context}
        try:
            result = await self._generator.generate(
                task=inputs["task"], payload=payload
            )
        except ModelRequestError as exc:
            self._failures.append(exc)
            raise
        if not isinstance(result, AnalysisResult):
            raise ContentWorkflowError("content generator must return AnalysisResult")
        return {"content": result.content, "usage": result.usage()}


class _GroundingValidationComponent(WorkflowComponent):
    def __init__(self, failures: list[Exception]) -> None:
        super().__init__()
        self._failures = failures

    async def invoke(self, inputs, session, context):
        try:
            candidate = _parse_json_object(inputs["content"])
            payload = inputs["payload"]
            if inputs["task"] == "extract_claims":
                source_blocks = {
                    block["id"]: block["text"] for block in payload["source_blocks"]
                }
                if len(source_blocks) != len(payload["source_blocks"]):
                    raise ContentWorkflowError("duplicate extraction source block")
                validated = validate_claim_extraction_candidate(
                    candidate,
                    source_blocks=source_blocks,
                )
            elif inputs["task"] == "coach_answers":
                validated = validate_coaching_candidate(
                    candidate,
                    report_id=payload["report_id"],
                    answers_by_root=payload["answers_by_root"],
                    allowed_claims=payload["allowed_claims"],
                )
            elif inputs["task"] == "compose_resume":
                validated = validate_resume_candidate(
                    candidate,
                    draft_id=payload["draft_id"],
                    allowed_claims=payload["allowed_claims"],
                )
            else:
                raise ContentWorkflowError("unsupported content task")
        except GroundedContentValidationError as exc:
            repair_context = None
            if _has_repair_sources(inputs["task"], inputs["payload"]):
                repair_context = {
                    "previous_output": inputs["content"],
                    "issues": exc.issues,
                }
            error = ContentWorkflowError(
                "generated content failed contract validation",
                repair_context=repair_context,
            )
            self._failures.append(error)
            # The SDK receives only a safe message, never raw model content.
            raise error from None
        except (ContentWorkflowError, KeyError, TypeError):
            error = ContentWorkflowError("generated content failed contract validation")
            self._failures.append(error)
            raise error from None
        return {"candidate": validated, "usage": inputs["usage"]}


def _has_repair_sources(task: ContentTask, payload: dict[str, Any]) -> bool:
    claims = payload.get("allowed_claims")
    if not isinstance(claims, dict):
        return False
    has_claims = any(isinstance(text, str) and text.strip() for text in claims.values())
    if task == "compose_resume":
        return has_claims and isinstance(payload.get("draft_id"), str)
    if task == "coach_answers":
        roots = payload.get("answers_by_root")
        return (
            isinstance(payload.get("report_id"), str)
            and isinstance(roots, dict)
            and bool(roots)
            and all(
                isinstance(answers, dict)
                and (
                    has_claims
                    or any(
                        isinstance(text, str) and text.strip()
                        for text in answers.values()
                    )
                )
                for answers in roots.values()
            )
        )
    return False


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
            unwrap_code_fence(content),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        raise GroundedContentValidationError(
            "content generator returned invalid JSON", code="invalid_json"
        ) from None
    if not isinstance(parsed, dict):
        raise GroundedContentValidationError(
            "content generator output must be one object", code="schema.type"
        )
    return parsed


def build_grounded_content_workflow(
    generator: ContentGenerator,
    *,
    repair_context: dict[str, Any] | None = None,
    _failures: list[Exception] | None = None,
) -> Workflow:
    """Build the official Start→Generator→SemanticValidation→End graph."""

    failures = _failures if _failures is not None else []
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
        _GeneratorComponent(generator, repair_context, failures),
        inputs_schema={"task": "${start.task}", "payload": "${start.payload}"},
    )
    workflow.add_workflow_comp(
        "semantic_validation",
        _GroundingValidationComponent(failures),
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
    repair_context: dict[str, Any] | None = None,
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

    if repair_context is not None and not _has_repair_sources(task, payload):
        raise ContentWorkflowError(
            "content correction requires original factual sources"
        )
    # SDK wrappers can discard Python causes. Capture typed failures per invocation;
    # private candidate/context never enters workflow input, events or error strings.
    failures: list[Exception] = []
    workflow = build_grounded_content_workflow(
        generator, repair_context=repair_context, _failures=failures
    )
    session = create_workflow_session(
        session_id=uuid4().hex, envs={WORKFLOW_EXECUTE_TIMEOUT: float(timeout_seconds)}
    )
    try:
        output = await _invoke_bounded(
            workflow.invoke({"task": task, "payload": payload}, session),
            float(timeout_seconds),
        )
    except TimeoutError:
        raise
    except Exception as exc:
        if failures:
            raise failures[0] from None
        timeout = _sdk_timeout_error(exc, float(timeout_seconds))
        if timeout is not None:
            raise timeout from exc
        raise _workflow_contract_error(exc) from exc
    return _checked_output(output)
