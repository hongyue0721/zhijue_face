"""实验编排：case × method × model → 一条 trace。

集中强制防污染与公平性不变式：

- I3 一个 cell 一次生成：validator 拒绝后**不**重调模型；`attempts` 来自真实调用计数。
- I4 M2/M3 复用同一个 `EvidenceSet` 实例：检索每 case 只发生一次。
- 保留原始输出：即使被确定性 validator 拒绝，raw 文本与 reason code 也要落盘。
- 生成侧输入做出口扫描：真值结构键、trap 文本、evaluator 标签出现即整格失败
  （`LEAKAGE_BLOCKED`），并把失败事实写进 trace，不静默跳过。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zhijue.application.answer_workflow import (
    ModelRequestError,
    ModelRequestTimeoutError,
)
from zhijue.application.content_workflow import (
    ContentWorkflowError,
    run_grounded_content_workflow,
)

from zhijue_research.config import ExperimentConfig
from zhijue_research.dataset.models import (
    CandidateBundle,
    GeneratorCaseView,
    GroundTruth,
)
from zhijue_research.evidence import EvidenceSet, claim_ref_for
from zhijue_research.methods.base import UnvalidatedContentValidator
from zhijue_research.methods.four import METHOD_BY_ID, BaseMethod
from zhijue_research.model_clients import PromptBoundGenerator
from zhijue_research.observer import RecordingObserver
from zhijue_research.prompts import PromptRegistry
from zhijue_research.retrieval import RetrievalProvider
from zhijue_research.trace import TRACE_SCHEMA_VERSION, now_rfc3339, validate_trace

#: 业务 Workflow 只接受既有 content task 字面量；研究差异全部由 Strategy 表达。
WORKFLOW_TASK = "coach_answers"

#: 生成侧禁止出现的标签结构键（真值/标签专用字段名）。
LABEL_MARKERS = (
    "ground_truth",
    "fact_id",
    "trap_id",
    "trap_claims",
    "expected_labels",
    "expected_evidence_fact_ids",
    "injected_drift",
    "answer_style_rating",
    "allowed_context_ids",
    "provenance",
    "polarity",
    "basis_fact_ids",
)
MIN_LEAK_NEEDLE_CHARS = 8


class LeakageError(RuntimeError):
    """生成侧输入含真值结构/标签：实验污染，本格立即失败。"""


class RunnerError(RuntimeError):
    """runner 配置或输入不一致。"""


@dataclass(slots=True)
class CellResult:
    case_id: str
    method_id: str
    accepted: bool
    attempts: int
    record: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExperimentRunner:
    """一个 candidate 一个 runner：provider 已与 KB 绑定，避免跨候选人串证据。"""

    config: ExperimentConfig
    prompts: PromptRegistry
    client: Any
    retrieval: RetrievalProvider
    bundle: CandidateBundle
    provider_name: str
    model_name: str
    model_fingerprint: str

    async def run(self) -> list[CellResult]:
        """逐 case 检索一次，再跑该 case 的所有臂。

        `bundle.cases` 是 `InterviewCase`：方法只拿 `case.generator`（生成侧视图），
        evaluator 标签留在这里、只用于 trace 之后的离线 join。
        """

        results: list[CellResult] = []
        for case in self.bundle.cases:
            evidence = await self._retrieve(case.generator)
            for method_id in self.config.methods:
                results.append(
                    await self.run_cell(
                        case=case.generator, method_id=method_id, evidence=evidence
                    )
                )
        return results

    async def _retrieve(self, case: GeneratorCaseView) -> EvidenceSet | None:
        needs_evidence = any(
            METHOD_BY_ID[method_id].requires_evidence
            for method_id in self.config.methods
        )
        if not needs_evidence:
            return None
        evidence = await self.retrieval.retrieve(case)
        evidence.require_candidate()
        return evidence

    async def run_cell(
        self, *, case: GeneratorCaseView, method_id: str, evidence: EvidenceSet | None
    ) -> CellResult:
        method = METHOD_BY_ID.get(method_id)
        if method is None:
            raise RunnerError(f"未注册的方法：{method_id}")
        if method.requires_evidence and evidence is None:
            raise RunnerError(f"{method_id} 需要检索证据，但本次运行没有证据上下文")
        if not method.requires_evidence:
            evidence = None  # 结构性保证：M0/M1 拿不到证据对象，而不是"记得不用"

        prompt = self.prompts.load(method_id, self.config.prompt_versions[method_id])
        request = method.build_request(case=case, evidence=evidence, prompt=prompt)
        forbidden = trap_texts(self.bundle.ground_truth)
        assert_clean_generation_input(request.payload, forbidden)

        observer = RecordingObserver()
        generator = PromptBoundGenerator(
            method_id=method_id, system_prompt=request.system_prompt, client=self.client
        )
        calls_before = call_count_of(self.client)
        started = time.monotonic()
        workflow_error: str | None = None
        candidate: dict[str, Any] | None = None
        normalized: Sequence[Any] = ()
        try:
            outcome = await run_grounded_content_workflow(
                generator=generator,
                task=WORKFLOW_TASK,  # type: ignore[arg-type]
                payload=request.payload,
                timeout_seconds=self.config.model.timeout_seconds,
                validator=None
                if method.hard_validation
                else UnvalidatedContentValidator(),
                observer=observer,
            )
            candidate = outcome["candidate"]
            normalized = method.normalize(candidate)
        except (
            ContentWorkflowError,
            ModelRequestError,
            ModelRequestTimeoutError,
        ) as exc:
            workflow_error = type(exc).__name__
        except Exception as exc:  # noqa: BLE001 - 未预期异常也要留下事实，不吞
            workflow_error = f"unexpected:{type(exc).__name__}"
        latency_ms = int((time.monotonic() - started) * 1000)
        attempts = max(call_count_of(self.client) - calls_before, 0)

        record = self._build_record(
            case=case,
            method=method,
            prompt=prompt,
            request=request,
            observer=observer,
            candidate=candidate,
            normalized=normalized,
            latency_ms=latency_ms,
            attempts=attempts,
            workflow_error=workflow_error,
        )
        validate_trace(record)
        return CellResult(
            case_id=case.case_id,
            method_id=method_id,
            accepted=candidate is not None,
            attempts=record["attempts"],
            record=record,
            error=workflow_error,
        )

    def _build_record(
        self,
        *,
        case: GeneratorCaseView,
        method: BaseMethod,
        prompt: Any,
        request: Any,
        observer: RecordingObserver,
        candidate: dict[str, Any] | None,
        normalized: Sequence[Any],
        latency_ms: int,
        attempts: int,
        workflow_error: str | None,
    ) -> dict[str, Any]:
        observed = observer.observed
        usage = observed.usage or {}
        cost = self.config.estimated_cost(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        experiment_key = self.config.experiment_key(
            case_id=case.case_id,
            method_id=method.method_id,
            model_fingerprint=self.model_fingerprint,
        )
        reasons = list(observed.validation_reasons)
        if workflow_error and not reasons:
            reasons = ["TRANSPORT_ERROR"]
        status = _validation_status(method, observed.validation_status, workflow_error)
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "run_id": self.config.derive_run_id(experiment_key),
            "experiment_key": experiment_key,
            "case_id": case.case_id,
            "candidate_id": self.bundle.ground_truth.candidate_id,
            "domain": self.bundle.ground_truth.domain,
            "split": case.split,
            "method_id": method.method_id,
            "task": method.task,
            "provider": self.provider_name,
            "model": self.model_name,
            "model_fingerprint": self.model_fingerprint,
            "config_fingerprint": self.config.fingerprint,
            "dataset_version": self.config.dataset_version,
            "prompt_version": prompt.version,
            "prompt_hash": prompt.sha256,
            "input_hash": observed.input_hash or "",
            "evidence_input_hash": (
                None if request.evidence is None else evidence_hash(request.evidence)
            ),
            "retrieval": (
                None
                if request.evidence is None
                else self.retrieval.trace_block(request.evidence, expected_fact_ids=())
            ),
            "raw_output": {
                "content": observed.raw_content,
                "finish_reason": observed.finish_reason,
                "truncated": (
                    None
                    if observed.finish_reason is None
                    else observed.finish_reason == "length"
                ),
                "parse_status": _parse_status(
                    observed.validation_status, workflow_error
                ),
            },
            "normalized_output": (
                None
                if candidate is None
                else {"items": [item.as_trace_dict() for item in normalized]}
            ),
            "validation": {
                "performed": method.hard_validation,
                "status": status,
                "reasons": [
                    reason for reason in reasons if reason in ALLOWED_TRACE_REASONS
                ],
                "accepted": candidate is not None,
            },
            "latency_ms": latency_ms,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cost": cost["cost"],
            "cost_basis": cost["cost_basis"],
            "attempts": attempts,
            "observer_failures": observed.observer_failures,
            "created_at": now_rfc3339(),
            "model_driver": str(getattr(self.client, "driver_kind", "unknown")),
        }


#: trace 只允许登记已分类的 reason code；未分类的一律显式改名，不塞任意字符串。
ALLOWED_TRACE_REASONS = frozenset(
    {
        "SCHEMA_INVALID",
        "REPORT_ID_MISMATCH",
        "DUPLICATE_ROOT",
        "UNKNOWN_ROOT",
        "INVALID_ANSWER_QUOTE",
        "CLAIM_OUTSIDE_SNAPSHOT",
        "UNKNOWN_SOURCE",
        "UNBOUND_NUMERIC_FACT",
        "UNBOUND_HIGH_RISK_ASSERTION",
        "UNBOUND_TECHNICAL_TOKEN",
        "SEGMENT_MISMATCH",
        "CLAIM_SUMMARY_MISMATCH",
        "COVERAGE_MISMATCH",
        "PAYLOAD_KEY_MISSING",
        "PAYLOAD_TYPE_INVALID",
        "UNCLASSIFIED_GROUNDED_CONTENT_FAILURE",
        "TRANSPORT_ERROR",
        "UNCLASSIFIED_WORKFLOW_FAILURE",
    }
)


def trap_texts(ground_truth: GroundTruth) -> tuple[str, ...]:
    values = [str(item.get("value", "")) for item in ground_truth.trap_claims]
    return tuple(text for text in values if len(text) >= MIN_LEAK_NEEDLE_CHARS)


def assert_clean_generation_input(
    payload: Mapping[str, Any], forbidden: Sequence[str]
) -> None:
    import json

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for marker in LABEL_MARKERS:
        if f'"{marker}"' in serialized:
            raise LeakageError(f"LEAKAGE_BLOCKED：生成侧输入含真值/标签结构键 {marker}")
    for needle in {
        str(value) for value in forbidden if len(str(value)) >= MIN_LEAK_NEEDLE_CHARS
    }:
        if needle in serialized:
            raise LeakageError(
                f"LEAKAGE_BLOCKED：生成侧输入含 trap 文本片段 {needle[:24]}…"
            )


def evidence_hash(evidence: EvidenceSet) -> str:
    from zhijue_research.io_utils import sha256_text

    return sha256_text(
        "\n".join(
            f"{item.rank}\t{item.source_id}\t{item.text}" for item in evidence.items
        )
    )


def claim_refs(evidence: EvidenceSet) -> dict[str, str]:
    return {claim_ref_for(item): item.source_id for item in evidence.items}


def call_count_of(client: Any) -> int:
    value = getattr(client, "call_count", None)
    return int(value) if isinstance(value, int) else 0


def _parse_status(validation_status: str | None, workflow_error: str | None) -> str:
    if workflow_error and workflow_error != "ContentWorkflowError":
        return "transport_error"
    if validation_status is None:
        return "invalid_json" if workflow_error else "not_attempted"
    return "parsed"


def _validation_status(
    method: BaseMethod, observed_status: str | None, workflow_error: str | None
) -> str:
    if not method.hard_validation:
        return "not_performed"
    if workflow_error:
        return "failed"
    return observed_status or "not_attempted"


ProviderFactory = Callable[[CandidateBundle], RetrievalProvider]
