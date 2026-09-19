"""Operation 状态机与幂等输入哈希（docs/04 §3、api.md §1/§7）。

规则来源：
- queued → running → succeeded / failed / interrupted；queued 亦可因资料删除记 canceled。
- 所有终态不可原地再运行；retry 创建新的 operation 并以 parent_operation_id 链接。
- 幂等判定使用规范化业务输入哈希：同 key 同输入返回原操作，同 key 不同输入冲突。
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELED = "canceled"


TERMINAL_STATUSES = frozenset(
    {
        OperationStatus.SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.INTERRUPTED,
        OperationStatus.CANCELED,
    }
)

TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.QUEUED: frozenset(
        {OperationStatus.RUNNING, OperationStatus.CANCELED}
    ),
    OperationStatus.RUNNING: frozenset(
        {OperationStatus.SUCCEEDED, OperationStatus.FAILED, OperationStatus.INTERRUPTED}
    ),
    **{status: frozenset() for status in TERMINAL_STATUSES},
}


class InvalidStateTransition(ValueError):
    """状态转移不在允许表中；调用方不得吞掉后继续提交。"""


def ensure_transition(
    current: OperationStatus, target: OperationStatus
) -> OperationStatus:
    if target not in TRANSITIONS[current]:
        raise InvalidStateTransition(f"{current} -> {target}")
    return target


def canonical_input_hash(payload: object) -> str:
    """对 JSON 可序列化业务输入做规范化 SHA256。

    key 排序、拒绝 NaN、UTF-8 字节稳定；multipart 场景由调用方传
    文件 bytes hash + profile_id + expected_revision（api.md §1），不要把
    boundary 之类传输噪声放进来。
    """
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
