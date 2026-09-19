"""DocumentService：校验 → 提取 → 状态决策 → 单事务落库（docs/02 §4）。

职责边界：只产生 Document/SourceBlock 与受控失败，不给用户评能力、
不执行文件内指令、不做 Knowledge 入库（M1-03 的激活链负责）。
校验全部发生在任何持久化写入之前：失败不留半成品记录。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.documents import BlockPage, DocumentRepository
from zhijue.adapters.db.models import Document, Profile
from zhijue.adapters.pdf import extract_pdf_pages, extract_text_pages, sniff_kind
from zhijue.domain.errors import DocumentRejected
from zhijue.domain.extraction import ExtractionLimits, decide_status

_ALLOWED_KINDS = {"resume", "project"}
_MIME_BY_KIND = {
    "pdf": {
        "resume": "application/pdf",
        "project": "application/pdf",
    },
    "text": {
        "resume": "text/plain; charset=utf-8",
        "project": "text/plain; charset=utf-8",
    },
}


class DocumentService:
    def __init__(
        self,
        *,
        engine: Engine,
        repo: DocumentRepository,
        limits: ExtractionLimits,
        extractors: Mapping[str, Callable[..., list[Any]]] | None = None,
    ) -> None:
        self._engine = engine
        self._repo = repo
        self.limits = limits
        # 提取器按 MIME 家族注入：真实路径用 pypdf/文本解码，测试可换实现而不改业务逻辑。
        self._extractors: Mapping[str, Callable[..., list[Any]]] = extractors or {
            "pdf": extract_pdf_pages,
            "text": extract_text_pages,
        }

    def session(self) -> Session:
        return Session(self._engine)

    def import_document(
        self, *, profile_id: str, data: bytes, filename: str, kind: str
    ) -> Document:
        if kind not in _ALLOWED_KINDS:
            raise DocumentRejected(
                "INVALID_REQUEST", f"kind 必须是 resume/project：{kind!r}"
            )
        if len(data) > self.limits.max_bytes:
            raise DocumentRejected(
                "FILE_TOO_LARGE",
                f"文件 {len(data)} 字节，超过上限 {self.limits.max_bytes}。",
                retry_hint="reduce_document",
            )
        if self._repo.count_for_profile(profile_id) >= self.limits.max_documents:
            raise DocumentRejected(
                "DOCUMENT_LIMIT",
                f"每个档案最多 {self.limits.max_documents} 份材料。",
                retry_hint="delete_first",
            )
        with self.session() as check:
            if check.scalar(select(Profile.id).where(Profile.id == profile_id)) is None:
                raise DocumentRejected("RESOURCE_NOT_FOUND", "档案不存在。")

        sniffed = sniff_kind(data)
        pages = self._extractors[sniffed](data, limits=self.limits)
        status, warnings = decide_status(pages)
        return self._repo.save(
            profile_id=profile_id,
            kind=kind,
            filename_display=filename,
            data=data,
            mime=_MIME_BY_KIND[sniffed][kind],
            extract_status=status,
            warnings=warnings,
            pages=pages,
        )

    def list_blocks(
        self, document_id: str, *, cursor: str | None, limit: int
    ) -> BlockPage:
        return self._repo.list_blocks(document_id, cursor=cursor, limit=limit)

    def list_documents(self, profile_id: str) -> list[Document]:
        return self._repo.list_documents(profile_id)

    def get_document(self, document_id: str) -> Document | None:
        return self._repo.get(document_id)
