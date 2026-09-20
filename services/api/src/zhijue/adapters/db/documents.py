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

from zhijue.adapters.db.models import (
    Claim,
    Document,
    Profile,
    SourceBlock,
    utc_now_rfc3339,
)
from zhijue.adapters.db.profiles import RevisionConflict
from zhijue.domain.ids import new_id

_BLOCK_ORDER = (
    func.coalesce(SourceBlock.page_number, 0),
    SourceBlock.block_index,
)


@dataclass(frozen=True)
class BlockPage:
    items: list[SourceBlock]
    next_cursor: str | None


@dataclass(frozen=True)
class SourceBlockWrite:
    id: str
    page_number: int | None
    block_index: int
    text: str
    origin: str


@dataclass(frozen=True)
class ProposedClaimWrite:
    text: str
    source_block_id: str
    exact_quote: str
    section: str


@dataclass(frozen=True)
class DocumentWriteResult:
    document: Document
    resource_revision: int
    proposed_claim_count: int


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

    def require_revision(self, profile_id: str, expected_revision: int) -> None:
        """Reject stale uploads before parsing or making a paid model call."""

        with Session(self._engine) as session:
            profile = self._require_active_profile(session, profile_id)
            self._check_revision(profile, expected_revision)

    def save(
        self,
        *,
        profile_id: str,
        expected_revision: int,
        kind: str,
        filename_display: str,
        data: bytes,
        mime: str,
        extract_status: str,
        warnings: list[str],
        page_count: int | None,
        blocks: list[SourceBlockWrite],
        claims: list[ProposedClaimWrite],
    ) -> DocumentWriteResult:
        """Atomically persist Document, blocks, proposed Claims, and revision."""

        block_by_id = {block.id: block for block in blocks}
        if len(block_by_id) != len(blocks):
            raise ValueError("duplicate source block id")
        for claim in claims:
            block = block_by_id.get(claim.source_block_id)
            if block is None:
                raise ValueError("claim references an unknown source block")
            if claim.text != claim.exact_quote or claim.exact_quote not in block.text:
                raise ValueError("claim must equal one verbatim source quote")

        now = utc_now_rfc3339()
        document = Document(
            id=new_id("document"),
            profile_id=profile_id,
            kind=kind,
            filename_display=filename_display,
            sha256=hashlib.sha256(data).hexdigest(),
            mime=mime,
            size=len(data),
            page_count=page_count,
            extract_status=extract_status,
            index_status="pending",
            warnings=warnings,
            created_at=now,
            updated_at=now,
        )
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            profile = self._require_active_profile(session, profile_id)
            self._check_revision(profile, expected_revision)
            session.add(document)
            for block in blocks:
                session.add(
                    SourceBlock(
                        id=block.id,
                        document_id=document.id,
                        page_number=block.page_number,
                        block_index=block.block_index,
                        text=block.text,
                        text_hash=_page_text_hash(block.text),
                        origin=block.origin,
                    )
                )
            for claim in claims:
                block = block_by_id[claim.source_block_id]
                session.add(
                    Claim(
                        id=new_id("claim"),
                        profile_id=profile_id,
                        text=claim.text,
                        source_block_ids=[claim.source_block_id],
                        source_quotes=[
                            {
                                "source_block_id": claim.source_block_id,
                                "exact_quote": claim.exact_quote,
                                "text_context": claim.exact_quote,
                                "origin": block.origin,
                                "section": claim.section,
                            }
                        ],
                        status="proposed",
                        supersedes_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            profile.revision += 1
            profile.updated_at = now
            session.flush()
            session.refresh(document)
            return DocumentWriteResult(
                document=document,
                resource_revision=profile.revision,
                proposed_claim_count=len(claims),
            )

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

    @staticmethod
    def _require_active_profile(session: Session, profile_id: str) -> Profile:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise ValueError("RESOURCE_NOT_FOUND: 档案不存在。")
        if profile.status != "active":
            raise ValueError("INVALID_STATE: 档案不可写入。")
        return profile

    @staticmethod
    def _check_revision(profile: Profile, expected_revision: int) -> None:
        if profile.revision != expected_revision:
            raise RevisionConflict(
                f"REVISION_CONFLICT: 服务端 revision={profile.revision}, "
                f"请求={expected_revision}"
            )
