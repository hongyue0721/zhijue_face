"""M4 deterministic scoring: frozen rubric, abstention, conflict, and totals."""

from __future__ import annotations

from zhijue.domain.scoring import aggregate_report, score_root


def _rubric(*criteria: tuple[str, float]) -> dict[str, object]:
    return {
        "rubric": [
            {
                "criterion_id": criterion_id,
                "kind": "technical",
                "weight": weight,
            }
            for criterion_id, weight in criteria
        ]
    }


def _result(
    criterion_id: str,
    *,
    finding: str,
    level: int | None,
    answer_id: str,
    weight: float = 1,
) -> dict[str, object]:
    return {
        "criterion_id": criterion_id,
        "kind": "technical",
        "weight": weight,
        "level": level,
        "finding": finding,
        "answer_quotes": (
            []
            if finding in {"missing", "not_assessable"}
            else [{"answer_id": answer_id, "exact_quote": f"quote-{answer_id}"}]
        ),
        "knowledge_refs": [] if finding == "not_assessable" else ["reviewed_ref"],
        "explanation": f"explanation-{answer_id}",
    }


def test_followup_merges_each_criterion_once_without_averaging_turns():
    assessment = score_root(
        root_question_id="question_root",
        rubric_snapshot=_rubric(("criterion_a", 2), ("criterion_b", 1)),
        observations=[
            {
                "criteria": [
                    _result(
                        "criterion_a",
                        finding="missing",
                        level=0,
                        answer_id="answer_main",
                        weight=2,
                    ),
                    _result(
                        "criterion_b",
                        finding="not_assessable",
                        level=None,
                        answer_id="answer_main",
                    ),
                ]
            },
            {
                "criteria": [
                    _result(
                        "criterion_a",
                        finding="supported",
                        level=3,
                        answer_id="answer_probe",
                        weight=2,
                    ),
                    _result(
                        "criterion_b",
                        finding="supported",
                        level=0,
                        answer_id="answer_probe",
                    ),
                ]
            },
        ],
        answer_ids=["answer_main", "answer_probe"],
    )

    assert assessment["status"] == "scored"
    assert assessment["coverage"] == 1.0
    assert assessment["score"] == 67
    assert assessment["answer_ids"] == ["answer_main", "answer_probe"]
    assert len(assessment["criterion_results"]) == 2
    assert assessment["criterion_results"][0]["finding"] == "supported"
    assert assessment["criterion_results"][0]["level"] == 3


def test_sixty_percent_coverage_scores_but_lower_coverage_abstains():
    rubric = _rubric(("criterion_a", 3), ("criterion_b", 2))
    at_threshold = score_root(
        root_question_id="question_threshold",
        rubric_snapshot=rubric,
        observations=[
            {
                "criteria": [
                    _result(
                        "criterion_a",
                        finding="supported",
                        level=2,
                        answer_id="answer_a",
                        weight=3,
                    ),
                    _result(
                        "criterion_b",
                        finding="not_assessable",
                        level=None,
                        answer_id="answer_a",
                        weight=2,
                    ),
                ]
            }
        ],
        answer_ids=["answer_a"],
    )
    below_threshold = score_root(
        root_question_id="question_below",
        rubric_snapshot=rubric,
        observations=[
            {
                "criteria": [
                    _result(
                        "criterion_a",
                        finding="not_assessable",
                        level=None,
                        answer_id="answer_b",
                        weight=3,
                    ),
                    _result(
                        "criterion_b",
                        finding="supported",
                        level=3,
                        answer_id="answer_b",
                        weight=2,
                    ),
                ]
            }
        ],
        answer_ids=["answer_b"],
    )

    assert at_threshold["coverage"] == 0.6
    assert at_threshold["score"] == 67
    assert at_threshold["status"] == "scored"
    assert below_threshold["coverage"] == 0.4
    assert below_threshold["score"] is None
    assert below_threshold["status"] == "insufficient"


def test_conflicting_supported_and_contradicted_evidence_is_not_scored():
    assessment = score_root(
        root_question_id="question_conflict",
        rubric_snapshot=_rubric(("criterion_a", 1)),
        observations=[
            {
                "criteria": [
                    _result(
                        "criterion_a",
                        finding="supported",
                        level=3,
                        answer_id="answer_main",
                    )
                ]
            },
            {
                "criteria": [
                    _result(
                        "criterion_a",
                        finding="contradicted",
                        level=0,
                        answer_id="answer_probe",
                    )
                ]
            },
        ],
        answer_ids=["answer_main", "answer_probe"],
    )

    assert assessment["status"] == "disputed"
    assert assessment["score"] is None
    assert assessment["coverage"] == 0.0
    assert assessment["criterion_results"][0]["finding"] == "disputed"
    assert assessment["criterion_results"][0]["level"] is None
    assert len(assessment["criterion_results"][0]["answer_quotes"]) == 2


def test_skipped_and_unmeasured_roots_remain_null_instead_of_zero():
    rubric = _rubric(("criterion_a", 1))
    skipped = score_root(
        root_question_id="question_skipped",
        rubric_snapshot=rubric,
        observations=[],
        answer_ids=[],
        skipped=True,
    )
    unmeasured = score_root(
        root_question_id="question_unmeasured",
        rubric_snapshot=rubric,
        observations=[],
        answer_ids=["answer_failed"],
    )

    assert (skipped["status"], skipped["score"], skipped["coverage"]) == (
        "skipped",
        None,
        0.0,
    )
    assert (unmeasured["status"], unmeasured["score"]) == ("unmeasured", None)


def test_overall_requires_three_scores_and_uses_half_up_rounding():
    assessments = [
        {"status": "scored", "score": 50},
        {"status": "scored", "score": 50},
        {"status": "scored", "score": 51},
        {"status": "scored", "score": 51},
        {"status": "skipped", "score": None},
    ]
    overall, coverage = aggregate_report(
        assessments,
        planned_root_count=5,
        asked_root_count=5,
        answered_root_count=4,
        skipped_question_count=1,
    )

    assert overall == 51
    assert coverage == {
        "planned_root_count": 5,
        "asked_root_count": 5,
        "answered_root_count": 4,
        "scored_root_count": 4,
        "insufficient_root_count": 0,
        "disputed_root_count": 0,
        "skipped_root_count": 1,
        "unmeasured_root_count": 0,
        "skipped_question_count": 1,
        "overall_eligible": True,
    }

    overall, coverage = aggregate_report(
        assessments[:2],
        planned_root_count=5,
        asked_root_count=2,
        answered_root_count=2,
        skipped_question_count=0,
    )
    assert overall is None
    assert coverage["overall_eligible"] is False
