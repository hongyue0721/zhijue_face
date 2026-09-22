"""Current-policy retry decisions for persisted interview failures."""

from types import SimpleNamespace

from zhijue.application.interviews import InterviewService


def _service(*, attempt_limit: int) -> InterviewService:
    service = object.__new__(InterviewService)
    service._model_attempt_limit = attempt_limit
    return service


def _operation(
    *,
    kind: str = "interview.answer",
    attempts: int = 1,
    retryable: bool = False,
    code: str = "UPSTREAM_FAILED",
) -> SimpleNamespace:
    return SimpleNamespace(
        status="failed",
        kind=kind,
        attempts=attempts,
        error={"code": code, "retryable": retryable},
    )


def test_raised_budget_reopens_saved_answer_upstream_failure() -> None:
    service = _service(attempt_limit=3)

    assert service.can_retry_operation(_operation()) is True


def test_attempt_limit_still_closes_retry_and_unrelated_kinds_stay_closed() -> None:
    service = _service(attempt_limit=1)

    assert service.can_retry_operation(_operation()) is False
    assert (
        service.can_retry_operation(_operation(kind="interview.plan", retryable=True))
        is False
    )


def test_non_upstream_nonretryable_answer_failure_does_not_reopen() -> None:
    service = _service(attempt_limit=3)

    assert service.can_retry_operation(_operation(code="INVALID_STATE")) is False
