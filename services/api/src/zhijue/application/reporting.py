"""M4 report persistence over frozen questions and validated observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import (
    Answer,
    Assessment,
    Decision,
    Interview,
    Observation,
    OperationEvent,
    Question,
    Report,
)
from zhijue.adapters.db.operations import OperationRepository
from zhijue.domain.errors import InvalidStateError, ResourceNotFoundError
from zhijue.domain.ids import new_id
from zhijue.domain.scoring import SCORING_VERSION, aggregate_report, score_root


@dataclass(frozen=True)
class _ReportInputs:
    roots: list[Question]
    questions_by_id: dict[str, Question]
    answers: list[Answer]
    observations: list[Observation]
    decisions: list[Decision]


def _load_inputs(session: Session, interview_id: str) -> _ReportInputs:
    questions = list(
        session.scalars(
            select(Question)
            .where(Question.interview_id == interview_id)
            .order_by(Question.order_index, Question.created_at, Question.id)
        )
    )
    roots = [question for question in questions if question.kind == "main"]
    if not roots:
        raise InvalidStateError("面试没有可汇总的根问题。")
    root_ids = [root.id for root in roots]
    return _ReportInputs(
        roots=roots,
        questions_by_id={question.id: question for question in questions},
        answers=list(
            session.scalars(
                select(Answer)
                .where(Answer.interview_id == interview_id)
                .order_by(Answer.created_at, Answer.id)
            )
        ),
        observations=list(
            session.scalars(
                select(Observation)
                .where(Observation.root_question_id.in_(root_ids))
                .order_by(Observation.created_at, Observation.id)
            )
        ),
        decisions=list(
            session.scalars(
                select(Decision)
                .where(Decision.root_question_id.in_(root_ids))
                .order_by(Decision.created_at, Decision.id)
            )
        ),
    )


def _control_decisions(inputs: _ReportInputs) -> list[Decision]:
    return [
        decision
        for decision in inputs.decisions
        if isinstance(decision.target, dict)
        and bool(decision.target.get("control_operation_id"))
    ]


def _score_roots(
    inputs: _ReportInputs,
) -> tuple[list[dict[str, Any]], int, int, int, bool]:
    answers_by_root: dict[str, list[str]] = {root.id: [] for root in inputs.roots}
    for answer in inputs.answers:
        question = inputs.questions_by_id.get(answer.question_id)
        if question is not None:
            answers_by_root[question.root_id].append(answer.id)

    observations_by_root: dict[str, list[dict[str, Any]]] = {
        root.id: [] for root in inputs.roots
    }
    for observation in inputs.observations:
        observations_by_root[observation.root_question_id].append(
            {"criteria": list(observation.criteria or [])}
        )

    controls = _control_decisions(inputs)
    skipped_roots = {
        decision.root_question_id
        for decision in controls
        if decision.reason_code == "SKIPPED"
        and (decision.target or {}).get("question_kind") == "main"
    }
    asked_roots = {
        root_id for root_id, answer_ids in answers_by_root.items() if answer_ids
    } | {decision.root_question_id for decision in controls}
    assessments = []
    for root in inputs.roots:
        payload = score_root(
            root_question_id=root.id,
            rubric_snapshot=dict(root.rubric_snapshot or {}),
            observations=observations_by_root[root.id],
            answer_ids=answers_by_root[root.id],
            skipped=root.id in skipped_roots,
        )
        assessments.append({"id": new_id("assessment"), **payload})
    explicit_end = any(
        decision.reason_code == "USER_REQUESTED_END" for decision in controls
    )
    return (
        assessments,
        len(asked_roots),
        sum(bool(ids) for ids in answers_by_root.values()),
        sum(decision.reason_code == "SKIPPED" for decision in controls),
        explicit_end,
    )


def _limitations(
    interview: Interview,
    *,
    completion: str,
    overall_score: int | None,
    assessments: list[dict[str, Any]],
) -> list[Any]:
    limitations = list(interview.limitations or [])
    if completion == "incomplete":
        limitations.append("本场存在跳过、提前结束或未形成有效观察的根题。")
    if overall_score is None:
        limitations.append("少于三根题形成有效分数，未生成总分。")
    if any(item["status"] == "disputed" for item in assessments):
        limitations.append("存在相互冲突的回答证据，相关根题未计分。")
    if any(item["status"] == "insufficient" for item in assessments):
        limitations.append("部分根题的可评分 Rubric 覆盖率低于 60%。")
    deduplicated: list[Any] = []
    for limitation in limitations:
        if limitation not in deduplicated:
            deduplicated.append(limitation)
    return deduplicated


def _run_metadata(interview: Interview) -> dict[str, Any]:
    return {
        "run_mode": interview.run_mode,
        "seed_bank_version": interview.seed_bank_version,
        "rubric_version": interview.rubric_version,
        "prompt_versions": dict(interview.prompt_versions or {}),
        "policy_version": interview.policy_version,
        "model_fingerprint": interview.model_fingerprint or None,
        "sdk_version": interview.sdk_version or None,
        "scoring_version": SCORING_VERSION,
    }


def report_view(report: Report) -> dict[str, Any]:
    return {
        "id": report.id,
        "revision": report.revision,
        "interview_id": report.interview_id,
        "completion": report.completion,
        "overall_score": report.overall_score,
        "coverage": dict(report.coverage or {}),
        "root_assessments": list(report.root_assessments or []),
        "improvements_status": report.improvements_status,
        "active_operation_id": report.active_operation_id,
        "improved_answers": list(report.improved_answers or []),
        "limitations": list(report.limitations or []),
        "run_metadata": dict(report.run_metadata or {}),
    }


class ReportingService:
    def __init__(self, *, engine: Engine, operations: OperationRepository) -> None:
        self._engine = engine
        self._operations = operations

    def create_in_session(
        self,
        session: Session,
        *,
        interview: Interview,
        operation_id: str,
    ) -> Report:
        if interview.report_id is not None:
            existing = session.get(Report, interview.report_id)
            if existing is None:
                raise InvalidStateError("面试引用的报告不存在。")
            event_exists = session.scalar(
                select(OperationEvent.event_type).where(
                    OperationEvent.operation_id == operation_id,
                    OperationEvent.event_type == "report.ready",
                )
            )
            if event_exists is None:
                self._operations.append_event_in_session(
                    session,
                    operation_id,
                    "report.ready",
                    {
                        "report_id": existing.id,
                        "interview_revision": interview.revision,
                    },
                )
            return existing

        inputs = _load_inputs(session, interview.id)
        assessments, asked, answered, skipped_questions, explicit_end = _score_roots(
            inputs
        )
        overall_score, coverage = aggregate_report(
            assessments,
            planned_root_count=len(inputs.roots),
            asked_root_count=asked,
            answered_root_count=answered,
            skipped_question_count=skipped_questions,
        )
        observed_roots = {item.root_question_id for item in inputs.observations}
        completion = (
            "complete"
            if len(observed_roots) == len(inputs.roots)
            and skipped_questions == 0
            and not explicit_end
            else "incomplete"
        )
        report = Report(
            id=new_id("report"),
            interview_id=interview.id,
            revision=0,
            completion=completion,
            overall_score=overall_score,
            coverage=coverage,
            root_assessments=assessments,
            improvements_status="not_requested",
            active_operation_id=None,
            improvements_operation_id=None,
            improved_answers=[],
            limitations=_limitations(
                interview,
                completion=completion,
                overall_score=overall_score,
                assessments=assessments,
            ),
            run_metadata=_run_metadata(interview),
        )
        session.add_all(
            [
                Assessment(
                    id=item["id"],
                    interview_id=interview.id,
                    root_question_id=item["root_question_id"],
                    criterion_results=item["criterion_results"],
                    score=item["score"],
                    coverage=item["coverage"],
                    status=item["status"],
                )
                for item in assessments
            ]
            + [report]
        )
        interview.report_id = report.id
        interview.status = "completed"
        interview.current_question_id = None
        interview.active_operation_id = None
        interview.revision += 1
        self._operations.append_event_in_session(
            session,
            operation_id,
            "report.ready",
            {"report_id": report.id, "interview_revision": interview.revision},
        )
        return report

    def get_view(self, interview_id: str) -> dict[str, Any]:
        with Session(self._engine) as session:
            interview = session.get(Interview, interview_id)
            if interview is None:
                raise ResourceNotFoundError("面试不存在。")
            if interview.report_id is None:
                raise InvalidStateError(
                    "报告尚未生成。",
                    code="REPORT_NOT_READY",
                )
            report = session.get(Report, interview.report_id)
            if report is None:
                raise InvalidStateError("面试引用的报告不存在。")
            return report_view(report)
