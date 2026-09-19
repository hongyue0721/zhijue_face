"""SSE 事件流（api.md §8）：持久化事件重放 → live 接续 → 终态收敛。

范围说明：本轮实现/confirm 受理后客户端真正需要的最小可用流（重放、
去重序号、心跳、终态关闭）。M3-02 仍负责面试答题链路的断流恢复、
`EVENT_HISTORY_GONE` 保留策略与反向代理缓冲验证。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from zhijue.api.errors import ApiError
from zhijue.domain.operations import OperationStatus

router = APIRouter(prefix="/api/v1")

HEARTBEAT_SECONDS = 15
POLL_SECONDS = 0.2
TERMINAL = {status.value for status in OperationStatus} - {"queued", "running"}


@router.get("/operations/{operation_id}/events")
def stream_operation_events(
    operation_id: str,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    services = request.app.state.services
    operation = services.operations.get(operation_id)
    if operation is None:
        raise ApiError(
            status_code=404, code="RESOURCE_NOT_FOUND", message="操作不存在。"
        )

    # after 与 Last-Event-ID 同时给出且不同 → 400（api.md §8）。
    if after is not None and last_event_id is not None and str(after) != last_event_id:
        raise ApiError(
            status_code=400,
            code="INVALID_EVENT_CURSOR",
            message="after 与 Last-Event-ID 不一致。",
        )
    cursor = after
    if cursor is None and last_event_id is not None:
        try:
            cursor = int(last_event_id)
        except ValueError as exc:
            raise ApiError(
                status_code=400, code="INVALID_EVENT_CURSOR", message="事件游标无效。"
            ) from exc
    start = cursor or 0

    async def event_source() -> AsyncIterator[str]:
        last = start
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return
            events = services.operations.events_after(operation_id, last)
            for event in events:
                last = event.seq
                payload = {
                    "schema_version": "1.0.0",
                    "operation_id": operation_id,
                    "seq": event.seq,
                    "payload": event.payload,
                }
                yield (
                    f"id: {event.seq}\n"
                    f"event: {event.event_type}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
                idle = 0.0
            current = services.operations.get(operation_id)
            if events and current is not None and current.status in TERMINAL:
                return  # 终态事件已发；不把连接关闭当作成功（api.md §8）
            if current is None:
                return
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS
            if idle >= HEARTBEAT_SECONDS:
                idle = 0.0
                yield ": ping\n\n"  # 心跳不占 seq、不持久化

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
