"""M1-01 仓储测试：幂等受理、事件只追加单调、契约校验、恢复语义（临时 SQLite，无模型）。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import Base, Operation
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


def test_restart_marks_running_and_queued_interrupted_without_replaying(repo):
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
    assert set(interrupted) == {op.id, queued.id}
    assert repo.get(op.id).status == OperationStatus.INTERRUPTED
    assert repo.get(queued.id).status == OperationStatus.INTERRUPTED
    # BackgroundTasks 的 callable 不持久化；重启后不能假装可安全自动重放。
    assert repo.requeue_pending() == []


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


def test_retry_rejects_new_key_sibling_and_replays_after_budget_change(repo):
    original = repo.accept(start_command())
    repo.transition(original.id, OperationStatus.RUNNING)
    repo.transition(original.id, OperationStatus.FAILED)
    child = repo.retry(original.id, idempotency_key="first-retry")
    repo.transition(child.id, OperationStatus.RUNNING)
    repo.transition(child.id, OperationStatus.FAILED)
    with pytest.raises(ValueError, match="latest operation"):
        repo.retry(original.id, idempotency_key="sibling-retry")
    assert (
        repo.retry(original.id, idempotency_key="first-retry", max_attempts=1).id
        == child.id
    )
    third = repo.retry(child.id, idempotency_key="tail-retry")
    repo.transition(third.id, OperationStatus.RUNNING)
    repo.transition(third.id, OperationStatus.FAILED)
    with pytest.raises(ValueError, match="budget exhausted"):
        repo.retry(third.id, idempotency_key="fourth-retry")


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_retry_repositories_admit_one_successor(repo, same_key):
    original = repo.accept(start_command())
    repo.transition(original.id, OperationStatus.RUNNING)
    repo.transition(original.id, OperationStatus.FAILED)
    barrier = Barrier(2)

    def retry(index):
        other = OperationRepository(repo._engine)
        barrier.wait()
        try:
            return other.retry(
                original.id,
                idempotency_key="concurrent" if same_key else f"concurrent-{index}",
            ).id
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(retry, range(2)))
    assert len({value for value in results if value is not None}) == 1
    assert results.count(None) == (0 if same_key else 1)


def test_legacy_retry_forks_share_one_logical_budget(repo):
    original = repo.accept(start_command())
    repo.transition(original.id, OperationStatus.RUNNING)
    repo.transition(original.id, OperationStatus.FAILED)
    child = repo.retry(original.id, idempotency_key="legacy-child-one")
    repo.transition(child.id, OperationStatus.RUNNING)
    repo.transition(child.id, OperationStatus.FAILED)
    with Session(repo._engine) as session, session.begin():
        session.add(
            Operation(
                id="operation_legacy_sibling",
                kind=original.kind,
                resource_type=original.resource_type,
                resource_id=original.resource_id,
                scope=child.scope,
                idempotency_key="legacy-child-two",
                input_hash=original.input_hash,
                parent_operation_id=original.id,
                status=OperationStatus.FAILED,
                attempts=2,
            )
        )
    with pytest.raises(ValueError, match="budget exhausted"):
        repo.retry(child.id, idempotency_key="legacy-fourth-call")


def test_concurrent_start_claims_one_actual_attempt(repo):
    operation = repo.accept(start_command())
    barrier = Barrier(2)

    def start(_index):
        other = OperationRepository(repo._engine)
        barrier.wait()
        return other.start(operation.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(start, range(2))) == [False, True]
    stored = repo.get(operation.id)
    assert stored.attempts == 1
    assert stored.status == OperationStatus.RUNNING
    events = repo.events_after(operation.id, 0)
    assert len(events) == 1
    assert events[0].event_type == "operation.started"


def test_retry_provenance_comes_from_durable_events_and_legacy_parent_rows(repo):
    original = repo.accept(start_command())
    assert repo.retry_metadata(original) == {
        "retry_trigger": None,
        "next_operation_id": None,
        "retry_reason": None,
        "chain_started_at": original.created_at,
    }
    repo.start(original.id)
    repo.transition(original.id, OperationStatus.FAILED)
    automatic = repo.retry(original.id, idempotency_key="automatic-child")
    repo.append_event(
        automatic.id,
        "operation.retry_scheduled",
        {
            "parent_operation_id": original.id,
            "trigger": "automatic",
            "reason": "correction",
        },
    )
    repo.start(automatic.id)
    repo.transition(automatic.id, OperationStatus.FAILED)
    manual = repo.retry(automatic.id, idempotency_key="legacy-manual-child")
    assert repo.retry_metadata(original)["next_operation_id"] == automatic.id
    assert repo.retry_metadata(automatic) == {
        "retry_trigger": "automatic",
        "next_operation_id": manual.id,
        "retry_reason": "correction",
        "chain_started_at": original.created_at,
    }
    assert repo.retry_metadata(manual) == {
        "retry_trigger": "manual",
        "next_operation_id": None,
        "retry_reason": None,
        "chain_started_at": original.created_at,
    }
    assert repo.events_after(automatic.id, 0)[1].payload == {
        "kind": automatic.kind,
        "resource_id": automatic.resource_id,
    }


def test_retry_scheduling_event_cannot_persist_private_correction_context(repo):
    operation = repo.accept(start_command())
    with pytest.raises(ValueError, match="violates contract"):
        repo.append_event(
            operation.id,
            "operation.retry_scheduled",
            {
                "parent_operation_id": "operation_original",
                "trigger": "automatic",
                "reason": "correction",
                "repair_context": {"previous_output": "private model response"},
            },
        )
    assert repo.events_after(operation.id, 0) == []
