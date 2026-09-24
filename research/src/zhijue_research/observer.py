"""研究侧观察者：把 R1 只读事件流转成 trace 需要的事实。

它只搬运事实，不做判定：raw 文本、usage、finish_reason、校验分类。
内部异常自己计数（trace 的 `observer_failures`），业务侧 `_notify` 另有吞异常兜底。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zhijue_research.io_utils import sha256_text


@dataclass(slots=True)
class ObservedGeneration:
    """一个 cell 的观测结果。缺失字段保持 None，不猜。"""

    input_hash: str | None = None
    raw_content: str | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    validation_status: str | None = None  # passed | failed
    validation_reasons: tuple[str, ...] = ()
    normalized_candidate: dict[str, Any] | None = None
    observer_failures: int = 0

    @property
    def evidence_input_hash(self) -> str | None:
        return self.input_hash


@dataclass(slots=True)
class RecordingObserver:
    """实现业务 `ContentWorkflowObserver` 协议（四个 on_* 方法）。"""

    observed: ObservedGeneration = field(default_factory=ObservedGeneration)
    events: tuple[str, ...] = ()

    def on_generation_input(self, event) -> None:
        self._safe(
            "on_generation_input",
            lambda: setattr(
                self.observed,
                "input_hash",
                sha256_text(_stable(event.task, event.payload)),
            ),
        )

    def on_raw_generation(self, event) -> None:
        self._safe(
            "on_raw_generation",
            lambda: (
                setattr(self.observed, "raw_content", event.content),
                setattr(self.observed, "usage", dict(event.usage)),
                setattr(self.observed, "finish_reason", event.finish_reason),
            ),
        )

    def on_validation_success(self, event) -> None:
        self._safe(
            "on_validation_success",
            lambda: (
                setattr(self.observed, "validation_status", "passed"),
                setattr(self.observed, "normalized_candidate", dict(event.candidate)),
            ),
        )

    def on_validation_failure(self, event) -> None:
        self._safe(
            "on_validation_failure",
            lambda: (
                setattr(self.observed, "validation_status", "failed"),
                setattr(
                    self.observed,
                    "validation_reasons",
                    (*self.observed.validation_reasons, event.reason_code),
                ),
                # 生产只留固定消息；研究必须留下折叠前的分类与原文。
                setattr(self.observed, "raw_content", event.content),
            ),
        )

    def _safe(self, hook: str, action) -> None:
        try:
            action()
            self.events = (*self.events, hook)
        except Exception:  # noqa: BLE001 - 记录失败不能污染实验本身
            self.observed.observer_failures += 1


def _stable(task: str, payload: Any) -> str:
    """payload 是只读 MappingProxyType，必须先转回普通 dict 才能序列化。"""

    import json

    return json.dumps(
        {"task": task, "payload": {key: value for key, value in payload.items()}},
        ensure_ascii=False,
        sort_keys=True,
    )
