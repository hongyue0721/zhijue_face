"""Profile / Claim / ProfileSnapshot 仓储：乐观 revision 检查、单事务写入。

不可变性（docs/03 §5）：Claim 状态只按状态机迁移，行内 text/source_* 永不改写；
ProfileSnapshot 没有任何 UPDATE 方法——确认一次产生一行新快照。
手填事实没有上传文件，因此按批次生成一个 `kind=user_input` 的 Document 承载
其 SourceBlock（origin=user_input），保持 document_id 外键与"块必属于文档"不变量。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from threading import Lock
from typing import Any

from sqlalchemy import Engine, and_, delete, func, or_, select, text
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import (
    Answer,
    Assessment,
    Claim,
    Decision,
    Document,
    Interview,
    Observation,
    Operation,
    OperationEvent,
    Profile,
    ProfileSnapshot,
    ProfileSnapshotActivation,
    Question,
    Report,
    ResumeDraft,
    SourceBlock,
    utc_now_rfc3339,
)
from zhijue.adapters.db.operations import OperationCommand, OperationRepository
from zhijue.domain.errors import (
    CapacityLimitedError,
    InvalidStateError,
    ResourceNotFoundError,
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
    active_operation_id: str | None
    snapshot_activation: dict[str, Any] | None


@dataclass(frozen=True)
class AcceptedProfileOperation:
    operation: Operation
    created: bool


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
    activation = session.get(ProfileSnapshotActivation, latest) if latest else None
    active_operation_id = session.scalar(
        select(Operation.id)
        .where(
            Operation.resource_type == "profile",
            Operation.resource_id == profile.id,
            or_(
                Operation.status.in_(("queued", "running")),
                # 删除失败/中断后档案停在 deleting：回执操作必须从 ProfileView
                # 可恢复显式重试，否则用户刷新后永远找不到恢复入口。
                and_(
                    Operation.kind == "profile.delete",
                    Operation.status.in_(("failed", "interrupted")),
                ),
            ),
        )
        .order_by(Operation.created_at.desc(), Operation.id)
        .limit(1)
    )
    return ProfileView(
        id=profile.id,
        revision=profile.revision,
        display_name=profile.display_name,
        synthetic=profile.synthetic,
        status=profile.status,
        latest_snapshot_id=latest,
        active_operation_id=active_operation_id,
        snapshot_activation=(
            {
                "snapshot_id": latest,
                "status": activation.status if activation else "pending",
                "operation_id": activation.operation_id if activation else None,
            }
            if latest
            else None
        ),
    )


class ProfileRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._operations = OperationRepository(engine)
        self._acceptance_lock = Lock()

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
            profile, snapshot = self._confirm_in_session(
                session, profile_id, expected_revision, decisions
            )
            return _to_view(session, profile), snapshot

    def _confirm_in_session(
        self,
        session: Session,
        profile_id: str,
        expected_revision: int,
        decisions: list[dict[str, str]],
    ) -> tuple[Profile, ProfileSnapshot]:
        profile = self._require_active(session, profile_id)
        self._require_revision(profile, expected_revision)
        if not decisions:
            raise ValueError("decisions 不能为空")
        self._apply_decisions(session, profile_id, decisions)
        profile.revision += 1
        profile.updated_at = utc_now_rfc3339()
        confirmed = list(
            session.scalars(
                select(Claim.id)
                .where(Claim.profile_id == profile_id, Claim.status == "confirmed")
                .order_by(Claim.created_at, Claim.id)
            )
        )
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
        session.add(
            ProfileSnapshotActivation(snapshot_id=snapshot.id, status="pending")
        )
        session.flush()
        return profile, snapshot

    def get_snapshot(self, snapshot_id: str) -> ProfileSnapshot | None:
        with Session(self._engine, expire_on_commit=False) as session:
            return session.get(ProfileSnapshot, snapshot_id)

    def _existing_operation(
        self, session: Session, command: OperationCommand
    ) -> Operation | None:
        existing = session.scalar(
            select(Operation).where(
                Operation.scope == command.scope,
                Operation.idempotency_key == command.idempotency_key,
            )
        )
        return (
            self._operations.accept_in_session(session, command)
            if existing is not None
            else None
        )

    def accept_confirmation(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        decisions: list[dict[str, str]],
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing = self._existing_operation(session, command)
            if existing is not None:
                return AcceptedProfileOperation(existing, created=False)
            if not capacity_available:
                raise CapacityLimitedError()
            self._require_idle(session, profile_id)
            _profile, snapshot = self._confirm_in_session(
                session, profile_id, expected_revision, decisions
            )
            operation = self._operations.accept_in_session(session, command)
            activation = session.get(ProfileSnapshotActivation, snapshot.id)
            activation.operation_id = operation.id
            activation.status = "indexing"
            return AcceptedProfileOperation(operation, created=True)

    def accept_activation(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing = self._existing_operation(session, command)
            if existing is not None:
                return AcceptedProfileOperation(existing, created=False)
            profile = self._require_active(session, profile_id)
            self._require_revision(profile, expected_revision)
            snapshot = self._latest_snapshot(session, profile_id)
            if snapshot is None or not snapshot.confirmed_claim_ids:
                raise InvalidStateError("资料快照没有已确认事实，请先补充并确认。")
            activation = session.get(ProfileSnapshotActivation, snapshot.id)
            if activation is not None and activation.operation_id is not None:
                return AcceptedProfileOperation(
                    session.get(Operation, activation.operation_id), created=False
                )
            self._require_idle(session, profile_id)
            if not capacity_available:
                raise CapacityLimitedError()
            operation = self._operations.accept_in_session(session, command)
            if activation is None:
                activation = ProfileSnapshotActivation(snapshot_id=snapshot.id)
                session.add(activation)
            activation.operation_id = operation.id
            activation.status = "indexing"
            activation.updated_at = utc_now_rfc3339()
            return AcceptedProfileOperation(operation, created=True)

    # ---------- 删除：先 tombstone，再级联清理（api.md §4） ----------

    def accept_deletion(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        """DELETE 只受理 tombstone（status=deleting）与 Operation；真正清理由后台执行。

        deleting 后其余写入被 `_require_active` 拒绝；重复提交返回原操作；
        存在未终结业务操作时拒绝受理，避免与清理竞争写入。
        """
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing = self._existing_operation(session, command)
            if existing is not None:
                return AcceptedProfileOperation(existing, created=False)
            profile = session.get(Profile, profile_id)
            if profile is None or profile.status == "deleted":
                raise ResourceNotFoundError("档案不存在。")
            if profile.status == "deleting":
                running = session.scalar(
                    select(Operation.id).where(
                        Operation.resource_type == "profile",
                        Operation.resource_id == profile_id,
                        Operation.kind == "profile.delete",
                        Operation.status.in_(("queued", "running")),
                    )
                )
                if running is not None:
                    return AcceptedProfileOperation(
                        session.get(Operation, running), created=False
                    )
                raise InvalidStateError(
                    "档案正在删除或等待重试，请刷新真实状态后再操作。"
                )
            self._require_revision(profile, expected_revision)
            if not capacity_available:
                raise CapacityLimitedError()
            resource_ids = self._related_resource_ids(session, profile_id)
            active = session.scalar(
                select(Operation.id)
                .where(
                    Operation.status.in_(("queued", "running")),
                    Operation.resource_id.in_(resource_ids),
                )
                .limit(1)
            )
            if active is not None:
                raise InvalidStateError("档案存在未终结的操作，请先等待其完成或失败。")
            operation = self._operations.accept_in_session(session, command)
            profile.status = "deleting"
            profile.updated_at = utc_now_rfc3339()
            return AcceptedProfileOperation(operation, created=True)

    def _related_resource_ids(self, session: Session, profile_id: str) -> list[str]:
        """档案及其派生资源的 ID 集合，用于在途操作检查与级联清理。"""
        ids = [profile_id]
        ids += list(
            session.scalars(
                select(Document.id).where(Document.profile_id == profile_id)
            )
        )
        snapshot_ids = list(
            session.scalars(
                select(ProfileSnapshot.id).where(
                    ProfileSnapshot.profile_id == profile_id
                )
            )
        )
        ids += snapshot_ids
        interview_ids = (
            list(
                session.scalars(
                    select(Interview.id).where(
                        Interview.profile_snapshot_id.in_(snapshot_ids)
                    )
                )
            )
            if snapshot_ids
            else []
        )
        ids += interview_ids
        ids += list(
            session.scalars(
                select(ResumeDraft.id).where(ResumeDraft.profile_id == profile_id)
            )
        )
        return sorted(set(ids))

    def knowledge_source_ids(self, profile_id: str) -> list[str]:
        """全部激活回执里的 source_id：Knowledge 清理只删确实写过的来源。"""
        with Session(self._engine) as session:
            receipts = session.scalars(
                select(ProfileSnapshotActivation.receipt)
                .join(
                    ProfileSnapshot,
                    ProfileSnapshot.id == ProfileSnapshotActivation.snapshot_id,
                )
                .where(ProfileSnapshot.profile_id == profile_id)
            ).all()
        ids: set[str] = set()
        for receipt in receipts:
            if isinstance(receipt, dict):
                ids.update(
                    source_id
                    for source_id in (receipt.get("source_ids") or [])
                    if isinstance(source_id, str)
                )
        return sorted(ids)

    def purge_profile(self, profile_id: str) -> dict[str, int]:
        """单事务级联清理：任何一步失败整体回滚，绝不留下半清理状态。

        只保留 profile.delete 回执 Operation；档案行最后物理删除，
        之后 GET 返回 404（tombstone 的意义是阻止并发写入，不是永久保留行）。
        """
        with Session(self._engine) as session, session.begin():
            # 同一事务内延迟 FK：claim.supersedes_id / operation.parent_operation_id
            # 自引用行会在同一条 DELETE 中互相引用，immediate 检查会误报。
            session.execute(text("PRAGMA defer_foreign_keys=ON"))
            profile = session.get(Profile, profile_id)
            if profile is None or profile.status != "deleting":
                raise InvalidStateError("档案不处于待删除状态，拒绝清理。")
            snapshot_ids = list(
                session.scalars(
                    select(ProfileSnapshot.id).where(
                        ProfileSnapshot.profile_id == profile_id
                    )
                )
            )
            interview_ids = (
                list(
                    session.scalars(
                        select(Interview.id).where(
                            Interview.profile_snapshot_id.in_(snapshot_ids)
                        )
                    )
                )
                if snapshot_ids
                else []
            )
            document_ids = list(
                session.scalars(
                    select(Document.id).where(Document.profile_id == profile_id)
                )
            )
            resource_ids = set(self._related_resource_ids(session, profile_id))
            # profile.delete 整条链（失败原操作与 retry 子操作）是删除回执，
            # 全部保留；其余关联操作连同事件一并清理。
            operation_ids = set(
                session.scalars(
                    select(Operation.id).where(
                        Operation.resource_id.in_(resource_ids),
                        Operation.kind != "profile.delete",
                    )
                )
            )
            if operation_ids:
                operation_ids.update(
                    session.scalars(
                        select(Operation.id).where(
                            Operation.parent_operation_id.in_(operation_ids),
                            Operation.kind != "profile.delete",
                        )
                    )
                )
            counts: dict[str, int] = {}

            def _purge(model: Any, condition: Any, label: str) -> None:
                counts[label] = session.execute(delete(model).where(condition)).rowcount

            if interview_ids:
                question_ids = select(Question.id).where(
                    Question.interview_id.in_(interview_ids)
                )
                _purge(
                    Decision,
                    Decision.observation_id.in_(
                        select(Observation.id).where(
                            Observation.question_id.in_(question_ids)
                        )
                    ),
                    "decision",
                )
                _purge(
                    Observation,
                    Observation.question_id.in_(question_ids),
                    "observation",
                )
                _purge(Answer, Answer.interview_id.in_(interview_ids), "answer")
                _purge(Question, Question.interview_id.in_(interview_ids), "question")
                _purge(
                    Assessment,
                    Assessment.interview_id.in_(interview_ids),
                    "assessment",
                )
                _purge(Report, Report.interview_id.in_(interview_ids), "report")
                _purge(Interview, Interview.id.in_(interview_ids), "interview")
            if snapshot_ids:
                _purge(
                    ProfileSnapshotActivation,
                    ProfileSnapshotActivation.snapshot_id.in_(snapshot_ids),
                    "snapshot_activation",
                )
                _purge(
                    ProfileSnapshot,
                    ProfileSnapshot.id.in_(snapshot_ids),
                    "profile_snapshot",
                )
            _purge(ResumeDraft, ResumeDraft.profile_id == profile_id, "resume_draft")
            _purge(Claim, Claim.profile_id == profile_id, "claim")
            if document_ids:
                _purge(
                    SourceBlock,
                    SourceBlock.document_id.in_(document_ids),
                    "source_block",
                )
            _purge(Document, Document.profile_id == profile_id, "document")
            if operation_ids:
                _purge(
                    OperationEvent,
                    OperationEvent.operation_id.in_(operation_ids),
                    "operation_event",
                )
                _purge(Operation, Operation.id.in_(operation_ids), "operation")
            session.delete(profile)
            counts["profile"] = 1
            return counts

    def accept_retry(
        self,
        operation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_input: dict[str, Any],
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            original = session.get(Operation, operation_id)
            if original is None:
                raise ResourceNotFoundError("原操作不存在。")
            if original.kind not in {
                "profile.confirm",
                "profile.activate",
                "profile.delete",
            }:
                raise InvalidStateError("该操作不是资料确认或资料删除操作。")
            retry_scope = f"{original.scope}#retry_of_{original.id}"
            existing = session.scalar(
                select(Operation).where(
                    Operation.scope == retry_scope,
                    Operation.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                operation = self._operations.retry_in_session(
                    session,
                    original,
                    idempotency_key=idempotency_key,
                    request_input=request_input,
                )
                return AcceptedProfileOperation(operation, created=False)
            if original.kind == "profile.delete":
                # 删除重试只重跑清理：档案必须仍是 deleting tombstone；
                # 不做 revision 检查（deleting 后档案不再接受任何业务写入）。
                tombstone = session.get(Profile, original.resource_id)
                if tombstone is None or tombstone.status != "deleting":
                    raise InvalidStateError("档案不处于待删除状态，拒绝重试清理。")
                if not bool((original.error or {}).get("retryable")):
                    raise InvalidStateError("原操作不可重试。")
                if not capacity_available:
                    raise CapacityLimitedError()
                try:
                    operation = self._operations.retry_in_session(
                        session,
                        original,
                        max_attempts=3,
                        idempotency_key=idempotency_key,
                        request_input=request_input,
                    )
                except ValueError as exc:
                    raise InvalidStateError(str(exc)) from exc
                return AcceptedProfileOperation(operation, created=True)
            profile = self._require_active(session, original.resource_id)
            self._require_revision(profile, expected_revision)
            snapshot = self._latest_snapshot(session, profile.id)
            activation = (
                session.get(ProfileSnapshotActivation, snapshot.id)
                if snapshot is not None
                else None
            )
            if (
                activation is None
                or activation.operation_id != original.id
                or activation.status != "failed"
            ):
                raise InvalidStateError("激活操作已被其他操作或新资料快照取代。")
            self._require_idle(session, profile.id)
            if not bool((original.error or {}).get("retryable")):
                raise InvalidStateError("原操作不可重试。")
            if not capacity_available:
                raise CapacityLimitedError()
            try:
                operation = self._operations.retry_in_session(
                    session,
                    original,
                    max_attempts=3,
                    idempotency_key=idempotency_key,
                    request_input=request_input,
                )
            except ValueError as exc:
                raise InvalidStateError(str(exc)) from exc
            activation.operation_id = operation.id
            activation.status = "indexing"
            activation.updated_at = utc_now_rfc3339()
            return AcceptedProfileOperation(operation, created=True)

    def snapshot_for_operation(self, operation_id: str) -> ProfileSnapshot:
        with Session(self._engine, expire_on_commit=False) as session:
            activation = session.scalar(
                select(ProfileSnapshotActivation).where(
                    ProfileSnapshotActivation.operation_id == operation_id
                )
            )
            if activation is None:
                raise InvalidStateError("激活操作没有可恢复的资料快照。")
            return session.get(ProfileSnapshot, activation.snapshot_id)

    def set_activation_status(
        self,
        snapshot_id: str,
        status: str,
        *,
        operation_id: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> None:
        with Session(self._engine) as session, session.begin():
            snapshot = session.get(ProfileSnapshot, snapshot_id)
            if snapshot is None:
                raise ResourceNotFoundError("资料快照不存在。")
            activation = session.get(ProfileSnapshotActivation, snapshot_id)
            if activation is None:
                activation = ProfileSnapshotActivation(snapshot_id=snapshot_id)
                session.add(activation)
            if activation.operation_id != operation_id:
                raise InvalidStateError("激活操作已被其他操作取代。")
            if status == "indexing":
                latest = self._latest_snapshot(session, snapshot.profile_id)
                if latest.id != snapshot_id:
                    raise InvalidStateError("激活操作的资料快照已过期。")
            activation.status = status
            activation.receipt = receipt
            activation.updated_at = utc_now_rfc3339()

    def recover_interrupted_operations(self) -> None:
        # Scan persisted state too: the process may have died between operation
        # interruption bookkeeping and this resource recovery in a previous startup.
        with Session(self._engine) as session, session.begin():
            for activation in session.scalars(
                select(ProfileSnapshotActivation).where(
                    ProfileSnapshotActivation.status == "indexing"
                )
            ):
                operation = (
                    session.get(Operation, activation.operation_id)
                    if activation.operation_id
                    else None
                )
                if operation is None or operation.status not in {"queued", "running"}:
                    activation.status = "failed"
                    activation.updated_at = utc_now_rfc3339()
                    snapshot = session.get(ProfileSnapshot, activation.snapshot_id)
                    latest = self._latest_snapshot(session, snapshot.profile_id)
                    if latest.id != snapshot.id:
                        continue
                    block_ids = [
                        block_id
                        for claim in session.scalars(
                            select(Claim).where(
                                Claim.id.in_(snapshot.confirmed_claim_ids)
                            )
                        )
                        for block_id in claim.source_block_ids or []
                    ]
                    document_ids = select(SourceBlock.document_id).where(
                        SourceBlock.id.in_(block_ids)
                    )
                    for document in session.scalars(
                        select(Document).where(
                            Document.id.in_(document_ids),
                            Document.index_status == "indexing",
                        )
                    ):
                        document.index_status = "failed"
                        document.updated_at = utc_now_rfc3339()

    @staticmethod
    def require_ready_snapshot(session: Session, snapshot_id: str) -> ProfileSnapshot:
        snapshot = session.get(ProfileSnapshot, snapshot_id)
        if snapshot is None or not snapshot.confirmed_claim_ids:
            raise InvalidStateError("资料快照没有已确认事实，请先补充并确认。")
        activation = session.get(ProfileSnapshotActivation, snapshot_id)
        if activation is None or activation.status != "ready":
            raise InvalidStateError("该资料快照的 Knowledge 尚未就绪，请先完成激活。")
        return snapshot

    @staticmethod
    def _latest_snapshot(session: Session, profile_id: str) -> ProfileSnapshot | None:
        return session.scalar(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.profile_id == profile_id)
            .order_by(ProfileSnapshot.revision.desc())
            .limit(1)
        )

    @staticmethod
    def _require_revision(profile: Profile, expected_revision: int) -> None:
        if profile.revision != expected_revision:
            raise RevisionConflict(
                f"REVISION_CONFLICT: 服务端 revision={profile.revision}, 请求={expected_revision}"
            )

    @staticmethod
    def _require_idle(session: Session, profile_id: str) -> None:
        active = session.scalar(
            select(Operation.id)
            .where(
                Operation.resource_type == "profile",
                Operation.resource_id == profile_id,
                Operation.status.in_(("queued", "running")),
            )
            .limit(1)
        )
        if active is not None:
            raise InvalidStateError(
                "资料已有进行中的操作。", code="OPERATION_IN_PROGRESS"
            )

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
