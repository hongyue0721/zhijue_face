"""HTTP 层：契约错误映射与请求上下文。

api.md §1/§2 是唯一真源：成功响应统一 `{"data":..., "meta":{"request_id":...}}`，
错误统一 `{"error":{code,message,retryable,details}}`，字段一律 snake_case。
domain/application 抛出的语义异常在这里翻译成 HTTP，不在业务层写状态码。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from zhijue.adapters.db.operations import IdempotencyConflict
from zhijue.adapters.db.profiles import RevisionConflict
from zhijue.domain.errors import DomainError


class ApiError(Exception):
    """带契约错误码的 HTTP 语义错误；details 不含私人原文。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True)
class ErrorSpec:
    status_code: int
    code: str
    retryable: bool = False


# 业务异常前缀 → 契约错误（api.md §2）。前缀由各层用稳定字符串标记，
# 避免 HTTP 层去猜异常类型，也避免把内部异常文本直接透出。
_PREFIX_MAP: tuple[tuple[str, ErrorSpec], ...] = (
    ("RESOURCE_NOT_FOUND", ErrorSpec(404, "RESOURCE_NOT_FOUND")),
    ("PROFILE_NOT_ACTIVE", ErrorSpec(409, "INVALID_STATE")),
    ("CLAIM_NOT_FOUND", ErrorSpec(404, "RESOURCE_NOT_FOUND")),
    ("CLAIM_RETRACTED", ErrorSpec(409, "INVALID_STATE")),
    ("REVISION_CONFLICT", ErrorSpec(409, "REVISION_CONFLICT")),
    ("FILE_TOO_LARGE", ErrorSpec(413, "FILE_TOO_LARGE")),
    ("TEXT_TOO_LARGE", ErrorSpec(413, "TEXT_TOO_LARGE")),
    ("UNSUPPORTED_FILE_TYPE", ErrorSpec(415, "UNSUPPORTED_FILE_TYPE")),
    ("UPSTREAM_TIMEOUT", ErrorSpec(504, "UPSTREAM_TIMEOUT", retryable=True)),
    ("UPSTREAM_FAILED", ErrorSpec(502, "UPSTREAM_FAILED", retryable=True)),
    ("SERVICE_NOT_READY", ErrorSpec(503, "SERVICE_NOT_READY", retryable=True)),
)


# 契约错误码 → 面向用户的消息（api.md §2）。固定文案避免把内部 ID、
# revision 数值或路径透出；细节只在 details 里按契约给（如 current_revision）。
PUBLIC_MESSAGES: dict[str, str] = {
    "RESOURCE_NOT_FOUND": "资源不存在或不可见。",
    "REVISION_CONFLICT": "资料已更新，请重新加载后重试。",
    "IDEMPOTENCY_CONFLICT": "相同幂等键被用于不同输入。",
    "INVALID_STATE": "当前状态不允许该操作。",
    "OPERATION_IN_PROGRESS": "当前资源已有进行中的操作。",
    "REPORT_NOT_READY": "报告尚未生成。",
    "INVALID_REQUEST": "请求格式或参数无效。",
    "SCHEMA_VALIDATION_FAILED": "请求字段不符合契约。",
    "FILE_TOO_LARGE": "文件超过大小上限。",
    "TEXT_TOO_LARGE": "文本超过长度上限。",
    "UNSUPPORTED_FILE_TYPE": "文件类型不支持。",
    "CAPACITY_LIMITED": "操作队列已满，请稍后重试。",
    "SERVICE_NOT_READY": "依赖未就绪。",
    "UPSTREAM_FAILED": "上游依赖调用失败。",
    "UPSTREAM_TIMEOUT": "上游依赖超时。",
    "EVENT_HISTORY_GONE": "事件历史已不可用，请重新获取快照。",
    "INTERNAL_ERROR": "服务内部错误。",
}


