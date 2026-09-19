"""pypdf 适配：魔数识别、按页提取、资源限制。

只把 bytes 变成 PageText 序列或抛受控 DocumentRejected（docs/09 §7：
按内容不信任文件名；限制页数/字符）。加密 PDF 不向用户索取密码
（api.md §4），直接给粘贴文本指引。
"""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from zhijue.domain.errors import DocumentRejected
from zhijue.domain.extraction import ExtractionLimits, PageText

PDF_MAGIC = b"%PDF-"
TEXT_MAX_SNIFF_BYTES = 4096


def sniff_kind(data: bytes) -> str:
    """返回 'pdf' 或 'text'；其他为 UNSUPPORTED_FILE_TYPE（按内容而非文件名）。"""
    if data.startswith(PDF_MAGIC):
        return "pdf"
    sample = data[:TEXT_MAX_SNIFF_BYTES]
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        raise DocumentRejected(
            "UNSUPPORTED_FILE_TYPE", "文件类型不受支持；当前仅接受 PDF 与 UTF-8 文本。"
        ) from None
    return "text"


def extract_pdf_pages(data: bytes, *, limits: ExtractionLimits) -> list[PageText]:
    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise DocumentRejected(
            "DOCUMENT_UNREADABLE",
            f"PDF 无法解析：{type(exc).__name__}。",
            retry_hint="check_file",
        ) from exc
    if reader.is_encrypted:
        # 不尝试任何口令，也不要求用户提供口令；这是业务边界，不是解析技巧。
        raise DocumentRejected(
            "DOCUMENT_ENCRYPTED",
            "PDF 已加密，当前版本不处理加密文件；请粘贴简历文本内容继续。",
            retry_hint="paste_text",
        )
    if len(reader.pages) > limits.max_pages:
        raise DocumentRejected(
            "TOO_MANY_PAGES",
            f"文档共 {len(reader.pages)} 页，超过每次上限 {limits.max_pages} 页。",
            retry_hint="split_document",
        )
    total = 0
    pages: list[PageText] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — 单页解码失败按"缺文字层"处理并保留页结构，
            text = ""  # 由 decide_status 转成警告，绝不静默删页或整体假成功
        total += len(text)
        if total > limits.max_chars:
            raise DocumentRejected(
                "TEXT_TOO_LARGE",
                f"提取文本超过 {limits.max_chars} 字符上限。",
                retry_hint="reduce_document",
            )
        pages.append(PageText(page_number=number, text=text))
    return pages


def extract_text_pages(data: bytes, *, limits: ExtractionLimits) -> list[PageText]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentRejected(
            "UNSUPPORTED_FILE_TYPE", "文本文件不是有效 UTF-8。"
        ) from exc
    if len(text) > limits.max_chars:
        raise DocumentRejected(
            "TEXT_TOO_LARGE",
            f"文本超过 {limits.max_chars} 字符上限。",
            retry_hint="reduce_document",
        )
    return [PageText(page_number=None, text=text)]
