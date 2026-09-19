"""Claim 生命周期纯规则（docs/03 §3/§4/§5）。

不依赖 ORM/框架：状态机与引文校验是 domain 不变量，应用层负责落库。
"""

from __future__ import annotations

from enum import StrEnum


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
