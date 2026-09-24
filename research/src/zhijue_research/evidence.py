"""检索证据的稳定形状。

`source_id` 必须能反解到 `candidate_id / fact_id`，因为论文要回答
"这句话是哪条候选人事实支持的"，而不只是"模型输出像不像真的"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SOURCE_ID_PATTERN = re.compile(
    r"^(?P<candidate>candidate_[0-9a-z_]{2,}):(?P<fact>F[0-9]{2,})$"
)


class EvidenceError(ValueError):
    """证据来源不可追踪或与当前 candidate 不一致。"""


def make_source_id(*, candidate_id: str, fact_id: str) -> str:
    source_id = f"{candidate_id}:{fact_id}"
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise EvidenceError(f"SOURCE_ID_INVALID: {source_id}")
    return source_id


#: coaching-result 契约的 claim_id 只允许 `[A-Za-z][A-Za-z0-9_-]`，不允许冒号；
#: 因此 KB source_id 与 validator claim_id 之间必须显式换算，不能靠"差不多能用"。
CLAIM_REF_SEPARATOR = "__"


def claim_ref_for(source: EvidenceItem | str) -> str:
    source_id = source if isinstance(source, str) else source.source_id
    return source_id.replace(":", CLAIM_REF_SEPARATOR)


def source_id_from_claim_ref(claim_ref: str) -> str:
    return claim_ref.replace(CLAIM_REF_SEPARATOR, ":", 1)


def parse_source_id(source_id: str) -> tuple[str, str]:
    match = SOURCE_ID_PATTERN.fullmatch(source_id or "")
    if match is None:
        raise EvidenceError(f"UNKNOWN_SOURCE: {source_id!r}")
    return match.group("candidate"), match.group("fact")


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """一条可回查证据：来自 RAG 命中，或来自候选人自己的回答。"""

    source_id: str
    text: str
    fact_id: str | None
    rank: int
    score: float | None
    generation: str | None
    chunk_id: str | None

    @property
    def is_answer(self) -> bool:
        return self.fact_id is None

    def as_prompt_line(self) -> str:
        return f"[{self.source_id}] {self.text}"


@dataclass(frozen=True, slots=True)
class EvidenceSet:
    """一次检索的有序结果；M2 与 M3 必须拿到同一个实例（I4）。"""

    candidate_id: str
    query: str
    top_k: int
    items: tuple[EvidenceItem, ...]

    def source_ids(self) -> tuple[str, ...]:
        return tuple(item.source_id for item in self.items)

    def texts(self) -> dict[str, str]:
        return {item.source_id: item.text for item in self.items}

    def require_candidate(self) -> None:
        for item in self.items:
            candidate, _ = parse_source_id(item.source_id)
            if candidate != self.candidate_id:
                raise EvidenceError(
                    f"CROSS_CANDIDATE_SOURCE: {item.source_id} 属于 {candidate}，"
                    f"当前实验只允许 {self.candidate_id}"
                )
