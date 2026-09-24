"""数据集内存模型：真值 (Ground Truth) 与两种投影视图。

可见性是本模块的核心不变式：

- `CandidateFacts` / `GroundTruth` 只供 Dataset 与 Evaluator 使用；
- `GeneratorCaseView` 是唯一可以进入 Prompt 的对象，构造时就把 evaluator-only
  字段丢弃（不是"记得不用"，而是类型上拿不到）；
- `EvaluatorCaseView` 只供离线判定。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

_FACT_ID = re.compile(r"^F[0-9]{2,}$")
_CONTEXT_ID = re.compile(r"^(self|proj_[0-9a-z_]+|course_[0-9a-z_]+|work_[0-9a-z_]+)$")
POLARITIES = frozenset({"positive", "negative", "uncertain"})

# evaluator-only 字段名；泄漏守卫按这些键扫描最终模型输入。
# 只登记真值/标签专用键：`notes` 在别处是合法字段名，不列入避免误报。
EVALUATOR_ONLY_KEYS = (
    "expected_evidence_fact_ids",
    "allowed_context_ids",
    "injected_drift",
    "answer_style_rating",
    "trap_claims",
    "ground_truth",
    "verbatim",
    "provenance",
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

    def __post_init__(self) -> None:
        """字段类型与取值必须成立：真值模型不接受"看起来差不多"的值。

        否则一个位置参数写错的 fixture 会静默变成 confirmed=True，
        把未确认事实索引进 KB，实验结论直接被污染。
        """

        if not _FACT_ID.fullmatch(self.fact_id):
            raise ValueError(f"fact_id 非法：{self.fact_id!r}")
        if not _CONTEXT_ID.fullmatch(self.context_id):
            raise ValueError(f"context_id 非法：{self.context_id!r}")
        if self.polarity not in POLARITIES:
            raise ValueError(f"polarity 必须是 {POLARITIES}，得到 {self.polarity!r}")
        if not isinstance(self.confirmed, bool):
            # 非 bool 是类型错误，不是取值错误：位置参数写错时必须立刻暴露。
            raise TypeError(f"confirmed 必须是 bool，得到 {self.confirmed!r}")
        if not self.value.strip():
            raise ValueError("fact value 不能为空")

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
