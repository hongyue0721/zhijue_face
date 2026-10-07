"""Claim 生命周期纯规则（docs/03 §3/§4/§5）。

不依赖 ORM/框架：状态机与引文校验是 domain 不变量，应用层负责落库。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeVar


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    RETRACTED = "retracted"


class InvalidClaimTransition(ValueError):
    """非法 Claim 状态迁移。业务上等价于 409 语义冲突。"""


# proposed -> confirmed/disputed/retracted；confirmed -> retracted（撤回保留历史）；
# disputed 保留冲突，用户裁决后可 confirmed 或 retracted；retracted 是终态。
_ALLOWED: dict[ClaimStatus, frozenset[ClaimStatus]] = {
    ClaimStatus.PROPOSED: frozenset(
        {ClaimStatus.CONFIRMED, ClaimStatus.DISPUTED, ClaimStatus.RETRACTED}
    ),
    ClaimStatus.CONFIRMED: frozenset({ClaimStatus.RETRACTED}),
    ClaimStatus.DISPUTED: frozenset({ClaimStatus.CONFIRMED, ClaimStatus.RETRACTED}),
    ClaimStatus.RETRACTED: frozenset(),
}


def ensure_transition(current: ClaimStatus, target: ClaimStatus) -> ClaimStatus:
    allowed = _ALLOWED[current]
    if target not in allowed:
        raise InvalidClaimTransition(
            f"claim 状态不允许 {current.value} -> {target.value}"
        )
    return target


def validate_exact_quote(exact_quote: str, block_text: str) -> str:
    """引文必须真实存在于来源块（AGENTS §2：被引文本核验）。"""
    if not exact_quote.strip():
        raise ValueError("exact_quote 不能为空")
    if exact_quote not in block_text:
        raise ValueError("exact_quote 不是来源块文本的子串，拒绝写入")
    return exact_quote


# ---------------- 阅读顺序（ProfileView 展示序） ----------------


@dataclass(frozen=True)
class SourcePosition:
    """来源块在档案材料中的位置；document_rank 是材料文档的登记先后。"""

    document_rank: int
    page_number: int | None
    block_index: int
    block_text: str


class OrderableClaim(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def created_at(self) -> str: ...

    @property
    def source_block_ids(self) -> Sequence[Any]: ...

    @property
    def source_quotes(self) -> Sequence[Any]: ...

    @property
    def supersedes_id(self) -> str | None: ...


ClaimT = TypeVar("ClaimT", bound=OrderableClaim)
_Anchor = tuple[int, int, int, int]


def _own_anchor(
    claim: OrderableClaim, positions: Mapping[str, SourcePosition]
) -> _Anchor | None:
    """一条事实在材料中的最早出现处：文档→页→块→块内引文偏移。"""
    quotes_by_block = {
        quote.get("source_block_id"): quote.get("exact_quote") or ""
        for quote in claim.source_quotes
        if isinstance(quote, Mapping)
    }
    anchors: list[_Anchor] = []
    for block_id in claim.source_block_ids:
        position = positions.get(block_id)
        if position is None:
            continue
        quote = quotes_by_block.get(block_id, "")
        offset = position.block_text.find(quote) if quote else 0
        anchors.append(
            (
                position.document_rank,
                position.page_number or 0,
                position.block_index,
                max(offset, 0),
            )
        )
    return min(anchors) if anchors else None


def order_claims_for_reading(
    claims: Sequence[ClaimT], positions: Mapping[str, SourcePosition]
) -> list[ClaimT]:
    """按材料阅读顺序排列事实，供核对界面与原文对照。

    同一次抽取的事实 created_at 相同，按随机 ID 排序会打乱简历原文顺序，
    让核对变成在乱序碎片里找上下文。规则：
    - 有可解析来源块的事实按“文档登记先后 → 页 → 块 → 块内引文位置”排列；
    - 本人更正（supersedes_id）沿用被更正事实的位置，紧随其后，保持原文语境；
    - 找不到来源位置的事实（例如来源块已不存在）不猜位置，排在最后；
    - 位置相同按 created_at、id 稳定排序。
    只影响展示顺序，不改变确认快照内容。
    """
    by_id = {claim.id: claim for claim in claims}
    own = {claim.id: _own_anchor(claim, positions) for claim in claims}

    def inherited_anchor(claim: OrderableClaim) -> _Anchor | None:
        # 沿 supersedes 链找到最早的原始事实；链上任一环缺失时停在已知最早处。
        origin: OrderableClaim = claim
        seen = {claim.id}
        while origin.supersedes_id is not None:
            predecessor = by_id.get(origin.supersedes_id)
            if predecessor is None or predecessor.id in seen:
                break
            seen.add(predecessor.id)
            origin = predecessor
        return own[origin.id] or own[claim.id]

    def sort_key(claim: ClaimT) -> tuple[int, _Anchor, str, str]:
        anchor = inherited_anchor(claim)
        if anchor is None:
            return (1, (0, 0, 0, 0), claim.created_at, claim.id)
        return (0, anchor, claim.created_at, claim.id)

    return sorted(claims, key=sort_key)
