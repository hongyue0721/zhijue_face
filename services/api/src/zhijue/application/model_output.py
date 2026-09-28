"""Shared handling of OpenAI-compatible model output formatting quirks."""

from __future__ import annotations

import re

# 整体包裹的 Markdown 代码栅栏（```json ... ``` 等）。
_FENCE_RE = re.compile(
    r"^```[ \t]*[A-Za-z0-9_-]*[ \t]*\n(?P<body>.*?\n)[ \t]*```[ \t]*$",
    re.DOTALL,
)


def unwrap_code_fence(content: str) -> str:
    """剥离整体包裹的 Markdown 代码栅栏。

    部分 OpenAI 兼容模型（实测 qwen3.8-flash）即使 `response_format=json_object`
    仍会把整个 JSON 包进 ``` 栅栏。这只影响外层包装：解出的正文仍必须通过完整
    schema/引用/ID 严格校验，不放宽任何业务契约；栅栏内不是合法 JSON 对象时
    与未剥离时一样失败。
    """
    text = content.strip()
    match = _FENCE_RE.match(text)
    return match.group("body").strip() if match else text
