"""纯提取契约与文档状态规则（domain 层，无第三方依赖）。

`extract_status` 决策在这里成为可单测的纯函数：
- 所有页无文字 → requires_text（绝不记成"解析成功零项"的假成功）；
- 部分页无文字 → parsed + 缺页警告（T03）；
- 有任一非空 → parsed；
- 文字层里无法识别的字符统一标成 U+FFFD 并给出警告，交给用户在核对时更正。

ExtractionLimits 的规范值来自 config/demo.yaml；application 层注入，
domain 只声明形状，不读配置文件。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# PDF 字体没有提供文字映射时，提取器会吐出 NUL 等控制字符（例如上标「²」）。
# 它们不是简历内容，也不能猜成某个字；统一换成 Unicode 替换字符，让缺失可见。
UNREADABLE_CHARACTER = "\ufffd"
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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
    # P-EXTRACT 单次模型调用的源文字预算：长文档按连续段分块多次抽取，
    # 控制每次生成时长，避免整份文档一次性生成突破传输总超时。
    max_chars_per_extract_call: int = 1_600


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


def mark_unreadable_characters(
    pages: list[PageText],
) -> tuple[list[PageText], list[str]]:
    """把无法识别的字符标成「\ufffd」，并按页返回警告。

    不删除也不猜测缺失字符：删掉会把「I²C」拼成「IC」，猜测则是在替用户编造事实。
    标记后的文本就是来源块正文，候选经历逐字引用它，用户在核对时更正。
    """
    marked: list[PageText] = []
    warnings: list[str] = []
    for page in pages:
        text = _CONTROL_CHARACTERS.sub(UNREADABLE_CHARACTER, page.text)
        marked.append(replace(page, text=text))
        count = text.count(UNREADABLE_CHARACTER)
        if count:
            where = (
                "文本里" if page.page_number is None else f"第 {page.page_number} 页"
            )
            warnings.append(
                f"{where}有 {count} 个字符无法识别，已用「{UNREADABLE_CHARACTER}」标出；"
                "核对经历时请更正这些位置。"
            )
    return marked, warnings
