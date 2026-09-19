"""M1-01 纯域测试：Operation 状态机、幂等输入哈希与 ID 规范（docs/04 §3、api.md §1—§3）。"""

import re

import pytest

from zhijue.domain.ids import new_id
from zhijue.domain.operations import (
    TERMINAL_STATUSES,
    TRANSITIONS,
    InvalidStateTransition,
    OperationStatus,
    canonical_input_hash,
    ensure_transition,
)


def test_terminal_states_cannot_move_anywhere():
    for status in TERMINAL_STATUSES:
        assert TRANSITIONS[status] == frozenset()


def test_queued_can_run_or_cancel_but_not_succeed():
    assert (
        ensure_transition(OperationStatus.QUEUED, OperationStatus.RUNNING)
        is OperationStatus.RUNNING
    )
    assert (
        ensure_transition(OperationStatus.QUEUED, OperationStatus.CANCELED)
        is OperationStatus.CANCELED
    )
    with pytest.raises(InvalidStateTransition):
        ensure_transition(OperationStatus.QUEUED, OperationStatus.SUCCEEDED)


def test_running_splits_into_three_exclusive_ends():
    for target in (
        OperationStatus.SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.INTERRUPTED,
    ):
        assert ensure_transition(OperationStatus.RUNNING, target) is target
    with pytest.raises(InvalidStateTransition):
        ensure_transition(OperationStatus.RUNNING, OperationStatus.QUEUED)


def test_interrupted_is_not_retryable_via_same_operation():
    # retry 必须新建 operation（parent 链接），终态本身不可原地复活。
    assert TRANSITIONS[OperationStatus.INTERRUPTED] == frozenset()
    assert TRANSITIONS[OperationStatus.FAILED] == frozenset()


def test_canonical_input_hash_is_order_and_format_stable():
    a = canonical_input_hash({"x": 1, "y": [1, 2], "z": {"k": "值"}})
    b = canonical_input_hash({"z": {"k": "值"}, "y": [1, 2], "x": 1})
    assert a == b
    # 内容变化必须改变哈希（幂等冲突检测的前提）。
    assert a != canonical_input_hash({"x": 1, "y": [2, 1], "z": {"k": "值"}})


@pytest.mark.parametrize("prefix", ("profile", "operation", "question"))
def test_new_id_shape(prefix):
    value = new_id(prefix)
    assert re.fullmatch(rf"{prefix}_[0-9a-f]{{20}}", value)
    assert value != new_id(prefix)
