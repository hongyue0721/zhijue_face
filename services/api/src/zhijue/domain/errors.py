"""领域错误类型：API 层据此映射统一 code（docs/09 §4）。

优先使用类型化异常（typed exception）与显式错误码（explicit error code），
字符串前缀匹配仅保留为底层第三方异常的兼容兜底。
错误必须携带机器可读 code 和可读 message；失败绝不伪装成空成功。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DomainError(Exception):
    """领域异常基类：携带机器可读 error_code、HTTP status_code 和面向调用者的提示。"""

    def __init__(
        self,
        message: str = "",
        *,
        code: str = "INVALID_REQUEST",
        status_code: int = 400,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ResourceNotFoundError(DomainError):
    """资源不存在。"""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message, code="RESOURCE_NOT_FOUND", status_code=404, details=details
        )


class InvalidStateError(DomainError):
    """状态机或业务状态冲突。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID_STATE",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=409, details=details)


class RevisionConflictError(DomainError):
    """乐观锁版本冲突。"""

    def __init__(self, message: str, *, current_revision: int | None = None) -> None:
        details = (
            {"current_revision": current_revision}
            if current_revision is not None
            else {}
        )
        super().__init__(
            message, code="REVISION_CONFLICT", status_code=409, details=details
        )


@dataclass
class DocumentRejected(DomainError):
    """文档校验失败或不支持。保持 dataclass 结构以兼容字段检测。"""

    code: str
    message: str
    retry_hint: str | None = field(default=None)
    status_code: int = field(default=422, kw_only=True)
    details: dict[str, Any] = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        sc = self.status_code
        if self.code in ("FILE_TOO_LARGE", "TEXT_TOO_LARGE"):
            sc = 413
        elif self.code == "UNSUPPORTED_FILE_TYPE":
            sc = 415
        elif self.code == "RESOURCE_NOT_FOUND":
            sc = 404
        d = dict(self.details)
        if self.retry_hint:
            d["retry_hint"] = self.retry_hint
        self.status_code = sc
        self.details = d
        super().__init__(self.message, code=self.code, status_code=sc, details=d)


class JdRejected(DomainError):
    """JD 不可用：空、超长、或缺少必要来源信息。"""

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if status_code is None:
            if code == "TEXT_TOO_LARGE":
                status_code = 413
            elif code in ("INVALID_REQUEST", "RESOURCE_NOT_FOUND"):
                status_code = 400 if code == "INVALID_REQUEST" else 404
            else:
                status_code = 422
        super().__init__(message, code=code, status_code=status_code, details=details)


class PlanningRejected(DomainError):
    """计划不可生成：JD 没有可用要求、或无法满足覆盖约束。"""

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code == "INVALID_REQUEST":
            status_code = 400
        super().__init__(message, code=code, status_code=status_code, details=details)


class CapacityLimitedError(DomainError):
    """队列或处理容量达到上限。"""

    def __init__(self, message: str = "系统处理队列已满，请稍后重试。") -> None:
        super().__init__(
            message, code="CAPACITY_LIMITED", status_code=429, retryable=True
        )


class ServiceUnavailableError(DomainError):
    """依赖的基础服务未就绪。"""

    def __init__(self, message: str = "服务未就绪，请稍后重试。") -> None:
        super().__init__(
            message, code="SERVICE_NOT_READY", status_code=503, retryable=True
        )


class UpstreamError(DomainError):
    """上游服务异常或超时。"""

    def __init__(
        self, message: str, *, timeout: bool = False, retryable: bool = True
    ) -> None:
        code = "UPSTREAM_TIMEOUT" if timeout else "UPSTREAM_FAILED"
        status_code = 504 if timeout else 502
        super().__init__(
            message,
            code=code,
            status_code=status_code,
            retryable=retryable,
        )
