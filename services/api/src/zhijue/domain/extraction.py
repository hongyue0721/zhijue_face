"""纯提取契约与文档状态规则（domain 层，无第三方依赖）。

`extract_status` 决策在这里成为可单测的纯函数：
- 所有页无文字 → requires_text（绝不记成"解析成功零项"的假成功）；
- 部分页无文字 → parsed + 缺页警告（T03）；
- 有任一非空 → parsed。

ExtractionLimits 的规范值来自 config/demo.yaml；application 层注入，
domain 只声明形状，不读配置文件。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    page_number: int | None  # PDF 从 1 起；纯文本无页概念（docs/03 §3）
    text: str


@dataclass(frozen=True)
class ExtractionLimits:
    max_bytes: int = 10 * 1024 * 1024  # 10 MiB
    max_pages: int = 5
    max_chars: int = 30_000
    max_documents: int = 5


def decide_status(pages: list[PageText]) -> tuple[str, list[str]]:
    """返回 (extract_status, warnings)。空页保留在 pages 里，不静默删除。"""
    if not pages:
        return "requires_text", ["文档没有可解析的页面。"]
    empty = [p.page_number for p in pages if not p.text.strip()]
    if len(empty) == len(pages):
        return (
            "requires_text",
            ["这份文件没有可用文字层，疑似扫描件。当前版本可粘贴简历文字继续。"],
        )
    if empty:
        pages_label = "、".join(str(n) for n in empty)
        return "parsed", [
            f"第 {pages_label} 页没有可用文字层；已保留其余页面，缺页可稍后粘贴文本。"
        ]
    return "parsed", []
