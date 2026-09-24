"""数据集内存模型：真值 (Ground Truth) 与两种投影视图。

可见性是本模块的核心不变式：

- `CandidateFacts` / `GroundTruth` 只供 Dataset 与 Evaluator 使用；
- `GeneratorCaseView` 是唯一可以进入 Prompt 的对象，构造时就把 evaluator-only
  字段丢弃（不是"记得不用"，而是类型上拿不到）；
- `EvaluatorCaseView` 只供离线判定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

# evaluator-only 字段名；loader 会断言它们不出现在 GeneratorCaseView 的任何层级。
EVALUATOR_ONLY_KEYS = (
    "expected_evidence_fact_ids",
    "allowed_context_ids",
    "injected_drift",
    "answer_style_rating",
    "trap_claims",
    "ground_truth",
    "notes",
)


@dataclass(frozen=True, slots=True)
class CandidateFact:
    """一条可回查的候选人真值。"""

    fact_id: str
    context_id: str
    predicate: str
    value: str
    polarity: str
    confirmed: bool
    provenance_kind: str
    provenance_locator: str
    verbatim: str

    def source_id_for(self, *, candidate_id: str) -> str:
        """RAG 事实级索引的稳定 ID：`candidate_x:F03`。"""

        return f"{candidate_id}:{self.fact_id}"

    def as_prompt_text(self) -> str:
        """证据块文本：只含事实本身，不含真值标签。"""

        return f"[{self.fact_id} · {self.context_id} · {self.predicate}] {self.value}"


@dataclass(frozen=True, slots=True)
class GroundTruth:
    candidate_id: str
    domain: str
    data_status: str
    facts: tuple[CandidateFact, ...]
    trap_claims: tuple[dict[str, Any], ...]
    raw: Mapping[str, Any] = field(default_factory=dict)

    def fact(self, fact_id: str) -> CandidateFact | None:
        return next((item for item in self.facts if item.fact_id == fact_id), None)

    def confirmed_facts(self) -> tuple[CandidateFact, ...]:
        return tuple(item for item in self.facts if item.confirmed)

    def context_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.context_id for item in self.facts}))


@dataclass(frozen=True, slots=True)
class GeneratorCaseView:
    """允许进入模型输入的唯一 case 形态。"""

    case_id: str
    candidate_id: str
    split: str
    question_wording: str
    competency_tags: tuple[str, ...]
    turns: tuple[tuple[str, str, str], ...]  # (answer_id, kind, text)
    retrieval_query_template: str

    def answer_text(self) -> str:
        return "\n".join(text for _, _, text in self.turns)

    def answers_by_root(self, root_id: str) -> dict[str, str]:
        return {answer_id: text for answer_id, _, text in self.turns}

    def root_questions(self, root_id: str) -> dict[str, str]:
        return {root_id: self.question_wording}


@dataclass(frozen=True, slots=True)
class EvaluatorCaseView:
    """只供离线判定；禁止被方法层 import。"""

    case_id: str
    expected_evidence_fact_ids: tuple[str, ...]
    allowed_context_ids: tuple[str, ...]
    injected_drift: tuple[dict[str, Any], ...]
    answer_style_rating: str | None


@dataclass(frozen=True, slots=True)
class InterviewCase:
    generator: GeneratorCaseView
    evaluator: EvaluatorCaseView
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        return self.generator.case_id

    @property
    def split(self) -> str:
        return self.generator.split


@dataclass(frozen=True, slots=True)
class CandidateBundle:
    ground_truth: GroundTruth
    cases: tuple[InterviewCase, ...]
    private_kb_documents: Mapping[str, str]

    def case(self, case_id: str) -> InterviewCase | None:
        return next((item for item in self.cases if item.case_id == case_id), None)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType({"private_kb": self.private_kb_documents})
