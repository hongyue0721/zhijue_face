"""M1-01 仓储测试：幂等受理、事件只追加单调、契约校验、恢复语义（临时 SQLite，无模型）。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError

from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import Base
from zhijue.adapters.db.operations import (
    IdempotencyConflict,
    OperationCommand,
    OperationRepository,
    canon_scope,
)
from zhijue.domain.operations import OperationStatus, canonical_input_hash


@pytest.fixture()
def repo(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return OperationRepository(engine)


def start_command(scope_extra: str = "") -> OperationCommand:
    return OperationCommand(
        kind="answer_submit",
        resource_type="interview",
        resource_id="interview_test1",
        scope=canon_scope("local", "POST", f"/api/v1/interviews/answer{scope_extra}"),
        idempotency_key="answer-demo-turn-0001",
        input={"answer_text": "我们加了锁"},
    )


def test_first_accept_creates_queued_operation(repo):
    op = repo.accept(start_command())
    assert op.status == OperationStatus.QUEUED
    assert op.attempts == 0


def test_same_key_same_input_returns_original(repo):
    first = repo.accept(start_command())
    replay = repo.accept(start_command())
    assert replay.id == first.id
    # 重放不推进状态、不增加尝试。
    assert replay.status == first.status


def test_same_key_different_input_conflicts(repo):
    repo.accept(start_command())
    changed = replace(start_command(), input={"answer_text": "我们没加锁"})
    with pytest.raises(IdempotencyConflict):
        repo.accept(changed)


def test_events_append_monotonic_and_unique(repo):
    op = repo.accept(start_command())
    repo.transition(op.id, OperationStatus.RUNNING)
    seq1 = repo.append_event(
        op.id, "operation.started", {"kind": op.kind, "resource_id": op.resource_id}
    )
    seq2 = repo.append_event(op.id, "node.started", {"node_id": "extract"})
    assert (seq1, seq2) == (1, 2)
    fresh = repo.get(op.id)
    assert fresh.last_event_seq == 2
    with pytest.raises(IntegrityError):
        repo._insert_raw_event(
            op.id, 1, "node.started", {"node_id": "dup"}
        )  # (op,seq) 唯一


def test_event_payload_must_satisfy_contract_schema(repo):
    op = repo.accept(start_command())
    repo.transition(op.id, OperationStatus.RUNNING)
    # 契约要求 node.started 携带 node_id；缺字段必须拒绝而不是静默入库。
    with pytest.raises(ValueError, match="node_id"):
        repo.append_event(op.id, "node.started", {"wrong": "field"})


def test_events_after_terminal_are_rejected(repo):
    op = repo.accept(start_command())
    repo.transition(op.id, OperationStatus.RUNNING)
    repo.transition(op.id, OperationStatus.SUCCEEDED)
    with pytest.raises(ValueError):
        repo.append_event(op.id, "node.started", {"node_id": "late"})


def test_transition_enforces_state_machine(repo):
    op = repo.accept(start_command())
    with pytest.raises(ValueError):
        repo.transition(op.id, OperationStatus.SUCCEEDED)  # queued 不能直达成功


def test_retry_creates_child_operation_with_link(repo):
    op = repo.accept(start_command())
    repo.transition(op.id, OperationStatus.RUNNING)
    repo.transition(op.id, OperationStatus.FAILED)
    original = repo.get(op.id)
    retry = repo.retry(op.id)
    assert retry.parent_operation_id == op.id
    assert retry.id != op.id  # 终态行不复活
    assert retry.status == OperationStatus.QUEUED
    assert retry.input_hash == original.input_hash
    assert retry.attempts == original.attempts  # 累计预算跨父子不清零


def test_retry_budget_accumulates_across_parent_chain(repo):
    operation = repo.accept(start_command())
    repo.transition(operation.id, OperationStatus.RUNNING)
    repo.transition(operation.id, OperationStatus.FAILED)

    second_attempt = repo.retry(operation.id)
    repo.transition(second_attempt.id, OperationStatus.RUNNING)
    repo.transition(second_attempt.id, OperationStatus.FAILED)
    third_attempt = repo.retry(second_attempt.id)
    repo.transition(third_attempt.id, OperationStatus.RUNNING)
    repo.transition(third_attempt.id, OperationStatus.FAILED)

    with pytest.raises(ValueError, match="budget exhausted"):
        repo.retry(third_attempt.id)


def test_retry_idempotency_detects_changed_retry_request(repo):
    operation = repo.accept(start_command())
    repo.transition(operation.id, OperationStatus.RUNNING)
    repo.transition(operation.id, OperationStatus.FAILED)
    child = repo.retry(
        operation.id,
        idempotency_key="retry-key-0001",
        request_input={"expected_revision": 2},
    )

    replay = repo.retry(
        operation.id,
        idempotency_key="retry-key-0001",
        request_input={"expected_revision": 2},
    )
    assert replay.id == child.id
    with pytest.raises(IdempotencyConflict):
        repo.retry(
            operation.id,
            idempotency_key="retry-key-0001",
            request_input={"expected_revision": 3},
        )


def test_retry_rejects_non_failed_states(repo):
    op = repo.accept(start_command())
    with pytest.raises(ValueError):
        repo.retry(op.id)  # queued 不是失败，不允许"重试"
    repo.transition(op.id, OperationStatus.RUNNING)
    repo.transition(op.id, OperationStatus.SUCCEEDED)
    with pytest.raises(ValueError):
        repo.retry(op.id)  # 成功终态同样拒绝


def test_restart_marks_running_interrupted_without_replaying(repo):
    op = repo.accept(start_command())
    repo.transition(op.id, OperationStatus.RUNNING)
    queued = repo.accept(
        replace(
            start_command(),
            scope=canon_scope("local", "POST", "/api/v1/x"),
            idempotency_key="other-key-0002",
        )
    )
    interrupted = repo.mark_interrupted_on_restart()
    assert interrupted == [op.id]
    assert repo.get(op.id).status == OperationStatus.INTERRUPTED
    assert repo.get(queued.id).status == OperationStatus.QUEUED
    # queued 可安全重新入队，但仓储本身不改它的状态。
    assert repo.requeue_pending() == [queued.id]


def test_idempotency_scope_isolates_method_and_path(repo):
    first = repo.accept(start_command())
    other = replace(
        start_command(), scope=canon_scope("local", "POST", "/api/v1/interviews/other")
    )
    fresh = repo.accept(other)
    assert fresh.id != first.id  # 不同 scope 同 key 不互相冲突


def test_method_case_normalized_in_scope(repo):
    op = repo.accept(start_command())
    replay = replace(
        start_command(), scope=canon_scope("local", "post", "/api/v1/interviews/answer")
    )
    assert repo.accept(replay).id == op.id


def test_canonical_input_hash_used_for_conflict_detection(repo):
    op = repo.accept(start_command())
    reordered = replace(start_command(), input={"answer_text": "我们加了锁"})
    assert canonical_input_hash(reordered.input) == op.input_hash
    assert repo.accept(reordered).id == op.id  # 等价输入命中原操作
