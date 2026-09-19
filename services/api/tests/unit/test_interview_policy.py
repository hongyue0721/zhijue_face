"""M3-01 Observation validation and deterministic interview Policy tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from zhijue.domain.interview_policy import (
    POLICY_VERSION,
    ObservationValidationError,
    decide_next,
    validate_observation,
)

ANSWER_ID = "answer_policy_01"
OBSERVATION_ID = "observation_policy_01"
QUESTION_ID = "question_policy_01"
ROOT_ID = "question_policy_root_01"
ANSWER_TEXT = "我会先确认队列深度，再设置发送超时。个人负责采集任务。"
COMPETENCY_ID = "embedded.rtos.queue"

RUBRIC_SNAPSHOT = {
    "schema_version": "1.0.0",
    "source": "approved_seed",
    "seed_id": "seed_queue",
    "seed_version": "1.0.0",
    "competency_id": COMPETENCY_ID,
    "rubric": [
        {
            "criterion_id": "criterion_queue",
            "kind": "technical",
            "weight": 3,
            "levels": {"0": "未回答", "1": "模糊", "2": "基本", "3": "完整"},
        },
        {
            "criterion_id": "criterion_ownership",
            "kind": "expression",
            "weight": 1,
            "levels": {"0": "未回答", "1": "模糊", "2": "基本", "3": "完整"},
        },
    ],
    "reference_ids": ["freertos_reviewed_v10"],
    "reference_points": [],
    "follow_up_strategy": {"max_followups": 1},
    "followup_intents": ["detail", "counterfactual"],
    "out_of_scope": [],
}


def _criterion(
    criterion_id: str,
    *,
    kind: str,
    weight: int,
    finding: str = "supported",
    level: int | None = 2,
    quote: str | None = None,
    refs: list[str] | None = None,
) -> dict[str, object]:
    if quote is None:
        quote = (
            "我会先确认队列深度"
            if criterion_id == "criterion_queue"
            else "个人负责采集任务"
        )
    return {
        "criterion_id": criterion_id,
        "kind": kind,
        "weight": weight,
        "level": level,
        "finding": finding,
        "answer_quotes": (
            []
            if finding in {"missing", "not_assessable"}
            else [{"answer_id": ANSWER_ID, "exact_quote": quote}]
        ),
        "knowledge_refs": (
            ["freertos_reviewed_v10"]
            if refs is None and kind == "technical"
            else refs or []
        ),
        "explanation": "只描述本轮回答证据，不作范围外推断。",
    }


def _raw_observation() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "id": OBSERVATION_ID,
        "answer_id": ANSWER_ID,
        "question_id": QUESTION_ID,
        "root_question_id": ROOT_ID,
        "relevance": "relevant",
        "knowledge_status": "adequate",
        "criteria": [
            _criterion("criterion_queue", kind="technical", weight=3),
            _criterion("criterion_ownership", kind="expression", weight=1),
        ],
        "clarification_needed": False,
        "validation_flags": [],
    }


def _validated(raw: dict[str, object] | None = None) -> dict[str, object]:
    return validate_observation(
        _raw_observation() if raw is None else raw,
        observation_id=OBSERVATION_ID,
        answer_id=ANSWER_ID,
        question_id=QUESTION_ID,
        root_question_id=ROOT_ID,
        answer_text=ANSWER_TEXT,
        rubric_snapshot=RUBRIC_SNAPSHOT,
    )


def _decide(
    observation: dict[str, object],
    *,
    followup_count: int = 0,
    remaining_roots: int = 1,
    intents: tuple[str, ...] = ("detail", "counterfactual"),
) -> dict[str, object]:
    decision = decide_next(
        observation=observation,
        competency_id=COMPETENCY_ID,
        followup_count=followup_count,
        remaining_roots=remaining_roots,
        allowed_followup_intents=intents,
        decision_id="decision_policy_01",
    )
    root = Path(__file__).resolve().parents[4]
    schema = json.loads(
        (root / "contracts" / "policy-decision.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(decision)
    assert decision["policy_version"] == POLICY_VERSION
    return decision


def _replace_criterion(
    raw: dict[str, object], criterion_id: str, **changes: object
) -> None:
    criterion = next(
        item for item in raw["criteria"] if item["criterion_id"] == criterion_id
    )
    criterion.update(changes)


# T11: a vague but relevant answer gets exactly one bounded probe, not a false claim.
def test_t11_vague_relevant_answer_probes_most_important_missing_criterion():
    raw = _raw_observation()
    _replace_criterion(
        raw,
        "criterion_queue",
        finding="missing",
        level=1,
        answer_quotes=[],
        knowledge_refs=[],
    )
    _replace_criterion(
        raw,
        "criterion_ownership",
        finding="missing",
        level=1,
        answer_quotes=[],
    )

    decision = _decide(_validated(raw))

    assert decision["action"] == "PROBE"
    assert decision["reason_code"] == "MISSING_REQUIRED_DETAIL"
    assert decision["target"] == {
        "competency_id": COMPETENCY_ID,
        "criterion_id": "criterion_queue",
        "followup_intent": "detail",
    }


# T12: adequate evidence does not trigger a performative follow-up.
def test_t12_adequate_answer_advances_without_forced_probe():
    decision = _decide(_validated())

    assert decision["action"] == "NEXT"
    assert decision["reason_code"] == "ADEQUATE_EVIDENCE"
    assert decision["target"] is None


# T13: off-topic or unresolved reference is clarified before any assessment probe.
@pytest.mark.parametrize("relevance", ["ambiguous", "off_topic"])
def test_t13_ambiguous_or_off_topic_answer_is_clarified(relevance):
    raw = _raw_observation()
    raw["relevance"] = relevance
    _replace_criterion(
        raw,
        "criterion_queue",
        finding="missing",
        level=0,
        answer_quotes=[],
        knowledge_refs=[],
    )

    decision = _decide(_validated(raw))

    assert decision["action"] == "CLARIFY"
    assert decision["reason_code"] == "AMBIGUOUS_ANSWER"
    assert decision["target"]["followup_intent"] == "clarification"


# T14: the one-followup budget precedes ambiguity and missing-detail rules.
def test_t14_followup_limit_stops_even_when_another_probe_looks_useful():
    raw = _raw_observation()
    raw["relevance"] = "ambiguous"
    _replace_criterion(
        raw,
        "criterion_queue",
        finding="missing",
        level=1,
        answer_quotes=[],
        knowledge_refs=[],
    )

    decision = _decide(_validated(raw), followup_count=1)

    assert decision["action"] == "NEXT"
    assert decision["reason_code"] == "FOLLOWUP_LIMIT_REACHED"
    assert decision["target"] is None


# T15: a supported legal alternative is evidence; keywords do not drive Policy.
def test_t15_supported_alternative_advances_without_keyword_penalty():
    raw = _raw_observation()
    _replace_criterion(
        raw,
        "criterion_queue",
        explanation="环形缓冲区方案在题目允许边界内，且已说明选择依据。",
    )

    decision = _decide(_validated(raw))

    assert decision["action"] == "NEXT"
    assert decision["reason_code"] == "ADEQUATE_EVIDENCE"


# T16: lack of reviewed knowledge is abstention, not a negative technical result.
def test_t16_unknown_technology_is_not_treated_as_failure():
    raw = _raw_observation()
    raw["knowledge_status"] = "insufficient"
    _replace_criterion(
        raw,
        "criterion_queue",
        finding="not_assessable",
        level=None,
        answer_quotes=[],
        knowledge_refs=[],
    )

    observation = _validated(raw)
    decision = _decide(observation)

    assert observation["criteria"][0]["level"] is None
    assert decision["action"] == "NEXT"
    assert decision["reason_code"] == "NO_LEGAL_PROBE"


# T17: conflicting material asks for clarification and never declares fabrication.
def test_t17_conflicting_evidence_is_clarified_without_negative_conclusion():
    raw = _raw_observation()
    raw["knowledge_status"] = "conflicted"
    _replace_criterion(
        raw,
        "criterion_queue",
        finding="not_assessable",
        level=None,
        answer_quotes=[],
        knowledge_refs=[],
    )

    decision = _decide(_validated(raw))

    assert decision["action"] == "CLARIFY"
    assert decision["reason_code"] == "CONFLICTING_EVIDENCE"
    assert "扣分" in decision["reason_summary"]


# T18: invalid analyzer output raises before there is anything Policy can decide on.
def test_t18_invalid_model_output_raises_typed_error_and_returns_no_observation():
    raw = _raw_observation()
    raw["action"] = "PROBE"

    with pytest.raises(ObservationValidationError, match="schema violation"):
        _validated(raw)


@pytest.mark.parametrize("field", ["answer_id", "question_id", "root_question_id"])
def test_t18_model_cannot_replace_server_ids(field):
    raw = _raw_observation()
    raw[field] = "attacker_supplied_id"

    with pytest.raises(ObservationValidationError, match="server ID"):
        _validated(raw)


# T19: a real-looking ID cannot launder a fabricated quotation or foreign reference.
def test_t19_exact_quote_must_be_a_literal_substring_of_original_answer():
    raw = _raw_observation()
    raw["criteria"][0]["answer_quotes"][0]["exact_quote"] = "我使用了无锁队列"

    with pytest.raises(ObservationValidationError, match="literal answer substring"):
        _validated(raw)


def test_t19_quote_must_point_to_the_exact_answer_id():
    raw = _raw_observation()
    raw["criteria"][0]["answer_quotes"][0]["answer_id"] = "answer_other_01"

    with pytest.raises(ObservationValidationError, match="wrong answer_id"):
        _validated(raw)


def test_t19_knowledge_reference_must_be_in_frozen_allowed_set():
    raw = _raw_observation()
    raw["criteria"][0]["knowledge_refs"] = ["plausible_but_not_frozen"]

    with pytest.raises(ObservationValidationError, match="non-frozen"):
        _validated(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("criterion_id", "criterion_substitute", "criterion IDs"),
        ("kind", "expression", "frozen kind"),
        ("weight", 99, "frozen weight"),
    ],
)
def test_fixed_rubric_id_kind_and_weight_cannot_be_changed(field, value, message):
    raw = _raw_observation()
    raw["criteria"][0][field] = value

    with pytest.raises(ObservationValidationError, match=message):
        _validated(raw)


def test_fixed_rubric_cannot_omit_or_duplicate_a_criterion():
    omitted = _raw_observation()
    omitted["criteria"].pop()
    with pytest.raises(ObservationValidationError, match="criterion IDs"):
        _validated(omitted)

    duplicated = _raw_observation()
    duplicated["criteria"][1] = deepcopy(duplicated["criteria"][0])
    with pytest.raises(ObservationValidationError, match="duplicate criterion"):
        _validated(duplicated)


def test_technical_supported_or_contradicted_finding_needs_reviewed_reference():
    for finding, level in (("supported", 2), ("contradicted", 0)):
        raw = _raw_observation()
        _replace_criterion(
            raw,
            "criterion_queue",
            finding=finding,
            level=level,
            knowledge_refs=[],
        )
        with pytest.raises(ObservationValidationError, match="reviewed references"):
            _validated(raw)


def test_bounded_fallback_cannot_supply_reviewed_technical_judgment():
    snapshot = deepcopy(RUBRIC_SNAPSHOT)
    snapshot["source"] = "bounded_fallback"
    raw = _raw_observation()

    with pytest.raises(ObservationValidationError, match="reviewed references"):
        validate_observation(
            raw,
            observation_id=OBSERVATION_ID,
            answer_id=ANSWER_ID,
            question_id=QUESTION_ID,
            root_question_id=ROOT_ID,
            answer_text=ANSWER_TEXT,
            rubric_snapshot=snapshot,
        )


def test_supported_or_contradicted_finding_requires_answer_evidence():
    raw = _raw_observation()
    raw["criteria"][0]["answer_quotes"] = []

    with pytest.raises(ObservationValidationError, match="ungrounded finding"):
        _validated(raw)


def test_no_legal_probe_advances_and_never_invents_challenge_action():
    raw = _raw_observation()
    _replace_criterion(
        raw,
        "criterion_queue",
        finding="missing",
        level=1,
        answer_quotes=[],
        knowledge_refs=[],
    )

    decision = _decide(_validated(raw), intents=("CHALLENGE",))

    assert decision["action"] == "NEXT"
    assert decision["reason_code"] == "NO_LEGAL_PROBE"
    assert decision["action"] != "CHALLENGE"


def test_next_is_finalized_as_end_when_no_roots_remain():
    decision = _decide(_validated(), remaining_roots=0)

    assert decision["action"] == "END"
    assert decision["reason_code"] == "ALL_ROOTS_COMPLETED"
    assert decision["target"] is None


def test_followup_limit_finalizes_as_end_when_no_roots_remain():
    decision = _decide(_validated(), followup_count=1, remaining_roots=0)

    assert decision["action"] == "END"
    assert decision["reason_code"] == "ALL_ROOTS_COMPLETED"


def test_validation_returns_a_detached_copy_in_frozen_rubric_order():
    raw = _raw_observation()
    raw["criteria"].reverse()

    validated = _validated(raw)
    raw["criteria"][0]["explanation"] = "mutated after validation"

    assert [item["criterion_id"] for item in validated["criteria"]] == [
        "criterion_queue",
        "criterion_ownership",
    ]
    assert validated["criteria"][1]["explanation"] != "mutated after validation"
