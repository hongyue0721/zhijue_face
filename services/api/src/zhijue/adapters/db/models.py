"""SQLAlchemy 2 表模型：docs/03-architecture §3 实体清单的持久化形状。

规则：
- 仅本文件+迁移持有业务 Schema（唯一写入方，ADR 级约束）；P1 的 TrainingMemory 不建表。
- 时间统一 RFC3339 UTC 字符串；JSON 列存放版本化快照（docs/03 §7"第一版不把每个词建表"）。
- 关键唯一键：(scope,idempotency_key)、(operation_id,seq)、answer.question_id 一份已接受作答。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now_rfc3339() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(String(32), default=utc_now_rfc3339)
    updated_at: Mapped[str] = mapped_column(
        String(32), default=utc_now_rfc3339, onupdate=utc_now_rfc3339
    )


class Profile(TimestampMixin, Base):
    __tablename__ = "profile"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), default="local")
    display_name: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    # active / deleting / deleted（docs/03 §3）；tombstone 先于清理。
    status: Mapped[str] = mapped_column(String(16), default="active")


class Document(TimestampMixin, Base):
    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profile.id"))
    kind: Mapped[str] = mapped_column(String(16))  # resume / project
    filename_display: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    # pending / parsed / requires_text / failed（扫描件不假装 OCR）。
    extract_status: Mapped[str] = mapped_column(String(24), default="pending")
    # pending / indexing / ready / failed（双存储一致性：索引是副本，回执成功才激活）。
    index_status: Mapped[str] = mapped_column(String(16), default="pending")
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)


class SourceBlock(Base):
    __tablename__ = "source_block"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"))
    page_number: Mapped[int | None] = mapped_column(Integer)  # 从 1 起；纯文本为 null
    block_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(16))  # text_layer / ocr / user_input
    created_at: Mapped[str] = mapped_column(String(32), default=utc_now_rfc3339)

    __table_args__ = (UniqueConstraint("document_id", "page_number", "block_index"),)


class Claim(TimestampMixin, Base):
    __tablename__ = "claim"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profile.id"))
    text: Mapped[str] = mapped_column(Text)
    source_block_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # [{source_block_id, exact_quote}]；exact_quote 必须是块文本子串（语义校验在应用层）。
    source_quotes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # proposed / confirmed / disputed / retracted
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("claim.id"))


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshot"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profile.id"))
    revision: Mapped[int] = mapped_column(Integer)
    confirmed_claim_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    display_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(32), default=utc_now_rfc3339)

    __table_args__ = (UniqueConstraint("profile_id", "revision"),)


class Interview(TimestampMixin, Base):
    __tablename__ = "interview"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), default="local")
    profile_snapshot_id: Mapped[str] = mapped_column(ForeignKey("profile_snapshot.id"))
    # 不可变快照字段（docs/03 §2）：一经创建不随资料修改。
    jd_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    seed_bank_version: Mapped[str] = mapped_column(String(32))
    rubric_version: Mapped[str] = mapped_column(String(32))
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_version: Mapped[str] = mapped_column(String(32))
    model_fingerprint: Mapped[str] = mapped_column(String(200), default="")
    sdk_version: Mapped[str] = mapped_column(String(32), default="")
    run_mode: Mapped[str] = mapped_column(String(16))  # live / fixture / replay
    revision: Mapped[int] = mapped_column(Integer, default=0)
    # preparing / prepare_failed / ready / active / finishing / finish_failed / completed
    status: Mapped[str] = mapped_column(String(24), default="preparing")
    root_plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_question_id: Mapped[str | None] = mapped_column(String(128))
    active_operation_id: Mapped[str | None] = mapped_column(String(128))
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    report_id: Mapped[str | None] = mapped_column(String(128))
    limitations: Mapped[list[Any]] = mapped_column(JSON, default=list)


class Question(TimestampMixin, Base):
    __tablename__ = "question"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview.id"))
    root_id: Mapped[str] = mapped_column(String(128))  # 主问题时等于自身 id
    kind: Mapped[str] = mapped_column(String(24))  # main / follow_up / clarification
    seed_id: Mapped[str | None] = mapped_column(String(128))
    wording: Mapped[str] = mapped_column(Text)
    # {basis_type: resume|jd|gap, evidence_ids, assumption}（docs/04 §4）
    basis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rubric_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class Answer(Base):
    __tablename__ = "answer"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("question.id"))
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview.id"))
    client_turn_id: Mapped[str] = mapped_column(String(128))
    # 首次受理 Answer 的 operation；retry 通过 Operation.parent_operation_id 关联，
    # 不覆盖本字段，保证重复 POST 仍返回原 operation（api.md §6）。
    accepted_operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation.id"), unique=True
    )
    raw_text: Mapped[str] = mapped_column(Text)  # 原文不可覆盖
    # processing / failed / evaluated（retry 不新建 Answer）
    evaluation_status: Mapped[str] = mapped_column(String(16), default="processing")
    assistance: Mapped[str] = mapped_column(
        String(16), default="none"
    )  # none/hint/coached
    created_at: Mapped[str] = mapped_column(String(32), default=utc_now_rfc3339)

    __table_args__ = (
        # 一题一份已接受作答（docs/03 §7；比部分唯一索引更严格且符合契约）。
        UniqueConstraint("question_id"),
        UniqueConstraint("interview_id", "client_turn_id"),
    )


class Observation(Base):
    __tablename__ = "observation"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("answer.id"))
    question_id: Mapped[str] = mapped_column(ForeignKey("question.id"))
    root_question_id: Mapped[str] = mapped_column(String(128))
    relevance: Mapped[str] = mapped_column(String(16))
    knowledge_status: Mapped[str] = mapped_column(String(24))
    criteria: Mapped[list[Any]] = mapped_column(JSON, default=list)
    clarification_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String(32), default=utc_now_rfc3339)


class Decision(Base):
    __tablename__ = "decision"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    observation_id: Mapped[str | None] = mapped_column(ForeignKey("observation.id"))
    root_question_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(16))  # CLARIFY/PROBE/NEXT/END
    reason_code: Mapped[str] = mapped_column(String(48))
    reason_summary: Mapped[str] = mapped_column(Text)
    target: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(32), default=utc_now_rfc3339)


class Assessment(TimestampMixin, Base):
    __tablename__ = "assessment"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview.id"))
    root_question_id: Mapped[str] = mapped_column(String(128))
    criterion_results: Mapped[list[Any]] = mapped_column(JSON, default=list)
    score: Mapped[int | None] = mapped_column(Integer)  # 未评不是 0
    coverage: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(
        String(24)
    )  # scored/skipped/insufficient/disputed/...

    __table_args__ = (
        UniqueConstraint(
            "interview_id",
            "root_question_id",
            name="uq_assessment_interview_root",
        ),
    )


class Report(TimestampMixin, Base):
    __tablename__ = "report"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    interview_id: Mapped[str] = mapped_column(ForeignKey("interview.id"))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    completion: Mapped[str] = mapped_column(String(16))  # complete / incomplete
    overall_score: Mapped[int | None] = mapped_column(Integer)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    root_assessments: Mapped[list[Any]] = mapped_column(JSON, default=list)
    improvements_status: Mapped[str] = mapped_column(
        String(24), default="not_requested"
    )
    active_operation_id: Mapped[str | None] = mapped_column(String(128))
    improvements_operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation.id")
    )
    improved_answers: Mapped[list[Any]] = mapped_column(JSON, default=list)
    limitations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("interview_id", name="uq_report_interview"),)


class ResumeDraft(TimestampMixin, Base):
    __tablename__ = "resume_draft"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profile.id"))
    profile_snapshot_id: Mapped[str] = mapped_column(ForeignKey("profile_snapshot.id"))
    interview_id: Mapped[str | None] = mapped_column(ForeignKey("interview.id"))
    target_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="generating")
    sections: Mapped[list[Any]] = mapped_column(JSON, default=list)
    source_claim_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    changes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    missing_facts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cautions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    target_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active_operation_id: Mapped[str | None] = mapped_column(String(128))
    generation_operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation.id")
    )
    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "profile_snapshot_id",
            "target_hash",
            name="uq_resume_draft_snapshot_target",
        ),
    )


class Operation(TimestampMixin, Base):
    __tablename__ = "operation"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[str] = mapped_column(String(128))
    parent_operation_id: Mapped[str | None] = mapped_column(ForeignKey("operation.id"))
    # 幂等作用域：workspace + method + path（api.md §1）。
    scope: Mapped[str] = mapped_column(String(300))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_event_seq: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("scope", "idempotency_key"),)


class OperationEvent(Base):
    """只追加；payload 必须符合 contracts/operation-event.schema.json（仓储写入时校验）。"""

    __tablename__ = "operation_event"

    operation_id: Mapped[str] = mapped_column(
        ForeignKey("operation.id"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(32), default=utc_now_rfc3339)

    __table_args__ = (
        Index("ix_operation_event_op_seq", "operation_id", "seq", unique=True),
    )
