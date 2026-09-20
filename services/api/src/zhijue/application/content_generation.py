"""M4-02 grounded coaching and resume-draft lifecycle.

This service is the only write path for generated content. Model candidates pass
through the real openJiuwen workflow and deterministic source validation before
one atomic business commit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from threading import Lock
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import (
    Answer,
    Claim,
    Interview,
    Operation,
    Profile,
    ProfileSnapshot,
    Question,
    Report,
    ResumeDraft,
    utc_now_rfc3339,
)
from zhijue.adapters.db.operations import OperationCommand, OperationRepository
from zhijue.adapters.model import ModelRequestError
from zhijue.application.content_workflow import (
    ContentGenerator,
    ContentWorkflowError,
    run_grounded_content_workflow,
)
from zhijue.domain.errors import (
    CapacityLimitedError,
    InvalidStateError,
    ResourceNotFoundError,
    RevisionConflictError,
    ServiceUnavailableError,
    UpstreamError,
)
from zhijue.domain.grounded_content import GroundedContentValidationError
from zhijue.domain.ids import new_id


@dataclass(frozen=True)
class AcceptedContentOperation:
    operation: Operation
    created: bool


@dataclass(frozen=True)
class _CoachingContext:
    report_id: str
    operation_id: str
    payload: dict[str, Any]
    original_answers: dict[str, list[dict[str, str]]]


@dataclass(frozen=True)
class _ResumeContext:
    draft_id: str
    operation_id: str
    payload: dict[str, Any]


def _public_target_context(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in ("kind", "interview_id", "source_name", "content_hash")
        if value.get(key) is not None
    }


class ContentGenerationService:
    def __init__(
        self,
        *,
        engine: Engine,
        operations: OperationRepository,
        generator: ContentGenerator | None,
        run_mode: str,
        workflow_timeout_seconds: float = 60,
        model_attempt_limit: int = 3,
        generator_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._engine = engine
        self._operations = operations
        self._generator = generator
        self._run_mode = run_mode
        self._workflow_timeout_seconds = workflow_timeout_seconds
        if (
            isinstance(model_attempt_limit, bool)
            or not isinstance(model_attempt_limit, int)
            or not 1 <= model_attempt_limit <= 3
        ):
            raise ValueError("model_attempt_limit must be an integer from 1 to 3")
        self._model_attempt_limit = model_attempt_limit
        self._generator_metadata = dict(generator_metadata or {})
        self._acceptance_lock = Lock()

    @staticmethod
    def _existing_operation(
        session: Session, command: OperationCommand
    ) -> Operation | None:
        return session.scalar(
            select(Operation).where(
                Operation.scope == command.scope,
                Operation.idempotency_key == command.idempotency_key,
            )
        )

    def accept_coaching(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool = True,
    ) -> AcceptedContentOperation:
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing = self._existing_operation(session, command)
            if existing is not None:
                existing = self._operations.accept_in_session(session, command)
                return AcceptedContentOperation(existing, created=False)
            interview = session.get(Interview, interview_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if interview.report_id is None:
                raise InvalidStateError("报告尚未生成。", code="REPORT_NOT_READY")
            report = session.get(Report, interview.report_id)
            if report is None:
                raise InvalidStateError("面试引用的报告不存在。")
            if report.improvements_status in {"generating", "ready"}:
                operation = session.get(Operation, report.improvements_operation_id)
                if operation is None:
                    raise InvalidStateError("回答改写缺少原受理操作。")
                return AcceptedContentOperation(operation, created=False)
            if report.improvements_status == "failed":
                raise InvalidStateError("失败的回答改写必须通过原操作重试。")
            if report.revision != expected_revision:
                raise RevisionConflictError(
                    "报告版本已更新。", current_revision=report.revision
                )
            if not capacity_available:
                raise CapacityLimitedError()
            operation = self._operations.accept_in_session(session, command)
            report.improvements_status = "generating"
            report.active_operation_id = operation.id
            report.improvements_operation_id = operation.id
            report.revision += 1
            report.updated_at = utc_now_rfc3339()
            return AcceptedContentOperation(operation, created=True)

    def _load_coaching_context(self, operation_id: str) -> _CoachingContext:
        with Session(self._engine) as session:
            operation = session.get(Operation, operation_id)
            if operation is None or operation.kind != "report.coach":
                raise ResourceNotFoundError("回答改写操作不存在。")
            report = session.get(Report, operation.resource_id)
            if report is None:
                raise ResourceNotFoundError("报告不存在。")
            if report.improvements_status == "ready" and report.improved_answers:
                return _CoachingContext(
                    report_id=report.id,
                    operation_id=operation.id,
                    payload={},
                    original_answers={},
                )
            if (
                report.improvements_status != "generating"
                or report.active_operation_id != operation.id
            ):
                raise InvalidStateError("回答改写操作已过期或状态不一致。")
            interview = session.get(Interview, report.interview_id)
            if interview is None:
                raise InvalidStateError("报告关联的面试不存在。")
            snapshot = session.get(ProfileSnapshot, interview.profile_snapshot_id)
            if snapshot is None:
                raise InvalidStateError("面试资料快照不存在。")
            claims = self._claims_for_snapshot(session, snapshot)
            questions = list(
                session.scalars(
                    select(Question)
                    .where(Question.interview_id == interview.id)
                    .order_by(Question.order_index, Question.created_at, Question.id)
                )
            )
            questions_by_id = {question.id: question for question in questions}
            answers = list(
                session.scalars(
                    select(Answer)
                    .where(Answer.interview_id == interview.id)
                    .order_by(Answer.created_at, Answer.id)
                )
            )
            answers_by_root: dict[str, dict[str, str]] = {}
            original_answers: dict[str, list[dict[str, str]]] = {}
            for answer in answers:
                question = questions_by_id.get(answer.question_id)
                if question is None:
                    raise InvalidStateError("回答关联的问题不存在。")
                answers_by_root.setdefault(question.root_id, {})[answer.id] = (
                    answer.raw_text
                )
                original_answers.setdefault(question.root_id, []).append(
                    {
                        "answer_id": answer.id,
                        "question_id": answer.question_id,
                        "question_kind": question.kind,
                        "raw_text": answer.raw_text,
                    }
                )
            if not answers_by_root:
                raise InvalidStateError("本场没有可改写的已接受回答。")
            root_questions = {
                question.id: question.wording
                for question in questions
                if question.kind == "main" and question.id in answers_by_root
            }
            return _CoachingContext(
                report_id=report.id,
                operation_id=operation.id,
                payload={
                    "report_id": report.id,
                    "answers_by_root": answers_by_root,
                    "root_questions": root_questions,
                    "allowed_claims": claims,
                },
                original_answers=original_answers,
            )

    def _upstream_error(
        self, operation_id: str, message: str, *, timeout: bool = False
    ) -> UpstreamError:
        with Session(self._engine) as session:
            operation = session.get(Operation, operation_id)
            retryable = (
                operation is not None and operation.attempts < self._model_attempt_limit
            )
        return UpstreamError(message, timeout=timeout, retryable=retryable)

    async def process_coaching(self, *, operation_id: str) -> dict[str, Any]:
        context = self._load_coaching_context(operation_id)
        if not context.payload:
            with Session(self._engine) as session:
                report = session.get(Report, context.report_id)
                if report is None:
                    raise ResourceNotFoundError("报告不存在。")
                return {
                    "resource_revision": report.revision,
                    "report_id": report.id,
                    "improved_answer_count": len(report.improved_answers or []),
                }
        if self._generator is None:
            raise ServiceUnavailableError("内容生成模型尚未配置。")
        try:
            result = await run_grounded_content_workflow(
                generator=self._generator,
                task="coach_answers",
                payload=context.payload,
                timeout_seconds=self._workflow_timeout_seconds,
            )
        except TimeoutError as exc:
            raise self._upstream_error(
                operation_id, "回答改写超时。", timeout=True
            ) from exc
        except (
            ContentWorkflowError,
            GroundedContentValidationError,
            ModelRequestError,
        ) as exc:
            raise self._upstream_error(
                operation_id, "回答改写失败，原回答和评分未改变。"
            ) from exc

        items = []
        for item in result["candidate"]["items"]:
            items.append(
                {
                    **item,
                    "original_answers": context.original_answers[
                        item["root_question_id"]
                    ],
                }
            )
        with Session(self._engine) as session, session.begin():
            report = session.get(Report, context.report_id)
            if report is None:
                raise ResourceNotFoundError("报告不存在。")
            if report.improvements_status == "ready" and report.improved_answers:
                return {
                    "resource_revision": report.revision,
                    "report_id": report.id,
                    "improved_answer_count": len(report.improved_answers),
                }
            if report.active_operation_id != operation_id:
                raise InvalidStateError("回答改写操作已过期或状态不一致。")
            report.improved_answers = items
            report.improvements_status = "ready"
            report.active_operation_id = None
            report.revision += 1
            report.run_metadata = {
                **dict(report.run_metadata or {}),
                "content_generation": self._generation_metadata(result["usage"]),
            }
            report.updated_at = utc_now_rfc3339()
            self._operations.append_event_in_session(
                session,
                operation_id,
                "coaching.ready",
                {"report_id": report.id, "report_revision": report.revision},
            )
            return {
                "resource_revision": report.revision,
                "report_id": report.id,
                "improved_answer_count": len(items),
            }

    def accept_resume_draft(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        profile_snapshot_id: str,
        interview_id: str | None,
        jd_text: str | None,
        source_name: str | None,
        command_factory: Any,
        capacity_available: bool = True,
    ) -> AcceptedContentOperation:
        """Create one draft+operation atomically after resolving its private target."""

        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            profile = session.get(Profile, profile_id)
            if profile is None:
                raise ResourceNotFoundError("资料不存在。")
            if profile.status != "active":
                raise InvalidStateError("资料当前不可用。")
            snapshot = session.get(ProfileSnapshot, profile_snapshot_id)
            if snapshot is None or snapshot.profile_id != profile_id:
                raise InvalidStateError("资料快照不属于当前资料。")
            target_context, target_hash = self._resolve_target(
                session,
                snapshot=snapshot,
                interview_id=interview_id,
                jd_text=jd_text,
                source_name=source_name,
            )
            existing_draft = session.scalar(
                select(ResumeDraft).where(
                    ResumeDraft.profile_snapshot_id == snapshot.id,
                    ResumeDraft.target_hash == target_hash,
                )
            )
            if existing_draft is not None:
                operation = session.get(
                    Operation, existing_draft.generation_operation_id
                )
                if operation is None:
                    raise InvalidStateError("简历草稿缺少原受理操作。")
                return AcceptedContentOperation(operation, created=False)
            if profile.revision != expected_revision:
                raise RevisionConflictError(
                    "资料版本已更新。", current_revision=profile.revision
                )
            if not capacity_available:
                raise CapacityLimitedError()
            draft_id = new_id("resume")
            command = command_factory(draft_id, target_hash)
            existing_operation = self._existing_operation(session, command)
            if existing_operation is not None:
                existing_operation = self._operations.accept_in_session(
                    session, command
                )
                draft = session.get(ResumeDraft, existing_operation.resource_id)
                if draft is None:
                    raise InvalidStateError("幂等操作缺少简历草稿。")
                return AcceptedContentOperation(existing_operation, created=False)
            operation = self._operations.accept_in_session(session, command)
            session.add(
                ResumeDraft(
                    id=draft_id,
                    profile_id=profile_id,
                    profile_snapshot_id=snapshot.id,
                    interview_id=interview_id,
                    target_hash=target_hash,
                    revision=0,
                    status="generating",
                    sections=[],
                    source_claim_ids=[],
                    changes=[],
                    missing_facts=[],
                    cautions=[],
                    target_context=target_context,
                    active_operation_id=operation.id,
                    generation_operation_id=operation.id,
                    run_metadata={},
                )
            )
            return AcceptedContentOperation(operation, created=True)

    @staticmethod
    def _resolve_target(
        session: Session,
        *,
        snapshot: ProfileSnapshot,
        interview_id: str | None,
        jd_text: str | None,
        source_name: str | None,
    ) -> tuple[dict[str, Any], str]:
        if interview_id is not None and jd_text is not None:
            raise InvalidStateError("interview_id 与 jd_text 不能同时提供。")
        if interview_id is not None:
            interview = session.get(Interview, interview_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if interview.profile_snapshot_id != snapshot.id:
                raise InvalidStateError("面试与资料快照不一致。")
            raw_text = str((interview.jd_snapshot or {}).get("raw_text") or "")
            content_hash = str(
                (interview.jd_snapshot or {}).get("content_hash")
                or hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            )
            return (
                {
                    "kind": "interview",
                    "interview_id": interview.id,
                    "source_name": (interview.jd_snapshot or {}).get("source_name"),
                    "content_hash": content_hash,
                    "raw_text": raw_text,
                },
                content_hash,
            )
        if jd_text is not None:
            normalized = jd_text.strip()
            if not normalized:
                raise InvalidStateError("JD 文本不能为空。")
            content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            return (
                {
                    "kind": "jd_text",
                    "source_name": source_name or "USER_PROVIDED_JD",
                    "content_hash": content_hash,
                    "raw_text": normalized,
                },
                content_hash,
            )
        content_hash = hashlib.sha256(b"GENERIC_RESUME_TARGET").hexdigest()
        return (
            {
                "kind": "generic",
                "source_name": "NO_TARGET",
                "content_hash": content_hash,
                "raw_text": "",
            },
            content_hash,
        )

    @staticmethod
    def _claims_for_snapshot(
        session: Session, snapshot: ProfileSnapshot
    ) -> dict[str, str]:
        claim_ids = [str(value) for value in snapshot.confirmed_claim_ids or []]
        if not claim_ids:
            raise InvalidStateError("资料快照没有已确认事实。")
        rows = list(session.scalars(select(Claim).where(Claim.id.in_(claim_ids))))
        by_id = {claim.id: claim.text for claim in rows}
        if set(by_id) != set(claim_ids):
            raise InvalidStateError("资料快照引用的事实不存在。")
        return {claim_id: by_id[claim_id] for claim_id in claim_ids}

    def _load_resume_context(self, operation_id: str) -> _ResumeContext:
        with Session(self._engine) as session:
            operation = session.get(Operation, operation_id)
            if operation is None or operation.kind != "resume.compose":
                raise ResourceNotFoundError("简历生成操作不存在。")
            draft = session.get(ResumeDraft, operation.resource_id)
            if draft is None:
                raise ResourceNotFoundError("简历草稿不存在。")
            if draft.status in {"draft", "accepted"} and draft.sections:
                return _ResumeContext(draft.id, operation.id, {})
            if (
                draft.status != "generating"
                or draft.active_operation_id != operation.id
            ):
                raise InvalidStateError("简历生成操作已过期或状态不一致。")
            snapshot = session.get(ProfileSnapshot, draft.profile_snapshot_id)
            if snapshot is None:
                raise InvalidStateError("简历资料快照不存在。")
            claims = self._claims_for_snapshot(session, snapshot)
            return _ResumeContext(
                draft.id,
                operation.id,
                {
                    "draft_id": draft.id,
                    "allowed_claims": claims,
                    "target_context": dict(draft.target_context or {}),
                },
            )

    async def process_resume_draft(self, *, operation_id: str) -> dict[str, Any]:
        context = self._load_resume_context(operation_id)
        if not context.payload:
            with Session(self._engine) as session:
                draft = session.get(ResumeDraft, context.draft_id)
                if draft is None:
                    raise ResourceNotFoundError("简历草稿不存在。")
                return {
                    "resource_revision": draft.revision,
                    "resume_draft_id": draft.id,
                    "section_count": len(draft.sections or []),
                }
        if self._generator is None:
            raise ServiceUnavailableError("内容生成模型尚未配置。")
        try:
            result = await run_grounded_content_workflow(
                generator=self._generator,
                task="compose_resume",
                payload=context.payload,
                timeout_seconds=self._workflow_timeout_seconds,
            )
        except TimeoutError as exc:
            raise self._upstream_error(
                operation_id, "简历生成超时。", timeout=True
            ) from exc
        except (
            ContentWorkflowError,
            GroundedContentValidationError,
            ModelRequestError,
        ) as exc:
            raise self._upstream_error(
                operation_id, "简历生成失败，已确认事实未改变。"
            ) from exc

        candidate = result["candidate"]
        allowed_claims = context.payload["allowed_claims"]
        sections = [
            {
                "section_id": section["section_id"],
                "title": section["title"],
                "items": [
                    {
                        "item_id": item["item_id"],
                        "text": item["text"],
                        "claim_ids": list(item["claim_ids"]),
                    }
                    for item in section["items"]
                ],
            }
            for section in candidate["sections"]
        ]
        changes = [
            {
                "item_id": item["item_id"],
                "before": "；".join(
                    allowed_claims[claim_id] for claim_id in item["claim_ids"]
                ),
                "after": item["text"],
                "claim_ids": list(item["claim_ids"]),
                "reason": item["reason"],
            }
            for section in candidate["sections"]
            for item in section["items"]
        ]
        with Session(self._engine) as session, session.begin():
            draft = session.get(ResumeDraft, context.draft_id)
            if draft is None:
                raise ResourceNotFoundError("简历草稿不存在。")
            if draft.status in {"draft", "accepted"} and draft.sections:
                return {
                    "resource_revision": draft.revision,
                    "resume_draft_id": draft.id,
                    "section_count": len(draft.sections),
                }
            if draft.active_operation_id != operation_id:
                raise InvalidStateError("简历生成操作已过期或状态不一致。")
            draft.sections = sections
            draft.source_claim_ids = candidate["source_claim_ids"]
            draft.changes = changes
            draft.missing_facts = candidate["missing_facts"]
            draft.cautions = candidate["cautions"]
            draft.status = "draft"
            draft.active_operation_id = None
            draft.revision += 1
            draft.run_metadata = self._generation_metadata(result["usage"])
            draft.updated_at = utc_now_rfc3339()
            self._operations.append_event_in_session(
                session,
                operation_id,
                "resume_draft.ready",
                {
                    "resume_draft_id": draft.id,
                    "resume_draft_revision": draft.revision,
                },
            )
            return {
                "resource_revision": draft.revision,
                "resume_draft_id": draft.id,
                "section_count": len(draft.sections),
            }

    def get_resume_draft(self, draft_id: str) -> dict[str, Any]:
        with Session(self._engine) as session:
            draft = session.get(ResumeDraft, draft_id)
            if draft is None:
                raise ResourceNotFoundError("简历草稿不存在。")
            claims = []
            claim_ids = [str(value) for value in draft.source_claim_ids or []]
            if claim_ids:
                rows = list(
                    session.scalars(select(Claim).where(Claim.id.in_(claim_ids)))
                )
                by_id = {claim.id: claim for claim in rows}
                if set(by_id) != set(claim_ids):
                    raise InvalidStateError("简历草稿引用的事实不存在。")
                claims = [
                    {"id": claim_id, "text": by_id[claim_id].text}
                    for claim_id in claim_ids
                ]
            return {
                "id": draft.id,
                "revision": draft.revision,
                "profile_id": draft.profile_id,
                "profile_snapshot_id": draft.profile_snapshot_id,
                "interview_id": draft.interview_id,
                "status": draft.status,
                "sections": list(draft.sections or []),
                "source_claims": claims,
                "source_claim_ids": claim_ids,
                "changes": list(draft.changes or []),
                "missing_facts": list(draft.missing_facts or []),
                "cautions": list(draft.cautions or []),
                "target_context": _public_target_context(
                    dict(draft.target_context or {})
                ),
                "active_operation_id": draft.active_operation_id,
                "run_metadata": dict(draft.run_metadata or {}),
            }

    def accept_draft(self, draft_id: str, *, expected_revision: int) -> dict[str, Any]:
        with Session(self._engine) as session, session.begin():
            draft = session.get(ResumeDraft, draft_id)
            if draft is None:
                raise ResourceNotFoundError("简历草稿不存在。")
            if draft.revision != expected_revision:
                raise RevisionConflictError(
                    "简历版本已更新。", current_revision=draft.revision
                )
            if draft.status == "accepted":
                return self.get_resume_draft(draft_id)
            if draft.status != "draft":
                raise InvalidStateError("只有生成完成的草稿可以确认。")
            draft.status = "accepted"
            draft.revision += 1
            draft.updated_at = utc_now_rfc3339()
        return self.get_resume_draft(draft_id)

    def accept_retry(
        self,
        operation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_input: dict[str, Any],
        capacity_available: bool = True,
    ) -> AcceptedContentOperation:
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            original = session.get(Operation, operation_id)
            if original is None:
                raise ResourceNotFoundError("原操作不存在。")
            if original.kind not in {"report.coach", "resume.compose"}:
                raise InvalidStateError("该操作不属于内容生成链路。")
            retry_scope = f"{original.scope}#retry_of_{original.id}"
            existing = session.scalar(
                select(Operation).where(
                    Operation.scope == retry_scope,
                    Operation.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                existing = self._operations.retry_in_session(
                    session,
                    original,
                    max_attempts=self._model_attempt_limit,
                    idempotency_key=idempotency_key,
                    request_input=request_input,
                )
                return AcceptedContentOperation(existing, created=False)
            if not bool((original.error or {}).get("retryable")):
                raise InvalidStateError("原操作不可重试。")
            if not capacity_available:
                raise CapacityLimitedError()
            if original.kind == "report.coach":
                resource: Report | ResumeDraft | None = session.get(
                    Report, original.resource_id
                )
                failed_status = "failed"
            else:
                resource = session.get(ResumeDraft, original.resource_id)
                failed_status = "generation_failed"
            if resource is None:
                raise ResourceNotFoundError("生成资源不存在。")
            if resource.revision != expected_revision:
                raise RevisionConflictError(
                    "资源版本已更新。", current_revision=resource.revision
                )
            current_status = (
                resource.improvements_status
                if isinstance(resource, Report)
                else resource.status
            )
            if current_status != failed_status or resource.active_operation_id:
                raise InvalidStateError("当前生成状态不可重试。")
            try:
                operation = self._operations.retry_in_session(
                    session,
                    original,
                    max_attempts=self._model_attempt_limit,
                    idempotency_key=idempotency_key,
                    request_input=request_input,
                )
            except ValueError as exc:
                raise InvalidStateError(str(exc)) from exc
            if isinstance(resource, Report):
                resource.improvements_status = "generating"
            else:
                resource.status = "generating"
            resource.active_operation_id = operation.id
            resource.revision += 1
            resource.updated_at = utc_now_rfc3339()
            return AcceptedContentOperation(operation, created=True)

    async def process_operation(self, operation: Operation) -> dict[str, Any]:
        if operation.kind == "report.coach":
            return await self.process_coaching(operation_id=operation.id)
        if operation.kind == "resume.compose":
            return await self.process_resume_draft(operation_id=operation.id)
        raise InvalidStateError("不支持的内容生成操作。")

    def release_failed_operation(self, operation_id: str) -> None:
        with Session(self._engine) as session, session.begin():
            operation = session.get(Operation, operation_id)
            if operation is None:
                return
            if operation.kind == "report.coach":
                report = session.get(Report, operation.resource_id)
                if report is not None and report.active_operation_id == operation_id:
                    report.improvements_status = "failed"
                    report.active_operation_id = None
                    report.revision += 1
                    report.updated_at = utc_now_rfc3339()
            elif operation.kind == "resume.compose":
                draft = session.get(ResumeDraft, operation.resource_id)
                if draft is not None and draft.active_operation_id == operation_id:
                    draft.status = "generation_failed"
                    draft.active_operation_id = None
                    draft.revision += 1
                    draft.updated_at = utc_now_rfc3339()

    def recover_interrupted_operations(self, operation_ids: list[str]) -> None:
        for operation_id in operation_ids:
            self.release_failed_operation(operation_id)

    def _generation_metadata(self, usage: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_mode": self._run_mode,
            "workflow": "openjiuwen",
            "workflow_version": "1.0.0",
            "prompt_version": "m4-02.1",
            "generator": dict(self._generator_metadata),
            "usage": dict(usage),
        }
