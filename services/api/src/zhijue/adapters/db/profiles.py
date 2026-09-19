"""Profile / Claim / ProfileSnapshot 仓储：乐观 revision 检查、单事务写入。

不可变性（docs/03 §5）：Claim 状态只按状态机迁移，行内 text/source_* 永不改写；
ProfileSnapshot 没有任何 UPDATE 方法——确认一次产生一行新快照。
手填事实没有上传文件，因此按批次生成一个 `kind=user_input` 的 Document 承载
其 SourceBlock（origin=user_input），保持 document_id 外键与"块必属于文档"不变量。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import (
    Claim,
    Document,
    Profile,
    ProfileSnapshot,
    SourceBlock,
    utc_now_rfc3339,
)
from zhijue.domain.ids import new_id

FACT_DOCUMENT_KIND = "user_input"
FACT_FILENAME_DISPLAY = "手填事实（本批次）"


@dataclass(frozen=True)
class ProfileView:
    """api.md §3 ProfileView 的服务端形态；revision 用于乐观并发。"""

    id: str
    revision: int
    display_name: str
    synthetic: bool
    status: str
    latest_snapshot_id: str | None


class RevisionConflict(ValueError):
    """expected_revision 与库中不一致；HTTP 层映射 409。"""


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _to_view(session: Session, profile: Profile) -> ProfileView:
    latest = session.scalar(
        select(ProfileSnapshot.id)
        .where(ProfileSnapshot.profile_id == profile.id)
        .order_by(ProfileSnapshot.revision.desc())
        .limit(1)
    )
    return ProfileView(
        id=profile.id,
        revision=profile.revision,
        display_name=profile.display_name,
        synthetic=profile.synthetic,
        status=profile.status,
        latest_snapshot_id=latest,
    )


class ProfileRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ---------- 档案 ----------

    def create(self, *, display_name: str, synthetic: bool) -> ProfileView:
        profile = Profile(
            id=new_id("profile"),
            display_name=display_name,
            synthetic=synthetic,
            revision=0,
            status="active",
            created_at=utc_now_rfc3339(),
            updated_at=utc_now_rfc3339(),
        )
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            session.add(profile)
            session.flush()
            return _to_view(session, profile)

    def get_view(self, profile_id: str) -> ProfileView | None:
        with Session(self._engine, expire_on_commit=False) as session:
            profile = session.get(Profile, profile_id)
            return None if profile is None else _to_view(session, profile)

    # ---------- 事实与 Claim ----------

    def add_facts(
        self,
        *,
        profile_id: str,
        expected_revision: int,
        items: list[tuple[str, str]],
    ) -> ProfileView:
        """items 为 (section, text) 序列；单事务写 Document+Block+Claim 并推进 revision。"""
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            profile = self._require_active(session, profile_id)
            if profile.revision != expected_revision:
                raise RevisionConflict(
                    f"REVISION_CONFLICT: 服务端 revision={profile.revision}, 请求={expected_revision}"
                )
            payload = "\n".join(text for _, text in items).encode("utf-8")
            document = Document(
                id=new_id("document"),
                profile_id=profile_id,
                kind=FACT_DOCUMENT_KIND,
                filename_display=FACT_FILENAME_DISPLAY,
                sha256=hashlib.sha256(payload).hexdigest(),
                mime="text/plain",
                size=len(payload),
                page_count=None,
                extract_status="parsed",
                index_status="pending",
                warnings=[],
                created_at=utc_now_rfc3339(),
                updated_at=utc_now_rfc3339(),
            )
            session.add(document)
            for index, (section, text) in enumerate(items):
                text = text.strip()
                block = SourceBlock(
                    id=new_id("block"),
                    document_id=document.id,
                    page_number=None,
                    block_index=index,
                    text=text,
                    text_hash=_text_hash(text),
                    origin="user_input",
                )
                session.add(block)
                session.add(
                    Claim(
                        id=new_id("claim"),
                        profile_id=profile_id,
                        text=text,
                        source_block_ids=[block.id],
                        source_quotes=[
                            {
                                "source_block_id": block.id,
                                "exact_quote": text,
                                "text_context": text,
                                "origin": "user_input",
                                "section": section,
                            }
                        ],
                        status="proposed",
                        supersedes_id=None,
                        created_at=utc_now_rfc3339(),
                        updated_at=utc_now_rfc3339(),
                    )
                )
            profile.revision += 1
            profile.updated_at = utc_now_rfc3339()
            session.flush()
            return _to_view(session, profile)

    def list_claims(self, profile_id: str) -> list[Claim]:
        with Session(self._engine, expire_on_commit=False) as session:
            return list(
                session.scalars(
                    select(Claim)
                    .where(Claim.profile_id == profile_id)
                    .order_by(Claim.created_at, Claim.id)
                )
            )

    def confirm(
        self,
        *,
        profile_id: str,
        expected_revision: int,
        decisions: list[dict[str, str]],
    ) -> tuple[ProfileView, ProfileSnapshot]:
        """应用裁决、产生不可变快照并推进 revision；单事务。"""
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            profile = self._require_active(session, profile_id)
            if profile.revision != expected_revision:
                raise RevisionConflict(
                    f"REVISION_CONFLICT: 服务端 revision={profile.revision}, 请求={expected_revision}"
                )
            self._apply_decisions(session, profile_id, decisions)
            profile.revision += 1
            profile.updated_at = utc_now_rfc3339()
            confirmed = [
                claim.id
                for claim in session.scalars(
                    select(Claim)
                    .where(Claim.profile_id == profile_id, Claim.status == "confirmed")
                    .order_by(Claim.created_at, Claim.id)
                )
            ]
            snapshot = ProfileSnapshot(
                id=new_id("snapshot"),
                profile_id=profile_id,
                revision=profile.revision,
                confirmed_claim_ids=confirmed,
                display_fields=self._display_fields(session, confirmed),
                created_at=utc_now_rfc3339(),
            )
            session.add(snapshot)
            session.flush()
            return _to_view(session, profile), snapshot

    def get_snapshot(self, snapshot_id: str) -> ProfileSnapshot | None:
        with Session(self._engine, expire_on_commit=False) as session:
            return session.get(ProfileSnapshot, snapshot_id)

    # ---------- 内部 ----------

    def _apply_decisions(
        self, session: Session, profile_id: str, decisions: list[dict[str, str]]
    ) -> None:
        seen: set[str] = set()
        for decision in decisions:
            claim_id = decision.get("claim_id", "")
            action = decision.get("action", "")
            if claim_id in seen:
                raise ValueError(f"同一 Claim 在一次确认中出现多次：{claim_id}")
            seen.add(claim_id)
            claim = session.get(Claim, claim_id)
            if claim is None or claim.profile_id != profile_id:
                raise ValueError(f"CLAIM_NOT_FOUND: {claim_id} 不属于当前档案")
            if claim.status == "retracted":
                raise ValueError(f"CLAIM_RETRACTED: {claim_id} 已撤回，不能再裁决")
            if action == "accept":
                self._assert_transition(claim, "confirmed")
                claim.status = "confirmed"
            elif action == "reject":
                self._assert_transition(claim, "retracted")
                claim.status = "retracted"
            elif action == "correct":
                corrected = (decision.get("corrected_text") or "").strip()
                if not corrected:
                    raise ValueError("correct 必须提供 corrected_text")
                self._assert_transition(claim, "retracted")
                claim.status = "retracted"
                block = SourceBlock(
                    id=new_id("block"),
                    document_id=self._correction_document(
                        session, profile_id, corrected
                    ),
                    page_number=None,
                    block_index=0,
                    text=corrected,
                    text_hash=_text_hash(corrected),
                    origin="user_input",
                )
                session.add(block)
                session.add(
                    Claim(
                        id=new_id("claim"),
                        profile_id=profile_id,
                        text=corrected,
                        source_block_ids=[block.id],
                        source_quotes=[
                            {
                                "source_block_id": block.id,
                                "exact_quote": corrected,
                                "text_context": corrected,
                                "origin": "user_input",
                                "section": self._section_of(claim),
                            }
                        ],
                        status="confirmed",
                        supersedes_id=claim.id,
                        created_at=utc_now_rfc3339(),
                        updated_at=utc_now_rfc3339(),
                    )
                )
            else:
                raise ValueError(f"未知裁决动作：{action!r}")

    def _correction_document(self, session: Session, profile_id: str, text: str) -> str:
        """更正产生新的 user_input 依据（docs/03 §5.3），与手填批次同样落到 Document。"""
        payload = text.encode("utf-8")
        document = Document(
            id=new_id("document"),
            profile_id=profile_id,
            kind=FACT_DOCUMENT_KIND,
            filename_display="手填事实（更正）",
            sha256=hashlib.sha256(payload).hexdigest(),
            mime="text/plain",
            size=len(payload),
            page_count=None,
            extract_status="parsed",
            index_status="pending",
            warnings=[],
            created_at=utc_now_rfc3339(),
            updated_at=utc_now_rfc3339(),
        )
        session.add(document)
        session.flush()
        return document.id

    @staticmethod
    def _section_of(claim: Claim) -> str:
        quotes = claim.source_quotes or []
        return quotes[0].get("section", "other") if quotes else "other"

    @staticmethod
    def _assert_transition(claim: Claim, target: str) -> None:
        from zhijue.domain.claims import ClaimStatus, ensure_transition

        ensure_transition(ClaimStatus(claim.status), ClaimStatus(target))

    def _display_fields(
        self, session: Session, confirmed_claim_ids: list[str]
    ) -> dict[str, list[str]]:
        """确认快照的可展示字段：按 section 归组已确认原文（不改写）。"""
        if not confirmed_claim_ids:
            return {}
        grouped: dict[str, list[str]] = {}
        for claim in session.scalars(
            select(Claim)
            .where(Claim.id.in_(confirmed_claim_ids))
            .order_by(Claim.created_at, Claim.id)
        ):
            section = self._section_of(claim)
            grouped.setdefault(section, []).append(claim.text)
        return grouped

    @staticmethod
    def _require_active(session: Session, profile_id: str) -> Profile:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise ValueError(f"RESOURCE_NOT_FOUND: profile {profile_id}")
        if profile.status != "active":
            raise ValueError(f"PROFILE_NOT_ACTIVE: {profile.status}")
        return profile

    # ---------- 其他查询 ----------

    def count_documents(self, profile_id: str) -> int:
        with Session(self._engine) as session:
            return session.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.profile_id == profile_id)
            )

    def documents_for_blocks(self, block_ids: list[str]) -> list[str]:
        """来源块 → 所属 Document：激活时用于推进 index_status。"""
        if not block_ids:
            return []
        with Session(self._engine) as session:
            return sorted(
                set(
                    session.scalars(
                        select(SourceBlock.document_id).where(
                            SourceBlock.id.in_(block_ids)
                        )
                    )
                )
            )

    def set_index_status(self, document_ids: list[str], status: str) -> None:
        """索引状态随回执推进；原始文件、块与 Claim 文本都不因此改变。"""
        ids = sorted(set(document_ids))
        if not ids:
            return
        with Session(self._engine) as session, session.begin():
            for document in session.scalars(
                select(Document).where(Document.id.in_(ids))
            ):
                document.index_status = status
                document.updated_at = utc_now_rfc3339()
