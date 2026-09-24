"""R4 evaluator 包：确定性检测器 + 未来 LLM judge 的接口占位。

本轮零外部模型调用、零网络：`interfaces` 里的 `Fixture*` 只为离线打通代码路径。
"""

from __future__ import annotations

from .deterministic import evaluate_text
from .findings import Finding
from .interfaces import AtomicClaimExtractor, ClaimEvidenceJudge, UtilityJudge

#: 写入 config/trace 的 evaluator 版本；检测器口径变更必须升版本，禁止原地改语义。
EVALUATOR_VERSION = "eval_cef-1.0.0"

__all__ = [
    "EVALUATOR_VERSION",
    "AtomicClaimExtractor",
    "ClaimEvidenceJudge",
    "Finding",
    "UtilityJudge",
    "evaluate_text",
]
