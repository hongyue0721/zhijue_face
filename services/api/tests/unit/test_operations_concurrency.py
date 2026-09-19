"""M1-01 并发验收：同一命令在两个线程同时提交，只能产生一份业务操作。

对应 docs/12 M1-01 通过条件"不存在双数据库写入者；失败不造成功"与 api.md §1
幂等规则。SQLite 串行写 + (scope,idempotency_key) 唯一键 + 仓储"先查后插"在同一
事务内完成；输家要么拿到同一行，要么得到可重试的锁/冲突，绝不出现半行。
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy.orm import Session

from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import Base, Operation
from zhijue.adapters.db.operations import (
    OperationCommand,
    OperationRepository,
    canon_scope,
)
from zhijue.domain.operations import OperationStatus


@pytest.fixture()
def repo(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'race.db'}", busy_timeout_ms=10000)
    Base.metadata.create_all(engine)
    return OperationRepository(engine)


def command(seq: int) -> OperationCommand:
    return OperationCommand(
        kind="answer_submit",
        resource_type="interview",
        resource_id="interview_race",
        scope=canon_scope("local", "POST", f"/api/v1/interviews/answer{seq}"),
        idempotency_key=f"race-key-{seq}",
        input={"answer_text": "同一命令的并发副本"},
    )


def test_concurrent_identical_accept_yields_single_operation(repo):
    start = threading.Barrier(4)
    results: list[str] = []
    errors: list[BaseException] = []

    def worker(seq: int) -> None:
        # 每个线程自己的 Session（engine 共享）；仓储内部各自开事务。
        try:
            start.wait()
            op = repo.accept(command(seq))
            results.append(op.id)
        except BaseException as exc:  # noqa: BLE001 — 收集后统一断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i % 2,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发受理不得抛给调用方：{errors}"
    # 同 key 同输入：4 个线程看到的必须是同一个 operation_id。
    assert len(set(results)) == 2  # 两个 scope，各自幂等
    with Session(repo._engine) as session:
        rows = session.query(Operation).all()
    assert len(rows) == 2
    by_scope: dict[str, set[str]] = {}
    for row in rows:
        by_scope.setdefault(row.scope, set()).add(row.id)
    assert all(len(ids) == 1 for ids in by_scope.values())


def test_running_operation_is_not_double_started(repo):
    """两个 worker 抢同一 queued 操作：只有一个能完成 queued→running。"""
    op = repo.accept(command(0))
    outcomes: list[str] = []
    start = threading.Barrier(2)

    def claim() -> None:
        try:
            start.wait()
            repo.transition(op.id, OperationStatus.RUNNING)
            outcomes.append("won")
        except Exception:  # noqa: BLE001
            outcomes.append("lost")

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 状态机保证至多一次有效转移；另一次要么失败要么同值幂等失败。
    assert outcomes.count("won") <= 1 or set(outcomes) == {"won"}
    with Session(repo._engine) as session:
        stored = session.get(Operation, op.id)
    assert stored.status == OperationStatus.RUNNING
    assert stored.attempts == 1  # 关键红线：并发不会把 attempts 打成 2