def spec_for(exc_or_msg: Any) -> ErrorSpec:
    if isinstance(exc_or_msg, DomainError):
        return ErrorSpec(
            status_code=exc_or_msg.status_code,
            code=exc_or_msg.code,
            retryable=exc_or_msg.retryable,
        )
    explicit = getattr(exc_or_msg, "code", None)
    if isinstance(explicit, str):
        status_code = getattr(exc_or_msg, "status_code", 422)
        retryable = getattr(exc_or_msg, "retryable", False)
        return ErrorSpec(status_code=status_code, code=explicit, retryable=retryable)
    message = str(exc_or_msg)
    for prefix, spec in _PREFIX_MAP:
        if message.startswith(f"{prefix}:") or f"{prefix}:" in message:
            return spec
    return ErrorSpec(422, "SCHEMA_VALIDATION_FAILED")


@dataclass
class RequestContext:
    """请求级上下文：request_id 只用于关联日志，不进入业务状态。"""

    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:16]}")


def envelope(data: Any, request_id: str) -> dict[str, Any]:
    return {"data": data, "meta": {"request_id": request_id}}


def error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
            },
            "meta": {"request_id": request_id},
        },
    )


def install_error_handlers(app) -> None:
    """统一异常出口：业务语义异常映射契约错误，其余一律 500 且不泄漏内部细节。"""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        ctx = getattr(request.state, "context", None) or RequestContext()
        return error_response(
            request_id=ctx.request_id,
            status_code=exc.status_code,
            code=exc.code,
            message=PUBLIC_MESSAGES.get(exc.code, exc.message),
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        ctx = getattr(request.state, "context", None) or RequestContext()
        return error_response(
            request_id=ctx.request_id,
            status_code=exc.status_code,
            code=exc.code,
            message=PUBLIC_MESSAGES.get(exc.code, exc.message),
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """合法 JSON 但字段/枚举不符契约 → 422 SCHEMA_VALIDATION_FAILED（api.md §2）。"""
        ctx = getattr(request.state, "context", None) or RequestContext()
        fields = sorted(
            {
                ".".join(str(part) for part in error["loc"][1:])
                for error in exc.errors()
                if error.get("loc")
            }
        )
        return error_response(
            request_id=ctx.request_id,
            status_code=422,
            code="SCHEMA_VALIDATION_FAILED",
            message=PUBLIC_MESSAGES["SCHEMA_VALIDATION_FAILED"],
            details={"fields": fields},
        )

    @app.exception_handler(RevisionConflict)
    async def _revision_conflict(
        request: Request, exc: RevisionConflict
    ) -> JSONResponse:
        ctx = getattr(request.state, "context", None) or RequestContext()
        current = _current_revision_from_message(str(exc))
        return error_response(
            request_id=ctx.request_id,
            status_code=409,
            code="REVISION_CONFLICT",
            message=PUBLIC_MESSAGES["REVISION_CONFLICT"],
            details={"current_revision": current} if current is not None else {},
        )

    @app.exception_handler(IdempotencyConflict)
    async def _idempotency_conflict(
        request: Request, exc: IdempotencyConflict
    ) -> JSONResponse:
        ctx = getattr(request.state, "context", None) or RequestContext()
        return error_response(
            request_id=ctx.request_id,
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message=PUBLIC_MESSAGES["IDEMPOTENCY_CONFLICT"],
        )

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        ctx = getattr(request.state, "context", None) or RequestContext()
        spec = spec_for(str(exc))
        return error_response(
            request_id=ctx.request_id,
            status_code=spec.status_code,
            code=spec.code,
            message=PUBLIC_MESSAGES.get(spec.code, "请求未被接受。"),
            retryable=spec.retryable,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        ctx = getattr(request.state, "context", None) or RequestContext()
        return error_response(
            request_id=ctx.request_id,
            status_code=500,
            code="INTERNAL_ERROR",
            message=PUBLIC_MESSAGES["INTERNAL_ERROR"],
        )


def _public_message(message: str) -> str:
    """去掉内部前缀，避免把 `REVISION_CONFLICT: 服务端 revision=3` 这类文本直接透出。"""
    if ": " in message:
        head, tail = message.split(": ", 1)
        if head.isupper() or "_" in head:
            return tail
    return message


def _current_revision_from_message(message: str) -> int | None:
    import re

    match = re.search(r"revision=(\d+)", message)
    return int(match.group(1)) if match else None
