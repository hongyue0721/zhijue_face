"""业务 operation 执行：把"受理"与"真正干活"分开（api.md §1/§7）。

- API 层只创建 operation 行并返回 202 OperationAccepted；
- 本模块在 BackgroundTasks 里按状态机推进 running→succeeded/failed，
  逐条写持久化事件，失败必须发 `operation.failed` 且写 error 字段，
  不允许出现"202 之后无声失败"。
- 单进程单 worker（config/demo.yaml runtime.api_workers=1）：用进程内的排队
  锁保证同一时刻只有一个业务 operation 在跑，避免并发写同一 SQLite 资源。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import Operation, utc_now_rfc3339
from zhijue.adapters.db.operations import OperationRepository
from zhijue.api.errors import PUBLIC_MESSAGES
from zhijue.domain.errors import DocumentRejected, DomainError
from zhijue.domain.operations import OperationStatus

# 契约错误码的唯一来源是 api.md §2 的映射表（api/errors.py 已承载）。
CONTRACT_ERROR_CODES = frozenset(PUBLIC_MESSAGES)

logger = logging.getLogger("zhijue.operations")


@dataclass(frozen=True)
class OperationJob:
    operation_id: str
    kind: str
    resource_id: str
    run: Callable[[], Awaitable[dict[str, Any]]]


class OperationRunner:
    """有限队列 + 串行执行；队列满时由 API 层返回 429 CAPACITY_LIMITED。"""

    def __init__(
        self, *, engine: Engine, repo: OperationRepository, max_queued: int
    ) -> None:
        self._engine = engine
        self._repo = repo
        self._max_queued = max_queued
        self._lock = asyncio.Lock()
        self._pending = 0

    @property
    def pending(self) -> int:
        return self._pending

    @property
    def capacity_available(self) -> bool:
        return self._pending < self._max_queued

    async def submit(self, job: OperationJob) -> None:
        """后台任务入口：绝不向 ASGI 管道抛异常（响应已发出，抛出会污染连接）。

        业务失败走 _mark_failed 落库；连失败登记都失败时记 critical 日志，
        操作行保持非终态（如实表示"状态未知"），不伪造成功。
        """
        self._pending += 1
        try:
            # 串行：同一时刻只有一个业务 operation 推进（单机单 worker 语义）。
            async with self._lock:
                await self._execute(job)
        except Exception as exc:  # noqa: BLE001 - terminal bookkeeping boundary.
            logger.critical(
                "operation %s bookkeeping failed: %s",
                job.operation_id,
                type(exc).__name__,
            )
            try:
                self._mark_failed(job, RuntimeError("INTERNAL_ERROR"))
            except Exception as mark_exc:  # noqa: BLE001 - no exception may escape.
                logger.critical(
                    "operation %s could not record failure: %s",
                    job.operation_id,
                    type(mark_exc).__name__,
                )
        finally:
            self._pending -= 1

    async def _execute(self, job: OperationJob) -> None:
        self._mark_running(job)
        try:
            result = await job.run()
        except Exception as exc:  # noqa: BLE001 - 必须落 failed，不能静默
            logger.warning(
                "operation %s failed: %s", job.operation_id, type(exc).__name__
            )
            self._mark_failed(job, exc)
            return
        self._mark_succeeded(job, result)

    # ---- 状态推进（每次一个短事务，避免长事务占写锁） ----

    def _mark_running(self, job: OperationJob) -> None:
        self._repo.transition(job.operation_id, OperationStatus.RUNNING)
        self._repo.append_event(
            job.operation_id,
            "operation.started",
            {"kind": job.kind, "resource_id": job.resource_id},
        )

    def _mark_succeeded(self, job: OperationJob, result: dict[str, Any]) -> None:
        # 顺序不可颠倒：终态事件必须在状态转终态**之前**写入，
        # 因为 append_event 拒绝在终态后追加事件（事件流随操作关闭）。
        self._repo.append_event(
            job.operation_id,
            "operation.completed",
            {
                "resource_id": job.resource_id,
                "resource_revision": int(result.get("resource_revision", 0)),
            },
        )
        with Session(self._engine) as session, session.begin():
            operation = session.get(Operation, job.operation_id)
            operation.result = result
            operation.updated_at = utc_now_rfc3339()
        self._repo.transition(job.operation_id, OperationStatus.SUCCEEDED)

    def _mark_failed(self, job: OperationJob, exc: Exception) -> None:
        code = _error_code(exc)
        # 领域异常的 message 是代码内受控、可行动文案（模型内容在应用端口已被
        # 替换为固定错误）；有则优先于错误码的通用文案，让页面能显示真实原因。
        message = (
            exc.message
            if isinstance(exc, DomainError) and exc.message
            else PUBLIC_MESSAGES.get(code, "操作失败。")
        )
        declared_retryable = getattr(exc, "retryable", None)
        retryable = (
            bool(declared_retryable)
            if declared_retryable is not None
            else code
            in {
                "UPSTREAM_FAILED",
                "UPSTREAM_TIMEOUT",
                "SERVICE_NOT_READY",
                "CAPACITY_LIMITED",
                "INTERNAL_ERROR",
            }
        )
        if job.kind == "document.import":
            # Upload bytes live only in the accepted request's memory. Retrying
            # this operation would have no original file to replay.
            retryable = False
            if isinstance(exc, DocumentRejected):
                code = exc.code
            message = f"{message} 请重新选择并上传文件。"
        self._repo.append_event(
            job.operation_id,
            "operation.failed",
            {"code": code, "message": message, "retryable": retryable},
        )
        with Session(self._engine) as session, session.begin():
            operation = session.get(Operation, job.operation_id)
            operation.error = {
                "code": code,
                "message": message,
                "retryable": retryable,
            }
            operation.updated_at = utc_now_rfc3339()
        self._repo.transition(job.operation_id, OperationStatus.FAILED)


def _error_code(exc: Exception) -> str:
    """异常 → 契约错误码。

    优先取领域异常自带的 code（`JDPlanningError`/`JdRejected` 等显式声明），
    否则从消息前缀匹配；都不匹配才是 INTERNAL_ERROR——不把业务错误降级成内部错误。
    """
    explicit = getattr(exc, "code", None)
    if isinstance(explicit, str) and explicit in CONTRACT_ERROR_CODES:
        return explicit
    text = str(exc)
    for candidate in sorted(CONTRACT_ERROR_CODES, key=len, reverse=True):
        if text.startswith(f"{candidate}:") or f"{candidate}:" in text:
            return candidate
    return "INTERNAL_ERROR"
