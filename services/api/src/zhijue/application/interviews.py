"""Interview planning plus the M3 bounded answer workflow.

The service owns the single SQLite write path for Interview, Question, Answer,
validated Observation, program Decision, and their durable operation events.
Model output is never committed before schema and semantic validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import (
    Answer,
    Decision,
    Interview,
    Observation,
    Operation,
    Profile,
    ProfileSnapshot,
    Question,
    utc_now_rfc3339,
)
from zhijue.adapters.db.operations import (
    IdempotencyConflict,
    OperationCommand,
    OperationRepository,
)
from zhijue.adapters.db.profiles import ProfileRepository
from zhijue.application.answer_workflow import (
    AnswerAnalyzer,
    AnswerWorkflowError,
    ModelRequestError,
    ModelRequestTimeoutError,
    run_handle_answer_workflow,
)
from zhijue.application.reporting import ReportingService
from zhijue.application.requisition import JDPlanningError, JDPlanningService
from zhijue.application.seed_bank import SeedBank
from zhijue.domain.errors import (
    CapacityLimitedError,
    DomainError,
    InvalidStateError,
    ResourceNotFoundError,
    RevisionConflictError,
    ServiceUnavailableError,
    UpstreamError,
)
from zhijue.domain.ids import new_id
from zhijue.domain.interview_policy import ObservationValidationError
from zhijue.domain.planning import InterviewSlot, SlotReason
from zhijue.domain.questions import instantiate_root_questions
from zhijue.domain.requisition import CoverageStatus, JDSourceType

# 这些失败都发生在回答已经持久化之后，重新运行只会消费同一份回答。
# 历史 Operation 可能是在更小的模型预算下失败并写入 retryable=false；
# 当负责人随后明确提高预算时，应按当前策略重新判断，而不是永久锁死恢复入口。
_RECOVERABLE_ANSWER_FAILURE_CODES = frozenset({"UPSTREAM_FAILED", "UPSTREAM_TIMEOUT"})


class InterviewPreparationFailed(DomainError):
    """面试准备失败；HTTP/operation 层据此落 failed，不产生 ready 假象。"""

    def __init__(self, code_or_msg: str, message: str = "") -> None:
        if message:
            code = code_or_msg
            msg = message
        elif ": " in code_or_msg:
            code, msg = code_or_msg.split(": ", 1)
        else:
            code = "INVALID_REQUEST"
            msg = code_or_msg
        status_code = (
            404
            if code == "RESOURCE_NOT_FOUND"
            else (
                409
                if code
                in (
                    "PROFILE_NOT_ACTIVE",
                    "REVISION_CONFLICT",
                    "PROFILE_UNCONFIRMED",
                )
                else 400
            )
        )
        super().__init__(msg, code=code, status_code=status_code)


@dataclass(frozen=True)
class AcceptedInterviewOperation:
    operation: Operation
    created: bool
    answer_id: str | None = None


@dataclass(frozen=True)
class _AnswerRunContext:
    interview_id: str
    answer_id: str
    question_id: str
    root_question_id: str
    question_text: str
    answer_text: str
    rubric_snapshot: dict[str, Any]
    competency_id: str
    followup_count: int
    remaining_root_ids: tuple[str, ...]
    allowed_followup_intents: tuple[str, ...]
    reference_material: Any
    existing_result: dict[str, Any] | None


def _slot_from_payload(payload: dict[str, Any]) -> InterviewSlot:
    return InterviewSlot(
        slot_id=payload["slot_id"],
        competency=payload["competency"],
        jd_requirement_ids=tuple(payload["jd_requirement_ids"]),
        candidate_evidence_ids=tuple(payload["candidate_evidence_ids"]),
        current_verification_status=CoverageStatus(
            payload["current_verification_status"]
        ),
        verification_goal=payload["verification_goal"],
        priority=int(payload["priority"]),
        difficulty=payload["difficulty"],
        reason_code=SlotReason(payload["reason_code"]),
        structured_reason=payload["structured_reason"],
        seed_id=payload.get("seed_id"),
    )


class InterviewService:
    def __init__(
        self,
        *,
        engine: Engine,
        planner: JDPlanningService,
        operations: OperationRepository,
        seed_bank: SeedBank,
        reporting: ReportingService,
        analyzer: AnswerAnalyzer | None,
        workflow_timeout_seconds: float = 60,
        model_attempt_limit: int = 3,
    ) -> None:
        self._engine = engine
        self._planner = planner
        self._operations = operations
        self._seed_bank = seed_bank
        self._reporting = reporting
        self._analyzer = analyzer
        self._workflow_timeout_seconds = workflow_timeout_seconds
        if (
            isinstance(model_attempt_limit, bool)
            or not isinstance(model_attempt_limit, int)
            or not 1 <= model_attempt_limit <= 3
        ):
            raise ValueError("model_attempt_limit must be an integer from 1 to 3")
        self._model_attempt_limit = model_attempt_limit
        self._acceptance_lock = Lock()

    def _require_plannable_snapshot(
        self, session: Session, profile_id: str, expected_revision: int
    ) -> ProfileSnapshot:
        profile = session.get(Profile, profile_id)
        if profile is None:
            raise ResourceNotFoundError("资料不存在。")
        if profile.status != "active":
            raise InvalidStateError("资料不在可用状态。")
        if profile.revision != expected_revision:
            raise RevisionConflictError(
                "资料版本已更新。", current_revision=profile.revision
            )
        snapshot = session.scalar(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.profile_id == profile_id)
            .order_by(ProfileSnapshot.revision.desc())
            .limit(1)
        )
        if snapshot is None:
            raise InterviewPreparationFailed("PROFILE_UNCONFIRMED: 需先确认资料")
        return ProfileRepository.require_ready_snapshot(session, snapshot.id)

    def accept_plan(
        self,
        *,
        profile_id: str,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedInterviewOperation:
        with (
            self._acceptance_lock,
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing = self._existing_operation(session, command)
            if existing is not None:
                return AcceptedInterviewOperation(existing, created=False)
            self._require_plannable_snapshot(session, profile_id, expected_revision)
            if not capacity_available:
                raise CapacityLimitedError()
            operation = self._operations.accept_in_session(session, command)
            return AcceptedInterviewOperation(operation, created=True)

    def create_plan(
        self,
        *,
        interview_id: str,
        profile_id: str,
        expected_revision: int,
        jd_text: str,
        jd_source_name: str,
        jd_source_type: JDSourceType,
        seed_bank_version: str,
        run_mode: str,
    ) -> dict[str, Any]:
        with Session(self._engine, expire_on_commit=False) as session:
            snapshot = self._require_plannable_snapshot(
                session, profile_id, expected_revision
            )

        try:
            jd = self._planner.import_jd(
                profile_id=profile_id,
                raw_text=jd_text,
                source_name=jd_source_name,
                source_type=jd_source_type,
            )
            direct_ev, related_ctx, rel_map = self._planner.evidence_indices(
                profile_id=profile_id
            )
            result = self._planner.plan(
                snapshot=jd,
                evidence_index=direct_ev,
                profile_snapshot_id=snapshot.id,
                seed_bank_version=seed_bank_version,
                related_context_index=related_ctx,
                relation_index=rel_map,
            )
        except JDPlanningError as exc:
            raise InterviewPreparationFailed(str(exc)) from exc
        except ValueError as exc:
            raise InterviewPreparationFailed(str(exc)) from exc

        root_plan = result.plan.as_dict()
        root_plan["jd_snapshot"] = {
            "id": jd.id,
            "source_type": jd.source_type.value,
            "source_name": jd.source_name,
            "content_hash": jd.content_hash,
            "imported_at": jd.imported_at,
            "version": jd.version,
            "status": jd.status.value,
            "is_synthetic": jd.is_synthetic,
            "derived": jd.derived,
            "source_url": jd.source_url,
            "upstream_source_name": jd.upstream_source_name,
            "upstream_url": jd.upstream_url,
            "upstream_retrieved_at": jd.upstream_retrieved_at,
            "upstream_content_hash": jd.upstream_content_hash,
            "derived_artifact_path": jd.derived_artifact_path,
            "derived_content_hash": jd.derived_content_hash,
            "transformation_note": jd.transformation_note,
            # 原文随快照保留，保证"JD 来源与原文可恢复"（负责人决策 §5）。
            "raw_text": jd.raw_text,
        }
        root_plan["requirements"] = [
            {
                "id": r.id,
                "tier": r.tier.value,
                "competency_id": r.competency_id,
                "importance": r.importance,
                "statement": r.statement,
                "source_span": r.source_span,
                "extraction": r.extraction,
            }
            for r in result.requirements
        ]
        root_plan["coverage_map"] = [
            {
                "competency_id": e.competency_id,
                "status": e.status.value,
                "requirement_ids": list(e.requirement_ids),
                "evidence_ids": list(e.evidence_ids),
                "relation": e.relation.value,
                "related_context_ids": list(e.related_context_ids),
                "is_weakness": e.is_weakness,
                "note": e.note,
            }
            for e in result.coverage.entries
        ]
        root_plan["profile_snapshot_id"] = snapshot.id

        with Session(self._engine) as session, session.begin():
            self._require_plannable_snapshot(session, profile_id, expected_revision)
            interview = Interview(
                id=interview_id,
                profile_snapshot_id=snapshot.id,
                jd_snapshot=root_plan["jd_snapshot"],
                seed_bank_version=seed_bank_version,
                rubric_version="0.0.0",  # 尚无题目，故无 rubric
                prompt_versions={},
                policy_version="1.0.0",
                model_fingerprint="",
                sdk_version="",
                run_mode=run_mode,
                revision=0,
                status="ready",  # 计划已生成；题目与答题属 M3
                root_plan=root_plan,
                current_question_id=None,
                active_operation_id=None,
                stop_requested=False,
                report_id=None,
                limitations=list(result.plan.limitations),
                created_at=utc_now_rfc3339(),
                updated_at=utc_now_rfc3339(),
            )
            session.add(interview)

        return {
            "resource_revision": 0,
            "interview_id": interview_id,
            "profile_snapshot_id": snapshot.id,
            "slot_count": len(result.plan.slots),
            "competencies": list(result.plan.competency_coverage()),
            "seed_bank_version": seed_bank_version,
        }

    def _existing_operation(
        self, session: Session, command: OperationCommand
    ) -> Operation | None:
        existing = session.scalar(
            select(Operation).where(
                Operation.scope == command.scope,
                Operation.idempotency_key == command.idempotency_key,
            )
        )
        if existing is None:
            return None
        # Repository performs the canonical input-hash comparison.
        return self._operations.accept_in_session(session, command)

    def accept_start(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool = True,
    ) -> AcceptedInterviewOperation:
        with self._acceptance_lock:
            return self._accept_start_once(
                interview_id,
                expected_revision=expected_revision,
                command=command,
                capacity_available=capacity_available,
            )

    def _accept_start_once(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool = True,
    ) -> AcceptedInterviewOperation:
        with (
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing = self._existing_operation(session, command)
            if existing is not None:
                return AcceptedInterviewOperation(existing, created=False)
            interview = session.get(Interview, interview_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if not capacity_available:
                raise CapacityLimitedError()
            if interview.revision != expected_revision:
                raise RevisionConflictError(
                    "面试版本已更新。",
                    current_revision=interview.revision,
                )
            if interview.status != "ready":
                raise InvalidStateError("只有 ready 面试可以开始。")
            ProfileRepository.require_ready_snapshot(
                session, interview.profile_snapshot_id
            )
            if interview.active_operation_id is not None:
                raise InvalidStateError(
                    "面试已有进行中的操作。",
                    code="OPERATION_IN_PROGRESS",
                )
            operation = self._operations.accept_in_session(session, command)
            interview.active_operation_id = operation.id
            interview.revision += 1
            interview.updated_at = utc_now_rfc3339()
            return AcceptedInterviewOperation(operation, created=True)

    def start_interview(
        self, *, interview_id: str, operation_id: str
    ) -> dict[str, Any]:
        with Session(self._engine) as session, session.begin():
            interview = session.get(Interview, interview_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if (
                interview.status != "ready"
                or interview.active_operation_id != operation_id
            ):
                raise InvalidStateError("面试开始操作已过期或状态不一致。")
            ProfileRepository.require_ready_snapshot(
                session, interview.profile_snapshot_id
            )

            plan = dict(interview.root_plan or {})
            slots = tuple(
                _slot_from_payload(payload) for payload in plan.get("slots", [])
            )
            if not slots:
                raise InvalidStateError("面试计划没有可实例化的题目。")
            drafts = instantiate_root_questions(
                slots,
                self._seed_bank,
                interview_id=interview.id,
            )
            for draft in drafts:
                session.add(
                    Question(
                        id=draft.id,
                        interview_id=interview.id,
                        root_id=draft.root_id,
                        kind=draft.kind,
                        seed_id=draft.seed_id,
                        wording=draft.wording,
                        basis=draft.basis,
                        rubric_snapshot=draft.rubric_snapshot,
                        order_index=draft.order_index,
                    )
                )
            plan["slots"] = [
                {**payload, "seed_id": draft.seed_id}
                for payload, draft in zip(plan["slots"], drafts)
            ]
            interview.root_plan = plan
            interview.rubric_version = "1.0.0"
            interview.status = "active"
            interview.current_question_id = drafts[0].id
            interview.active_operation_id = None
            interview.revision += 1
            interview.updated_at = utc_now_rfc3339()
            self._operations.append_event_in_session(
                session,
                operation_id,
                "question.ready",
                {
                    "question_id": drafts[0].id,
                    "interview_revision": interview.revision,
                },
            )
            return {
                "resource_revision": interview.revision,
                "interview_id": interview.id,
                "question_id": drafts[0].id,
                "question_count": len(drafts),
            }

    def accept_answer(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        question_id: str,
        client_turn_id: str,
        answer_text: str,
        command: OperationCommand,
        capacity_available: bool = True,
    ) -> AcceptedInterviewOperation:
        with self._acceptance_lock:
            return self._accept_answer_once(
                interview_id,
                expected_revision=expected_revision,
                question_id=question_id,
                client_turn_id=client_turn_id,
                answer_text=answer_text,
                command=command,
                capacity_available=capacity_available,
            )

    def _accept_answer_once(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        question_id: str,
        client_turn_id: str,
        answer_text: str,
        command: OperationCommand,
        capacity_available: bool = True,
    ) -> AcceptedInterviewOperation:
        if not answer_text.strip():
            raise DomainError("回答不能为空。", code="INVALID_REQUEST")
        with (
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            existing_operation = self._existing_operation(session, command)
            if existing_operation is not None:
                answer = session.scalar(
                    select(Answer).where(
                        Answer.accepted_operation_id == existing_operation.id
                    )
                )
                if answer is None:
                    raise InvalidStateError("幂等操作缺少已受理回答。")
                return AcceptedInterviewOperation(
                    existing_operation, created=False, answer_id=answer.id
                )

            existing_answer = session.scalar(
                select(Answer).where(
                    Answer.interview_id == interview_id,
                    Answer.client_turn_id == client_turn_id,
                )
            )
            if existing_answer is not None:
                if (
                    existing_answer.question_id != question_id
                    or existing_answer.raw_text != answer_text
                ):
                    raise IdempotencyConflict(client_turn_id)
                operation = session.get(
                    Operation, existing_answer.accepted_operation_id
                )
                if operation is None:
                    raise InvalidStateError("已保存回答缺少原受理操作。")
                return AcceptedInterviewOperation(
                    operation, created=False, answer_id=existing_answer.id
                )

            interview = session.get(Interview, interview_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if not capacity_available:
                raise CapacityLimitedError()
            if interview.revision != expected_revision:
                raise RevisionConflictError(
                    "面试版本已更新。",
                    current_revision=interview.revision,
                )
            if interview.status != "active":
                raise InvalidStateError("当前面试不接受回答。")
            if interview.stop_requested:
                raise InvalidStateError("面试已请求结束，不再接受新回答。")
            if interview.active_operation_id is not None:
                raise InvalidStateError(
                    "面试已有进行中的操作。",
                    code="OPERATION_IN_PROGRESS",
                )
            if interview.current_question_id != question_id:
                raise InvalidStateError("只能回答服务端当前问题。")
            question = session.get(Question, question_id)
            if question is None or question.interview_id != interview_id:
                raise ResourceNotFoundError("当前问题不存在。")

            operation = self._operations.accept_in_session(session, command)
            answer = Answer(
                id=new_id("answer"),
                question_id=question_id,
                interview_id=interview_id,
                client_turn_id=client_turn_id,
                accepted_operation_id=operation.id,
                raw_text=answer_text,
                evaluation_status="processing",
                assistance="none",
            )
            session.add(answer)
            interview.active_operation_id = operation.id
            interview.revision += 1
            interview.updated_at = utc_now_rfc3339()
            session.flush()
            return AcceptedInterviewOperation(
                operation, created=True, answer_id=answer.id
            )

    @staticmethod
    def _answer_for_operation(session: Session, operation: Operation) -> Answer | None:
        current: Operation | None = operation
        visited: set[str] = set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            answer = session.scalar(
                select(Answer).where(Answer.accepted_operation_id == current.id)
            )
            if answer is not None:
                return answer
            current = (
                session.get(Operation, current.parent_operation_id)
                if current.parent_operation_id
                else None
            )
        return None

    @staticmethod
    def _failed_retry_tail(session: Session, answer: Answer) -> str | None:
        """沿 parent 链找到该回答失败链的链尾 operation。

        retry clone 通过 parent_operation_id 指向上一节点；链尾的 attempts
        才是累计预算真值，只有从链尾重试才不会被 `retry budget exhausted`
        误拒或分叉绕过预算。created_at 为 RFC3339，字符串序即时间序。
        """
        current = session.get(Operation, answer.accepted_operation_id)
        if current is None:
            return None
        visited: set[str] = {current.id}
        while True:
            child = session.scalar(
                select(Operation)
                .where(Operation.parent_operation_id == current.id)
                .order_by(Operation.created_at.desc(), Operation.id.desc())
                .limit(1)
            )
            if child is None or child.id in visited:
                return current.id
            visited.add(child.id)
            current = child

    @staticmethod
    def _existing_answer_result(
        session: Session,
        *,
        answer: Answer,
        interview: Interview,
    ) -> dict[str, Any] | None:
        observation = session.scalar(
            select(Observation)
            .where(Observation.answer_id == answer.id)
            .order_by(Observation.created_at.desc())
        )
        if observation is None:
            return None
        decision = session.scalar(
            select(Decision).where(Decision.observation_id == observation.id)
        )
        if decision is None:
            return None
        return {
            "resource_revision": interview.revision,
            "answer_id": answer.id,
            "observation_id": observation.id,
            "decision_id": decision.id,
            "action": decision.action,
            "question_id": interview.current_question_id,
            "usage": None,
            "report_id": interview.report_id,
        }

    def _load_answer_context(self, operation_id: str) -> _AnswerRunContext:
        with Session(self._engine) as session:
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise ResourceNotFoundError("回答操作不存在。")
            answer = self._answer_for_operation(session, operation)
            if answer is None:
                raise InvalidStateError("回答操作缺少已受理回答。")
            interview = session.get(Interview, answer.interview_id)
            question = session.get(Question, answer.question_id)
            if interview is None or question is None:
                raise InvalidStateError("回答关联的面试或问题不存在。")
            existing = self._existing_answer_result(
                session, answer=answer, interview=interview
            )
            root = session.get(Question, question.root_id)
            if root is None or root.kind != "main":
                raise InvalidStateError("回答关联的根问题不存在。")
            if existing is None and interview.active_operation_id != operation.id:
                raise InvalidStateError("回答操作已过期或状态不一致。")

            remaining_roots = tuple(
                session.scalars(
                    select(Question.id)
                    .where(
                        Question.interview_id == interview.id,
                        Question.kind == "main",
                        Question.order_index > root.order_index,
                    )
                    .order_by(Question.order_index, Question.id)
                )
            )
            followup_count = len(
                tuple(
                    session.scalars(
                        select(Question.id).where(
                            Question.interview_id == interview.id,
                            Question.root_id == root.id,
                            Question.kind != "main",
                        )
                    )
                )
            )
            rubric = dict(root.rubric_snapshot or {})
            competency_id = str(
                rubric.get("competency_id")
                or (root.basis or {}).get("competency")
                or ""
            )
            if not competency_id:
                raise InvalidStateError("根问题缺少能力项快照。")
            return _AnswerRunContext(
                interview_id=interview.id,
                answer_id=answer.id,
                question_id=question.id,
                root_question_id=root.id,
                question_text=question.wording,
                answer_text=answer.raw_text,
                rubric_snapshot=rubric,
                competency_id=competency_id,
                followup_count=followup_count,
                remaining_root_ids=remaining_roots,
                allowed_followup_intents=tuple(rubric.get("followup_intents") or ()),
                reference_material=rubric.get("reference_points"),
                existing_result=existing,
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

    async def process_answer(self, *, operation_id: str) -> dict[str, Any]:
        context = self._load_answer_context(operation_id)
        if context.existing_result is not None:
            return self._complete_natural_end(
                operation_id=operation_id,
                result=context.existing_result,
            )
        if self._analyzer is None:
            raise ServiceUnavailableError("回答分析模型尚未配置。")

        try:
            result = await run_handle_answer_workflow(
                analyzer=self._analyzer,
                observation_id=new_id("observation"),
                answer_id=context.answer_id,
                question_id=context.question_id,
                root_question_id=context.root_question_id,
                question_text=context.question_text,
                answer_text=context.answer_text,
                rubric_snapshot=context.rubric_snapshot,
                competency_id=context.competency_id,
                followup_count=context.followup_count,
                remaining_roots=len(context.remaining_root_ids),
                allowed_followup_intents=context.allowed_followup_intents,
                decision_id=new_id("decision"),
                reference_material=context.reference_material,
                timeout_seconds=self._workflow_timeout_seconds,
            )
        except TimeoutError as exc:
            raise self._upstream_error(
                operation_id, "回答分析超时。", timeout=True
            ) from exc
        except ModelRequestTimeoutError as exc:
            raise self._upstream_error(
                operation_id, "回答分析模型请求超时。", timeout=True
            ) from exc
        except (
            AnswerWorkflowError,
            ModelRequestError,
            ObservationValidationError,
        ) as exc:
            raise self._upstream_error(
                operation_id, "回答分析失败，原始回答已保留。"
            ) from exc
        committed = self._commit_answer_result(
            operation_id=operation_id,
            context=context,
            observation=result["observation"],
            decision=result["decision"],
            usage=result["usage"],
        )
        return self._complete_natural_end(
            operation_id=operation_id,
            result=committed,
        )

    @staticmethod
    def _followup_wording(
        intent: str,
        rubric_snapshot: dict[str, Any],
        criterion_id: str | None,
    ) -> str:
        generic = {
            "clarification": "请只澄清刚才回答中指代不清或与题目不一致的部分。",
            "detail": "请只补充刚才回答中尚未说明的关键实现细节。",
            "ownership": "请只说明这项工作中你本人负责的部分和实际动作。",
            "counterfactual": "如果关键条件发生变化，你会如何调整刚才的方案？",
            "pushback": "请只回应刚才方案中最关键的反例或限制条件。",
            "reflection": "请只说明这次经历中可验证的复盘结论。",
        }
        if criterion_id is None:
            return generic.get(intent, generic["detail"])

        criterion = next(
            (
                item
                for item in rubric_snapshot.get("rubric", ())
                if item.get("criterion_id") == criterion_id
            ),
            None,
        )
        target = (criterion or {}).get("levels", {}).get("2")
        if not isinstance(target, str) or not target.strip():
            return generic.get(intent, generic["detail"])

        focus = target.strip().rstrip("。")
        prefix = {
            "detail": "请针对刚才未覆盖的关键点补充",
            "ownership": "请结合你本人的实际动作补充",
            "counterfactual": "如果关键条件发生变化，请围绕这个关键点说明调整",
            "pushback": "请回应这个关键点在反例或限制条件下是否仍成立",
            "reflection": "请围绕这个关键点说明可验证的复盘",
        }.get(intent, "请针对刚才未覆盖的关键点补充")
        return f"{prefix}：{focus}。"

    def _complete_natural_end(
        self,
        *,
        operation_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if result["action"] != "END":
            return result
        with Session(self._engine) as session, session.begin():
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise ResourceNotFoundError("回答操作不存在。")
            interview = session.get(Interview, operation.resource_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if interview.stop_requested:
                return result
            report = self._reporting.create_in_session(
                session,
                interview=interview,
                operation_id=operation_id,
            )
            return {
                **result,
                "resource_revision": interview.revision,
                "question_id": None,
                "report_id": report.id,
            }

    def _commit_answer_result(
        self,
        *,
        operation_id: str,
        context: _AnswerRunContext,
        observation: dict[str, Any],
        decision: dict[str, Any],
        usage: dict[str, Any],
    ) -> dict[str, Any]:
        with Session(self._engine) as session, session.begin():
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise ResourceNotFoundError("回答操作不存在。")
            answer = self._answer_for_operation(session, operation)
            interview = session.get(Interview, context.interview_id)
            if answer is None or interview is None:
                raise InvalidStateError("回答操作关联数据不存在。")
            existing = self._existing_answer_result(
                session, answer=answer, interview=interview
            )
            if existing is not None:
                return existing
            if interview.active_operation_id != operation_id:
                raise InvalidStateError("回答操作已过期或状态不一致。")

            session.add(
                Observation(
                    id=observation["id"],
                    answer_id=observation["answer_id"],
                    question_id=observation["question_id"],
                    root_question_id=observation["root_question_id"],
                    relevance=observation["relevance"],
                    knowledge_status=observation["knowledge_status"],
                    criteria=observation["criteria"],
                    clarification_needed=observation["clarification_needed"],
                    validation_flags=observation["validation_flags"],
                )
            )
            session.flush()
            target = decision.get("target")
            session.add(
                Decision(
                    id=decision["id"],
                    observation_id=decision["observation_id"],
                    root_question_id=decision["root_question_id"],
                    action=decision["action"],
                    reason_code=decision["reason_code"],
                    reason_summary=decision["reason_summary"],
                    target=target,
                    policy_version=decision["policy_version"],
                )
            )

            next_question_id: str | None = None
            if interview.stop_requested:
                interview.status = "finishing"
            elif decision["action"] in {"CLARIFY", "PROBE"}:
                intent = str((target or {}).get("followup_intent") or "detail")
                root = session.get(Question, context.root_question_id)
                if root is None:
                    raise InvalidStateError("根问题不存在。")
                followup = Question(
                    id=new_id("question"),
                    interview_id=interview.id,
                    root_id=root.id,
                    kind=(
                        "clarification" if decision["action"] == "CLARIFY" else "probe"
                    ),
                    seed_id=root.seed_id,
                    wording=self._followup_wording(
                        intent,
                        context.rubric_snapshot,
                        (target or {}).get("criterion_id"),
                    ),
                    basis={
                        **dict(root.basis or {}),
                        "followup_intent": intent,
                        "decision_id": decision["id"],
                    },
                    rubric_snapshot=dict(root.rubric_snapshot or {}),
                    order_index=root.order_index,
                )
                session.add(followup)
                next_question_id = followup.id
            elif decision["action"] == "NEXT":
                if not context.remaining_root_ids:
                    raise InvalidStateError("策略要求继续，但没有剩余主问题。")
                next_question_id = context.remaining_root_ids[0]
            else:
                interview.status = "finishing"

            answer.evaluation_status = "evaluated"
            interview.current_question_id = next_question_id
            interview.active_operation_id = None
            interview.revision += 1
            interview.updated_at = utc_now_rfc3339()
            self._operations.append_event_in_session(
                session,
                operation_id,
                "policy.decided",
                {
                    "action": decision["action"],
                    "reason_code": decision["reason_code"],
                    "root_question_id": decision["root_question_id"],
                    "followup_intent": (
                        (target or {}).get("followup_intent")
                        if target is not None
                        else None
                    ),
                },
            )
            if next_question_id is not None:
                self._operations.append_event_in_session(
                    session,
                    operation_id,
                    "question.ready",
                    {
                        "question_id": next_question_id,
                        "interview_revision": interview.revision,
                    },
                )
            return {
                "resource_revision": interview.revision,
                "answer_id": answer.id,
                "observation_id": observation["id"],
                "decision_id": decision["id"],
                "action": decision["action"],
                "question_id": next_question_id,
                "usage": usage,
                "report_id": interview.report_id,
            }

    def accept_control(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        action: str,
        command: OperationCommand,
        capacity_available: bool = True,
    ) -> AcceptedInterviewOperation:
        with self._acceptance_lock:
            return self._accept_control_once(
                interview_id,
                expected_revision=expected_revision,
                action=action,
                command=command,
                capacity_available=capacity_available,
            )

    def _accept_control_once(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        action: str,
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedInterviewOperation:
        if action not in {"skip", "end"}:
            raise DomainError("未知面试控制动作。", code="INVALID_REQUEST")
        with (
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            if action == "end":
                existing_end = session.scalar(
                    select(Operation)
                    .where(
                        Operation.resource_id == interview_id,
                        Operation.kind == "interview.control.end",
                    )
                    .order_by(Operation.created_at, Operation.id)
                )
                if existing_end is not None:
                    return AcceptedInterviewOperation(existing_end, created=False)
            existing = self._existing_operation(session, command)
            if existing is not None:
                return AcceptedInterviewOperation(existing, created=False)
            interview = session.get(Interview, interview_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if not capacity_available:
                raise CapacityLimitedError()
            if interview.revision != expected_revision:
                raise RevisionConflictError(
                    "面试版本已更新。",
                    current_revision=interview.revision,
                )
            if interview.status not in {"active", "finishing", "finish_failed"}:
                raise InvalidStateError("当前面试不接受控制操作。")
            if action == "skip" and interview.active_operation_id is not None:
                raise InvalidStateError(
                    "面试已有进行中的操作。",
                    code="OPERATION_IN_PROGRESS",
                )
            question = (
                session.get(Question, interview.current_question_id)
                if interview.current_question_id is not None
                else None
            )
            if action == "skip" and question is None:
                raise InvalidStateError("当前没有可跳过的问题。")
            if question is None:
                question = session.scalar(
                    select(Question)
                    .where(
                        Question.interview_id == interview.id,
                        Question.kind == "main",
                    )
                    .order_by(Question.order_index.desc(), Question.id.desc())
                    .limit(1)
                )
            if question is None:
                raise InvalidStateError("面试没有可关联的根问题。")
            root = session.get(Question, question.root_id)
            if root is None:
                raise InvalidStateError("控制操作关联的根问题不存在。")
            remaining = tuple(
                session.scalars(
                    select(Question.id)
                    .where(
                        Question.interview_id == interview.id,
                        Question.kind == "main",
                        Question.order_index > root.order_index,
                    )
                    .order_by(Question.order_index, Question.id)
                )
            )
            operation = self._operations.accept_in_session(session, command)
            decision_action = "END" if action == "end" or not remaining else "NEXT"
            reason_code = "USER_REQUESTED_END" if action == "end" else "SKIPPED"
            session.add(
                Decision(
                    id=new_id("decision"),
                    observation_id=None,
                    root_question_id=root.id,
                    action=decision_action,
                    reason_code=reason_code,
                    reason_summary=(
                        "用户明确请求结束面试。"
                        if action == "end"
                        else "用户跳过当前问题，不据此推断能力。"
                    ),
                    target={
                        "control_operation_id": operation.id,
                        "question_id": question.id,
                        "question_kind": question.kind,
                    },
                    policy_version=interview.policy_version,
                )
            )
            if action == "end":
                interview.stop_requested = True
                interview.status = "finishing"
                if interview.active_operation_id is None:
                    interview.active_operation_id = operation.id
            else:
                interview.active_operation_id = operation.id
            interview.revision += 1
            interview.updated_at = utc_now_rfc3339()
            return AcceptedInterviewOperation(operation, created=True)

    @staticmethod
    def _control_decision_for_operation(
        session: Session, operation: Operation
    ) -> Decision:
        operation_ids: set[str] = set()
        current: Operation | None = operation
        while current is not None and current.id not in operation_ids:
            operation_ids.add(current.id)
            current = (
                session.get(Operation, current.parent_operation_id)
                if current.parent_operation_id
                else None
            )
        decisions = session.scalars(
            select(Decision)
            .where(Decision.reason_code.in_({"SKIPPED", "USER_REQUESTED_END"}))
            .order_by(Decision.created_at, Decision.id)
        )
        for decision in decisions:
            target = decision.target or {}
            if target.get("control_operation_id") in operation_ids:
                return decision
        raise InvalidStateError("控制操作缺少持久化决策。")

    def process_control(self, *, operation_id: str) -> dict[str, Any]:
        with Session(self._engine) as session, session.begin():
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise ResourceNotFoundError("控制操作不存在。")
            interview = session.get(Interview, operation.resource_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            decision = self._control_decision_for_operation(session, operation)
            self._operations.append_event_in_session(
                session,
                operation_id,
                "policy.decided",
                {
                    "action": decision.action,
                    "reason_code": decision.reason_code,
                    "root_question_id": decision.root_question_id,
                    "followup_intent": None,
                },
            )
            if decision.action == "NEXT":
                root = session.get(Question, decision.root_question_id)
                if root is None:
                    raise InvalidStateError("跳过操作关联的根问题不存在。")
                next_question_id = session.scalar(
                    select(Question.id)
                    .where(
                        Question.interview_id == interview.id,
                        Question.kind == "main",
                        Question.order_index > root.order_index,
                    )
                    .order_by(Question.order_index, Question.id)
                    .limit(1)
                )
                if next_question_id is None:
                    raise InvalidStateError("跳过操作缺少下一根问题。")
                interview.status = "active"
                interview.current_question_id = next_question_id
                interview.active_operation_id = None
                interview.revision += 1
                interview.updated_at = utc_now_rfc3339()
                self._operations.append_event_in_session(
                    session,
                    operation_id,
                    "question.ready",
                    {
                        "question_id": next_question_id,
                        "interview_revision": interview.revision,
                    },
                )
                return {
                    "resource_revision": interview.revision,
                    "decision_id": decision.id,
                    "action": decision.action,
                    "question_id": next_question_id,
                    "report_id": None,
                }

            report = self._reporting.create_in_session(
                session,
                interview=interview,
                operation_id=operation_id,
            )
            return {
                "resource_revision": interview.revision,
                "decision_id": decision.id,
                "action": decision.action,
                "question_id": None,
                "report_id": report.id,
            }

    def accept_retry(
        self,
        operation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_input: dict[str, Any],
        capacity_available: bool = True,
    ) -> AcceptedInterviewOperation:
        with self._acceptance_lock:
            return self._accept_retry_once(
                operation_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                request_input=request_input,
                capacity_available=capacity_available,
            )

    def can_retry_operation(self, operation: Operation) -> bool:
        """Return current actionability, including a deliberately raised budget.

        Operation.error records the decision made when the failure happened.  The
        read/retry boundary must additionally honor the *current* bounded policy so
        an earlier one-attempt run can be recovered after the configured budget is
        raised, without making unrelated business failures retryable.
        """
        if operation.status not in {"failed", "interrupted"}:
            return False
        if operation.kind == "interview.answer":
            max_attempts = self._model_attempt_limit
        elif operation.kind in {"interview.control.skip", "interview.control.end"}:
            max_attempts = 3
        else:
            return False
        if operation.attempts >= max_attempts:
            return False
        error = operation.error or {}
        if bool(error.get("retryable")):
            return True
        return (
            operation.kind == "interview.answer"
            and str(error.get("code")) in _RECOVERABLE_ANSWER_FAILURE_CODES
        )

    def _accept_retry_once(
        self,
        operation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_input: dict[str, Any],
        capacity_available: bool = True,
    ) -> AcceptedInterviewOperation:
        supported_kinds = {
            "interview.answer",
            "interview.control.skip",
            "interview.control.end",
        }
        with (
            Session(self._engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            original = session.get(Operation, operation_id)
            if original is None:
                raise ResourceNotFoundError("原操作不存在。")
            if original.kind not in supported_kinds:
                raise InvalidStateError("该操作不支持面试运行时重试。")
            max_attempts = (
                self._model_attempt_limit if original.kind == "interview.answer" else 3
            )
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
                    max_attempts=max_attempts,
                    idempotency_key=idempotency_key,
                    request_input=request_input,
                )
                answer = self._answer_for_operation(session, operation)
                return AcceptedInterviewOperation(
                    operation,
                    created=False,
                    answer_id=answer.id if answer is not None else None,
                )
            if not capacity_available:
                raise CapacityLimitedError()
            answer = self._answer_for_operation(session, original)
            interview = session.get(
                Interview,
                answer.interview_id if answer is not None else original.resource_id,
            )
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if interview.revision != expected_revision:
                raise RevisionConflictError(
                    "面试版本已更新。",
                    current_revision=interview.revision,
                )
            if interview.active_operation_id is not None:
                raise InvalidStateError(
                    "面试已有进行中的操作。",
                    code="OPERATION_IN_PROGRESS",
                )
            if not self.can_retry_operation(original):
                raise InvalidStateError("原操作不可重试。")
            try:
                operation = self._operations.retry_in_session(
                    session,
                    original,
                    max_attempts=max_attempts,
                    idempotency_key=idempotency_key,
                    request_input=request_input,
                )
            except ValueError as exc:
                raise InvalidStateError(str(exc)) from exc

            state_changed = False
            if answer is not None and answer.evaluation_status != "evaluated":
                answer.evaluation_status = "processing"
                interview.active_operation_id = operation.id
                state_changed = True
            elif answer is not None and interview.status == "finish_failed":
                interview.status = "finishing"
                interview.active_operation_id = operation.id
                state_changed = True
            elif original.kind.startswith("interview.control."):
                interview.active_operation_id = operation.id
                if original.kind == "interview.control.end":
                    interview.stop_requested = True
                    interview.status = "finishing"
                state_changed = True
            if state_changed:
                interview.revision += 1
                interview.updated_at = utc_now_rfc3339()
            return AcceptedInterviewOperation(
                operation,
                created=True,
                answer_id=answer.id if answer is not None else None,
            )

    def release_failed_operation(self, operation_id: str) -> None:
        with Session(self._engine) as session, session.begin():
            operation = session.get(Operation, operation_id)
            if operation is None:
                return
            interview = session.get(Interview, operation.resource_id)
            answer = self._answer_for_operation(session, operation)
            if answer is not None and answer.evaluation_status == "processing":
                answer.evaluation_status = "failed"
            if interview is None:
                return
            changed = False
            if interview.status == "finishing" and interview.report_id is None:
                interview.status = "finish_failed"
                changed = True
            if interview.active_operation_id == operation_id:
                interview.active_operation_id = None
                changed = True
            if changed:
                interview.revision += 1
                interview.updated_at = utc_now_rfc3339()

    def recover_interrupted_operations(self, _operation_ids: list[str]) -> None:
        # Scan persisted links, not only operations interrupted in this startup.
        # A previous failure may have reached Operation.failed while its best-effort
        # resource cleanup lost a SQLite write race; that terminal pointer must not
        # block the interview forever after the next restart.
        with Session(self._engine) as session, session.begin():
            interviews = list(
                session.scalars(
                    select(Interview).where(Interview.active_operation_id.is_not(None))
                )
            )
            for interview in interviews:
                operation = session.get(Operation, interview.active_operation_id)
                if operation is not None and operation.status in {
                    "queued",
                    "running",
                }:
                    continue
                answer = (
                    self._answer_for_operation(session, operation)
                    if operation is not None
                    else None
                )
                if answer is not None and answer.evaluation_status == "processing":
                    answer.evaluation_status = "failed"
                changed = False
                if interview.status == "finishing" and interview.report_id is None:
                    interview.status = "finish_failed"
                    changed = True
                if interview.active_operation_id is not None:
                    interview.active_operation_id = None
                    changed = True
                if changed:
                    interview.revision += 1
                    interview.updated_at = utc_now_rfc3339()

    def get_view(self, interview_id: str) -> dict[str, Any] | None:
        with Session(self._engine, expire_on_commit=False) as session:
            interview = session.get(Interview, interview_id)
            if interview is None:
                return None
            snapshot = session.get(ProfileSnapshot, interview.profile_snapshot_id)
            if snapshot is None:
                raise InvalidStateError("面试资料快照不存在。")
            plan = dict(interview.root_plan or {})
            jd = dict(interview.jd_snapshot or {})
            current_question = None
            if (
                interview.current_question_id is not None
                and not interview.stop_requested
            ):
                question = session.get(Question, interview.current_question_id)
                if question is not None:
                    answer = session.scalar(
                        select(Answer).where(Answer.question_id == question.id)
                    )
                    current_question = {
                        "id": question.id,
                        "root_id": question.root_id,
                        "kind": question.kind,
                        "seed_id": question.seed_id,
                        "wording": question.wording,
                        "basis": dict(question.basis or {}),
                        "order_index": question.order_index,
                        "accepted_answer": (
                            {
                                "id": answer.id,
                                "client_turn_id": answer.client_turn_id,
                                "raw_text": answer.raw_text,
                                "evaluation_status": answer.evaluation_status,
                                # failed 时暴露失败链尾 operation 作为恢复键
                                # （api.md §6）：链尾 attempts 是累计预算真值，
                                # 从中间节点重试会分叉绕过预算。
                                "retry_operation_id": (
                                    self._failed_retry_tail(session, answer)
                                    if answer.evaluation_status == "failed"
                                    else None
                                ),
                            }
                            if answer is not None
                            else None
                        ),
                    }
            root_ids = list(
                session.scalars(
                    select(Question.id).where(
                        Question.interview_id == interview.id,
                        Question.kind == "main",
                    )
                )
            )
            decisions = (
                list(
                    session.scalars(
                        select(Decision)
                        .where(Decision.root_question_id.in_(root_ids))
                        .order_by(Decision.created_at, Decision.id)
                    )
                )
                if root_ids
                else []
            )
            root_results = [
                {
                    "root_question_id": decision.root_question_id,
                    "observation_id": decision.observation_id,
                    "action": decision.action,
                    "reason_code": decision.reason_code,
                    "reason_summary": decision.reason_summary,
                    "target": decision.target,
                }
                for decision in decisions
            ]
            # 不返回 JD 全文以外的私密内容；JD 本身是用户输入，可以回给本人。
            return {
                "id": interview.id,
                "revision": interview.revision,
                "status": interview.status,
                "run_mode": interview.run_mode,
                "profile_id": snapshot.profile_id,
                "profile_snapshot_id": interview.profile_snapshot_id,
                "jd_requirements": plan.get("requirements", []),
                "jd_text": jd.get("raw_text"),
                "jd_source": {
                    key: jd.get(key)
                    for key in (
                        "id",
                        "source_type",
                        "source_name",
                        "content_hash",
                        "imported_at",
                        "version",
                        "status",
                        "is_synthetic",
                        "source_url",
                        "retrieved_at",
                        "derived",
                        "upstream_source_name",
                        "upstream_url",
                        "upstream_retrieved_at",
                        "upstream_content_hash",
                        "derived_artifact_path",
                        "derived_content_hash",
                        "transformation_note",
                    )
                },
                "root_plan": {
                    "slots": plan.get("slots", []),
                    "planner_version": plan.get("planner_version"),
                    "seed_bank_version": plan.get("seed_bank_version"),
                },
                "coverage_map": plan.get("coverage_map", []),
                "current_question": current_question,
                "root_results": root_results,
                "active_operation_id": interview.active_operation_id,
                "stop_requested": interview.stop_requested,
                "report_id": interview.report_id,
                "limitations": list(interview.limitations or []),
            }
