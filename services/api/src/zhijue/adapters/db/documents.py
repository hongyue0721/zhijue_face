"""Document / SourceBlock 仓储：单事务落库、分页只读查询。

SourceBlock 不可变（docs/03 §5）：没有任何 UPDATE 方法；替换文件=新 Document。
分页游标是行偏移的不可逆封装（块集合本身不变化，稳定成立）。
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import Document, SourceBlock, utc_now_rfc3339
from zhijue.domain.extraction import PageText
from zhijue.domain.ids import new_id

_BLOCK_ORDER = (
    func.coalesce(SourceBlock.page_number, 0),
    SourceBlock.block_index,
)


@dataclass(frozen=True)
class BlockPage:
    items: list[SourceBlock]
    next_cursor: str | None


def _page_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def count_for_profile(self, profile_id: str) -> int:
        with Session(self._engine) as session:
            return session.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.profile_id == profile_id)
            )

    def list_documents(self, profile_id: str) -> list[Document]:
        """ProfileView.documents；不含文件系统路径（api.md §3）。"""
        with Session(self._engine, expire_on_commit=False) as session:
            return list(
                session.scalars(
                    select(Document)
                    .where(Document.profile_id == profile_id)
                    .order_by(Document.created_at, Document.id)
                )
            )

    def save(
        self,
        *,
        profile_id: str,
        kind: str,
        filename_display: str,
        data: bytes,
        mime: str,
        extract_status: str,
        warnings: list[str],
        pages: list[PageText],
    ) -> Document:
        """Document 与其全部 SourceBlock 在一个事务提交，不留半套。"""
        sha256 = hashlib.sha256(data).hexdigest()
        document = Document(
            id=new_id("document"),
            profile_id=profile_id,
            kind=kind,
            filename_display=filename_display,
            sha256=sha256,
            mime=mime,
            size=len(data),
            page_count=max((p.page_number or 0) for p in pages) if pages else None,
            extract_status=extract_status,
            warnings=warnings,
            created_at=utc_now_rfc3339(),
            updated_at=utc_now_rfc3339(),
        )
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            session.add(document)
            for page in pages:
                if not page.text.strip():
                    continue  # 缺文字层页不生成空块（警告已在 Document.warnings）
                session.add(
                    SourceBlock(
                        id=new_id("block"),
                        document_id=document.id,
                        page_number=page.page_number,
                        block_index=0,
                        text=page.text,
                        text_hash=_page_text_hash(page.text),
                        origin="text_layer",
                    )
                )
            session.flush()
            session.refresh(document)
            return document

    def get(self, document_id: str) -> Document | None:
        with Session(self._engine, expire_on_commit=False) as session:
            return session.get(Document, document_id)

    def list_blocks(
        self, document_id: str, *, cursor: str | None, limit: int
    ) -> BlockPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1—100")  # api.md §4
        offset = 0
        if cursor is not None:
            try:
                offset = int(base64.b64decode(cursor.encode("ascii")).decode("ascii"))
            except Exception as exc:
                raise ValueError("无效分页游标") from exc
            if offset < 0:
                raise ValueError("无效分页游标")
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(SourceBlock)
                    .where(SourceBlock.document_id == document_id)
                    .order_by(*_BLOCK_ORDER)
                    .offset(offset)
                    .limit(limit + 1)
                )
            )
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = (
            base64.b64encode(str(offset + limit).encode("ascii")).decode("ascii")
            if has_more and items
            else None
        )
        return BlockPage(items=items, next_cursor=next_cursor)
