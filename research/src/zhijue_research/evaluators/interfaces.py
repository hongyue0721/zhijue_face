"""为未来 LLM judge 预留的接口 + 仅测试用 fixture 实现。

本轮（R4）零模型、零网络：这里只有 `Protocol` 契约和确定性的粗糙 fixture。
所有 `Fixture*` 类都是为了让 runner/聚合代码能离线跑通而存在，
**不代表真实判定质量**，禁止把它们的输出写进论文结论。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from zhijue_research.evidence import EvidenceItem

from .deterministic import numeric_facts, substantive_tokens


@dataclass(frozen=True, slots=True)
class AtomicClaim:
    """从生成文本里切出的最小可判陈述。"""

    claim_id: str
    text: str


class Verdict(StrEnum):
    """claim 相对证据的判定结果；UNKNOWN 是必备档，禁止在证据不足时强判。"""

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    claim_id: str
    verdict: Verdict
    evidence_source_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class UtilityScore:
    """回答对问题的有用度（0.0–1.0）；真实实现将来自 LLM judge。"""

    score: float
    rationale: str


@runtime_checkable
class AtomicClaimExtractor(Protocol):
    """把生成文本切成原子陈述（未来 LLM judge 第一步）。"""

    def extract(self, *, output_text: str) -> tuple[AtomicClaim, ...]: ...


@runtime_checkable
class ClaimEvidenceJudge(Protocol):
    """判定单条 claim 与证据集的关系（未来 LLM judge 第二步）。"""

    def judge(
        self, *, claim: AtomicClaim, evidences: Sequence[EvidenceItem]
    ) -> JudgeVerdict: ...


@runtime_checkable
class UtilityJudge(Protocol):
    """对候选回答的有用度打分（未来 LLM judge 第三步）。"""

    def score(
        self, *, question: str, answer: str, candidate_answer: str
    ) -> UtilityScore: ...


# --------------------------------------------------------------------------
# fixture 实现：确定性、粗糙、可离线复算；只用于打通代码路径。
# --------------------------------------------------------------------------


def _claim_anchors(text: str) -> set[str]:
    """fixture 的可核对锚点 = 数字段 ∪ 非噪音技术 token（casefold）。"""

    return set(numeric_facts(text)) | {
        token.casefold() for token in substantive_tokens(text)
    }


class FixtureAtomicClaimExtractor:
    """fixture，不代表真实判定质量：按中英文句子分隔符粗切，不识别并列子句。"""

    _SEPARATORS = "。！？!?；;\n\r"

    def extract(self, *, output_text: str) -> tuple[AtomicClaim, ...]:
        parts: list[str] = []
        buffer: list[str] = []
        for char in output_text:
            if char in self._SEPARATORS:
                if "".join(buffer).strip():
                    parts.append("".join(buffer).strip())
                buffer = []
            else:
                buffer.append(char)
        if "".join(buffer).strip():
            parts.append("".join(buffer).strip())
        return tuple(
            AtomicClaim(claim_id=f"claim_{i:02d}", text=text)
            for i, text in enumerate(parts, 1)
        )


class FixtureClaimEvidenceJudge:
    """fixture，不代表真实判定质量：只看 claim 的数字/技术锚点是否被证据文本覆盖。

    可复算规则：
    - 无证据，或 claim 内没有任何可核对锚点 → UNKNOWN；
    - 全部锚点出现在证据文本并集里 → SUPPORTED（附任一锚点命中的证据 source_id）；
    - 否则 → UNSUPPORTED（附缺失锚点）。
    fixture 永不产出 CONTRADICTED：反义/矛盾超出字符串覆盖能力，留给真实 judge。
    """

    def judge(
        self, *, claim: AtomicClaim, evidences: Sequence[EvidenceItem]
    ) -> JudgeVerdict:
        if not evidences:
            return JudgeVerdict(
                claim.claim_id, Verdict.UNKNOWN, (), "fixture：没有可比对的证据"
            )
        anchors = _claim_anchors(claim.text)
        if not anchors:
            return JudgeVerdict(
                claim.claim_id,
                Verdict.UNKNOWN,
                (),
                "fixture：claim 内没有数字/技术锚点，无法判定",
            )
        blob_anchors = _claim_anchors("\n".join(item.text for item in evidences))
        matched = tuple(
            item.source_id for item in evidences if anchors & _claim_anchors(item.text)
        )
        missing = sorted(anchors - blob_anchors)
        if not missing:
            return JudgeVerdict(
                claim.claim_id,
                Verdict.SUPPORTED,
                matched,
                "fixture：全部锚点被证据覆盖",
            )
        return JudgeVerdict(
            claim.claim_id,
            Verdict.UNSUPPORTED,
            matched,
            f"fixture：锚点未被证据覆盖: {', '.join(missing)}",
        )


class FixtureUtilityJudge:
    """fixture，不代表真实判定质量：按问题锚点在候选回答中的覆盖率打分。

    `answer`（候选人原回答）不参与计算，仅为真实 judge 保留接口位；
    问题无锚点时给 0.0 并说明，绝不虚报满分。
    """

    def score(
        self, *, question: str, answer: str, candidate_answer: str
    ) -> UtilityScore:
        anchors = _claim_anchors(question)
        if not anchors:
            return UtilityScore(0.0, "fixture：问题中没有可核对的数字/技术锚点")
        covered = _claim_anchors(candidate_answer)
        hit = anchors & covered
        return UtilityScore(
            len(hit) / len(anchors),
            f"fixture：问题锚点覆盖 {len(hit)}/{len(anchors)}（answer 原文未参与计算）",
        )
