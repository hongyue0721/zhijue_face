"""方法 Strategy 契约：四臂只差事实约束强度，其余全部相同（I5）。

同一 case、同一 model、同一 temperature/reasoning_effort/max_tokens/timeout、
同一 transport、每 cell 一次生成；只有 system prompt、payload 结构与是否做确定性硬校验不同。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from zhijue_research.dataset.models import GeneratorCaseView
from zhijue_research.evidence import EvidenceSet, claim_ref_for
from zhijue_research.prompts import Prompt

#: 三档输出契约；四臂共用同一个最小 JSON 信封，格式不构成事实约束。
TASK_ANSWER_ONLY = "answer_only"
TASK_ANSWER_WITH_EVIDENCE = "answer_with_evidence"
TASK_EVIDENCE_BOUND = "evidence_bound"


class MethodError(ValueError):
    """方法输入/输出违反研究契约。"""


def root_id_for(case: GeneratorCaseView) -> str:
    """一个 case 一个根题；id 稳定可推导，便于跨臂对齐同一条回答。"""

    return f"root_{case.case_id}"


def answers_by_root(case: GeneratorCaseView) -> dict[str, dict[str, str]]:
    return {root_id_for(case): {answer_id: text for answer_id, _, text in case.turns}}


def report_id_for(case: GeneratorCaseView) -> str:
    """M3 复用生产 validator，需要一个稳定的 report_id；用 case_id 派生，不引入新随机量。"""

    return f"report_{case.case_id}"


def root_questions(case: GeneratorCaseView) -> dict[str, str]:
    return {root_id_for(case): case.question_wording}


def evidence_block(evidence: EvidenceSet) -> list[dict[str, str]]:
    """M2/M3 共用同一份证据呈现；顺序即检索顺序（I4）。"""

    return [{"source_id": item.source_id, "text": item.text} for item in evidence.items]


def allowed_claims_from(evidence: EvidenceSet) -> dict[str, str]:
    """M3 的可校验声明集。

    键是 claim_ref：coaching-result 契约的 claim_id 不允许冒号，而 KB source_id 用冒号
    表达 `candidate:fact`，因此这里显式换算，trace/eval 侧再换算回去。
    """

    return {claim_ref_for(item): item.text for item in evidence.items}


@dataclass(frozen=True, slots=True)
class MethodRequest:
    """一次模型调用的全部输入；runner 只把它交给 workflow，不再加工。"""

    system_prompt: str
    payload: dict[str, Any]
    evidence: EvidenceSet | None
    hard_validation: bool

    def payload_without_prompt(self) -> dict[str, Any]:
        return self.payload


@dataclass(frozen=True, slots=True)
class MethodItem:
    """跨臂可比的规范化产物。`segments=None` 表示该臂不做来源绑定。"""

    root_question_id: str
    rewritten_answer: str
    used_claim_ids: tuple[str, ...] | None
    segments: tuple[dict[str, Any], ...] | None

    def as_trace_dict(self) -> dict[str, Any]:
        return {
            "root_question_id": self.root_question_id,
            "rewritten_answer": self.rewritten_answer,
            "used_claim_ids": (
                None if self.used_claim_ids is None else list(self.used_claim_ids)
            ),
            "segments": None
            if self.segments is None
            else [dict(s) for s in self.segments],
        }

    def answer_text(self) -> str:
        return self.rewritten_answer


class CoachingMethod(Protocol):
    """一个实验臂。实现必须无状态、无副作用、不访问 ground truth。"""

    method_id: str
    task: str
    requires_evidence: bool
    hard_validation: bool

    def build_request(
        self, *, case: GeneratorCaseView, evidence: EvidenceSet | None, prompt: Prompt
    ) -> MethodRequest: ...

    def normalize(self, candidate: dict[str, Any]) -> tuple[MethodItem, ...]: ...


def normalize_open_envelope(candidate: dict[str, Any]) -> tuple[MethodItem, ...]:
    """M0-M2 的最小信封：`{"root_question_id": ..., "rewritten_answer": ...}`。"""

    item = candidate.get("items")
    if not isinstance(item, list) or not item:
        raise MethodError("OPEN_ENVELOPE_ITEMS_MISSING")
    items: list[MethodItem] = []
    for entry in item:
        if not isinstance(entry, dict):
            raise MethodError("OPEN_ENVELOPE_ITEM_NOT_OBJECT")
        root_id = entry.get("root_question_id")
        rewritten = entry.get("rewritten_answer")
        if (
            not isinstance(root_id, str)
            or not isinstance(rewritten, str)
            or not rewritten.strip()
        ):
            raise MethodError("OPEN_ENVELOPE_FIELD_INVALID")
        items.append(
            MethodItem(
                root_question_id=root_id,
                rewritten_answer=rewritten,
                used_claim_ids=None,
                segments=None,
            )
        )
    return tuple(items)


def normalize_evidence_bound(candidate: dict[str, Any]) -> tuple[MethodItem, ...]:
    """M3 经过 `validate_coaching_candidate` 后的结构（segments + used_claim_ids）。"""

    items: list[MethodItem] = []
    for entry in candidate.get("items", []):
        items.append(
            MethodItem(
                root_question_id=entry["root_question_id"],
                rewritten_answer=entry["rewritten_answer"],
                used_claim_ids=tuple(entry.get("used_claim_ids", ())),
                segments=tuple(entry.get("segments", ())),
            )
        )
    if not items:
        raise MethodError("EVIDENCE_BOUND_ITEMS_MISSING")
    return tuple(items)


class UnvalidatedContentValidator:
    """M0-M2 的确定性策略：只保证 SemanticValidation 节点收到 JSON 对象，不做事实校验。

    这是行为差异（Strategy），不是观测差异；业务默认值仍是 grounding 校验。
    """

    def validate(
        self, *, task: str, payload: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]:
        del task, payload
        return candidate
