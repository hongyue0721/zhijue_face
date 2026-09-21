"""Operation 与 OperationEvent 仓储：幂等受理、只追加事件、状态机推进。

业务规则（api.md §1/§7，docs/04 §3）：
- 先按 (scope, idempotency_key) 检索既有操作，命中且 input_hash 相同 → 返回原操作
  （重放不推进状态、不重复调上游）；命中但 input_hash 不同 → IdempotencyConflict。
- 事件 seq 在 operation 内单调，(operation_id, seq) 唯一；终态后禁止再追加。
- retry 不复活终态行：创建新 operation，parent_operation_id 指向原操作，输入哈希继承。
- 事件 payload 必须符合 contracts/operation-event.schema.json 的对应分支。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import Operation, OperationEvent, utc_now_rfc3339
from zhijue.domain.errors import CapacityLimitedError
from zhijue.domain.ids import new_id
from zhijue.domain.operations import (
    TERMINAL_STATUSES,
    OperationStatus,
    canonical_input_hash,
    ensure_transition,
)

SCHEMA_VERSION = "1.0.0"


class IdempotencyConflict(Exception):
    """同 key 不同规范化输入；不得绕过授权或静默覆盖。"""


@dataclass(frozen=True)
class OperationCommand:
    kind: str
    resource_type: str
    resource_id: str
    scope: str
    idempotency_key: str
    input: Any


def canon_scope(workspace_id: str, method: str, path: str) -> str:
    return f"{workspace_id}|{method.upper()}|{path}"


def _load_event_validator() -> Draft202012Validator:
    import json
    from pathlib import Path

    # 向上定位仓库根的 contracts/，不依赖目录深度常数。
    here = Path(__file__).resolve()
    schema_path = next(
        (candidate / "contracts" / "operation-event.schema.json")
        for candidate in here.parents
        if (candidate / "contracts" / "operation-event.schema.json").is_file()
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


class OperationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._event_validator = _load_event_validator()
        self._acceptance_lock = Lock()

    # ---- 受理与查询 -------------------------------------------------------

    def accept(self, command: OperationCommand) -> Operation:
        input_hash = canonical_input_hash(command.input)
        try:
            with (
                Session(self._engine, expire_on_commit=False) as session,
                session.begin(),
            ):
                return self._accept_in_session(session, command, input_hash)
        except IntegrityError as exc:
            # 先查后插的竞争窗口：两个事务都未见彼此，输家在 INSERT 撞
            # (scope,idempotency_key) 唯一键。约束只对已提交行报错，因此赢家
            # 此刻必然已提交；新事务重查并返回原操作（api.md §1：同 key 同
            # 输入返回原操作）。查不到即非幂等竞争，原样抛出不吞错。
            with Session(self._engine, expire_on_commit=False) as session:
                winner = session.scalar(
                    select(Operation).where(
                        Operation.scope == command.scope,
                        Operation.idempotency_key == command.idempotency_key,
                    )
                )
            if winner is None:
                raise
            if winner.input_hash != input_hash:
                raise IdempotencyConflict(command.idempotency_key) from exc
            return winner

    def accept_queued(
        self, command: OperationCommand, *, capacity_available: bool
    ) -> tuple[Operation, bool]:
        """Replay first; reject capacity before committing any new queued row."""
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing = session.scalar(
                select(Operation).where(
                    Operation.scope == command.scope,
                    Operation.idempotency_key == command.idempotency_key,
                )
            )
            if existing is not None:
                return self.accept_in_session(session, command), False
            if not capacity_available:
                raise CapacityLimitedError()
            return self.accept_in_session(session, command), True

    @staticmethod
    def _accept_in_session(
        session: Session, command: OperationCommand, input_hash: str
    ) -> Operation:
        existing = session.scalar(
            select(Operation).where(
                Operation.scope == command.scope,
                Operation.idempotency_key == command.idempotency_key,
            )
        )
        if existing is not None:
            if existing.input_hash != input_hash:
                raise IdempotencyConflict(command.idempotency_key)
            return existing
        operation = Operation(
            id=new_id("operation"),
            kind=command.kind,
            resource_type=command.resource_type,
            resource_id=command.resource_id,
            scope=command.scope,
            idempotency_key=command.idempotency_key,
            input_hash=input_hash,
            status=OperationStatus.QUEUED,
        )
        session.add(operation)
        session.flush()
        session.refresh(operation)
        return operation

    def accept_in_session(
        self, session: Session, command: OperationCommand
    ) -> Operation:
        """在调用方业务事务中原子受理 operation。

        Answer/Interview 等业务写必须与 operation 同成同败；调用方负责
        `session.begin()` 和 IntegrityError 竞争重试，不能在此提交事务。
        """
        return self._accept_in_session(
            session, command, canonical_input_hash(command.input)
        )

    def get(self, operation_id: str) -> Operation | None:
        with Session(self._engine, expire_on_commit=False) as session:
            return session.get(Operation, operation_id)

    def retry(
        self,
        operation_id: str,
        *,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        request_input: Any | None = None,
    ) -> Operation:
        """仅 failed/interrupted 可重试；新 ID + parent 链接，累计预算不重置。"""
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            original = session.get(Operation, operation_id)
            if original is None:
                raise KeyError(operation_id)
            return self.retry_in_session(
                session,
                original,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                request_input=request_input,
            )

    @staticmethod
    def retry_in_session(
        session: Session,
        original: Operation,
        *,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        request_input: Any | None = None,
    ) -> Operation:
        if original.status not in (
            OperationStatus.FAILED,
            OperationStatus.INTERRUPTED,
        ):
            raise ValueError(f"retry not allowed from {original.status}")
        if original.attempts >= max_attempts:
            raise ValueError("retry budget exhausted")
        retry_scope = f"{original.scope}#retry_of_{original.id}"
        retry_key = idempotency_key or original.idempotency_key
        retry_input_hash = (
            original.input_hash
            if request_input is None
            else canonical_input_hash(request_input)
        )
        existing = session.scalar(
            select(Operation).where(
                Operation.scope == retry_scope,
                Operation.idempotency_key == retry_key,
            )
        )
        if existing is not None:
            if existing.input_hash != retry_input_hash:
                raise IdempotencyConflict(retry_key)
            return existing
        clone = Operation(
            id=new_id("operation"),
            kind=original.kind,
            resource_type=original.resource_type,
            resource_id=original.resource_id,
            scope=retry_scope,
            idempotency_key=retry_key,
            input_hash=retry_input_hash,
            parent_operation_id=original.id,
            status=OperationStatus.QUEUED,
            attempts=original.attempts,
        )
        session.add(clone)
        session.flush()
        session.refresh(clone)
        return clone

    # ---- 状态与事件 -------------------------------------------------------

    def transition(self, operation_id: str, target: OperationStatus) -> Operation:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise KeyError(operation_id)
            current = OperationStatus(operation.status)
            ensure_transition(current, OperationStatus(target))
            operation.status = OperationStatus(target)
            operation.updated_at = utc_now_rfc3339()
            if target == OperationStatus.RUNNING:
                operation.attempts += 1
            session.flush()
            session.refresh(operation)
            return operation

    def append_event(
        self, operation_id: str, event_type: str, payload: dict[str, Any]
    ) -> int:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            return self.append_event_in_session(
                session, operation_id, event_type, payload
            )

    def append_event_in_session(
        self,
        session: Session,
        operation_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """把业务状态与可恢复事件放进调用方的同一事务。"""
        document = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id,
            "seq": 1,
            "event_type": event_type,
            "payload": payload,
        }
        errors = sorted(self._event_validator.iter_errors(document), key=str)
        if errors:
            raise ValueError(f"event payload violates contract: {errors[0].message}")
        operation = session.get(Operation, operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status in TERMINAL_STATUSES:
            raise ValueError(
                f"operation {operation_id} is {operation.status}; events closed"
            )
        seq = operation.last_event_seq + 1
        session.add(
            OperationEvent(
                operation_id=operation_id,
                seq=seq,
                event_type=event_type,
                payload=payload,
            )
        )
        operation.last_event_seq = seq
        operation.updated_at = utc_now_rfc3339()
        return seq

    def _insert_raw_event(
        self, operation_id: str, seq: int, event_type: str, payload: dict[str, Any]
    ) -> None:
        """测试钩子：绕过仓储单调逻辑直接写，验证 DB 唯一约束兜底。"""
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            session.add(
                OperationEvent(
                    operation_id=operation_id,
                    seq=seq,
                    event_type=event_type,
                    payload=payload,
                )
            )

    def events_after(self, operation_id: str, after: int) -> list[OperationEvent]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = session.scalars(
                select(OperationEvent)
                .where(
                    OperationEvent.operation_id == operation_id,
                    OperationEvent.seq > after,
                )
                .order_by(OperationEvent.seq)
            )
            return list(rows)

    # ---- 进程重启恢复（docs/02 §7、docs/04 §3） ---------------------------

    def mark_interrupted_on_restart(self) -> list[str]:
        """Terminate persisted queued/running work because its in-memory job was lost."""
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            operations = list(
                session.scalars(
                    select(Operation).where(
                        Operation.status.in_(
                            (OperationStatus.QUEUED, OperationStatus.RUNNING)
                        )
                    )
                )
            )
            for operation in operations:
                payload = {
                    "code": "PROCESS_RESTARTED",
                    "message": (
                        "服务进程重启，上传已中断；请重新选择并上传文件。"
                        if operation.kind == "document.import"
                        else "服务进程重启，操作已中断；已保存的业务输入可显式重试。"
                    ),
                    "retryable": operation.kind != "document.import",
                }
                self.append_event_in_session(
                    session, operation.id, "operation.interrupted", payload
                )
                operation.status = OperationStatus.INTERRUPTED
                operation.error = payload
                operation.updated_at = utc_now_rfc3339()
            return [operation.id for operation in operations]

    def requeue_pending(self) -> list[str]:
        with Session(self._engine, expire_on_commit=False) as session:
            return list(
                session.scalars(
                    select(Operation.id).where(
                        Operation.status == OperationStatus.QUEUED
                    )
                )
            )
