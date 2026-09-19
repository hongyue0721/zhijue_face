"""不透明带前缀 ID（docs/03 §2）。

ID 由服务端生成，客户端不得从字面猜含义；这里只保证唯一性与前缀可读，
不编码业务事实（时间戳故意不进 ID，避免泄漏与时钟耦合）。
"""

from __future__ import annotations

import secrets

_ID_BYTES = 10  # 20 个 hex 字符；冲突概率对单机 Demo 可忽略，唯一性最终由 DB 约束兜底


def new_id(prefix: str) -> str:
    if not prefix or not prefix.replace("_", "").isalnum():
        raise ValueError(f"invalid id prefix: {prefix!r}")
    return f"{prefix}_{secrets.token_hex(_ID_BYTES)}"
