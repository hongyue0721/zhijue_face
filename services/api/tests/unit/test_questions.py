"""Root-question instantiation preserves approved provenance and safe fallbacks."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from zhijue.application.seed_bank import Seed, SeedBank
from zhijue.domain.planning import InterviewSlot, SlotReason
from zhijue.domain.questions import QuestionDraft, instantiate_root_questions
from zhijue.domain.requisition import CoverageStatus


def _seed(
    seed_id: str,
    competency_id: str,
    *,
    review_status: str = "approved",
    stem: str = "请说明你的具体做法和判断依据。",
) -> Seed:
    """Fixture-only seed; production content still comes through SeedBank."""

    return Seed(
        id=seed_id,
        version="1.2.3",
        competency_id=competency_id,
        difficulty="medium",
        archetype="project",
        intent="fixture-only intent",
        stem=stem,
        reference_ids=("reference_fixture",),
        reference_points=(
            {
                "point_id": "point_fixture",
                "kind": "technical",
                "statement": "fixture-only reviewed point",
                "reference_ids": ["reference_fixture"],
            },
        ),
        red_flags=(),
        follow_up_strategy={
            "max_followups": 1,
            "preferred_intents": ["detail"],
            "stop_conditions": ["fixture stop"],
        },
        rubric=(
            {
                "criterion_id": "criterion_fixture",
                "kind": "technical",
                "weight": 1,
                "levels": {
                    "0": "no evidence",
                    "1": "limited evidence",
                    "2": "supported",
                    "3": "supported with boundaries",
                },
            },
        ),
        followup_intents=("detail",),
        out_of_scope=("fixture limit",),
        review_status=review_status,
    )


def _bank(*seeds: Seed) -> SeedBank:
    return SeedBank(
        list(seeds),
        schema_version="1.0.0",
        live_allowed_review_status="approved",
    )


def _slot(
    index: int,
    competency: str,
    *,
    status: CoverageStatus = CoverageStatus.UNKNOWN,
    evidence_ids: tuple[str, ...] = (),
) -> InterviewSlot:
    return InterviewSlot(
        slot_id=f"slot_{index}_fixture",
        competency=competency,
        jd_requirement_ids=(f"requirement_{index}",),
        candidate_evidence_ids=evidence_ids,
        current_verification_status=status,
        verification_goal=f"验证 fixture goal {index}",
        priority=30 - index,
        difficulty="medium",
        reason_code=SlotReason.JD_CRITICAL_NOT_IN_MATERIAL,
        structured_reason=f"fixture basis {index}",
    )


def test_exact_live_competency_match_wins_and_non_live_seed_is_ignored():
    slot = _slot(1, "embedded.mcu.interrupt")
    approved = _seed("seed_z_approved", slot.competency)
    draft = _seed("seed_a_draft", slot.competency, review_status="draft")
    unrelated = _seed("seed_unrelated", "embedded.peripheral.serial_bus")

    (question,) = instantiate_root_questions(
        (slot,), _bank(draft, unrelated, approved), interview_id="interview_fixture"
    )

    assert question.seed_id == approved.id
    assert question.wording == approved.stem
    assert question.rubric_snapshot["source"] == "approved_seed"
    assert question.rubric_snapshot["competency_id"] == slot.competency


def test_rtos_family_mapping_is_deterministic_nonduplicating_and_reserves_exact_match():
    broad_slot = _slot(1, "embedded.rtos.fundamentals")
    exact_slot = _slot(2, "embedded.rtos.scheduling")
    queue = _seed("seed_queue", "embedded.rtos.queue")
    scheduling = _seed("seed_scheduling", "embedded.rtos.scheduling")

    questions = instantiate_root_questions(
        (broad_slot, exact_slot),
        _bank(scheduling, queue),
        interview_id="interview_fixture",
    )

    assert [question.seed_id for question in questions] == [queue.id, scheduling.id]
    assert len({question.seed_id for question in questions}) == 2
    assert (
        instantiate_root_questions(
            (broad_slot, exact_slot),
            _bank(queue, scheduling),
            interview_id="interview_fixture",
        )
        == questions
    )


def test_unsupported_slot_gets_bounded_nontechnical_experience_evidence_fallback():
    slot = _slot(
        1,
        "embedded.unsupported.internal_id",
        evidence_ids=("claim_fixture",),
    )

    (question,) = instantiate_root_questions(
        (slot,),
        _bank(_seed("seed_unrelated", "embedded.mcu.interrupt")),
        interview_id="interview_fixture",
    )

    snapshot = question.rubric_snapshot
    assert question.seed_id is None
    assert "真实经历" in question.wording
    assert slot.competency not in question.wording
    assert "fixture goal 1" in question.wording
    assert snapshot["source"] == "bounded_fallback"
    assert snapshot["reference_ids"] == []
    assert snapshot["reference_points"] == []
    assert {criterion["kind"] for criterion in snapshot["rubric"]} == {
        "expression",
        "evidence_reasoning",
    }
    assert snapshot["follow_up_strategy"]["max_followups"] == 1
    assert any("不对具体技术结论" in limit for limit in snapshot["out_of_scope"])
    assert question.basis["verification_goal"] == slot.verification_goal
    assert question.basis["candidate_evidence_ids"] == ["claim_fixture"]


def test_five_slot_instantiation_is_stable_ordered_and_unique():
    slots = tuple(
        _slot(index, f"unsupported.dimension_{index}") for index in range(1, 6)
    )
    bank = _bank()

    first = instantiate_root_questions(slots, bank, interview_id="interview_fixture")
    second = instantiate_root_questions(slots, bank, interview_id="interview_fixture")

    assert first == second
    assert isinstance(first[0], QuestionDraft)
    assert len(first) == len(slots) == 5
    assert [question.order_index for question in first] == list(range(5))
    assert len({question.id for question in first}) == 5
    assert all(question.id == question.root_id for question in first)
    assert all(question.kind == "main" for question in first)
    assert [question.basis["slot_id"] for question in first] == [
        slot.slot_id for slot in slots
    ]
    with pytest.raises(FrozenInstanceError):
        first[0].wording = "changed"


def test_seed_backed_snapshot_freezes_approved_provenance_and_nested_values():
    slot = _slot(1, "embedded.mcu.interrupt")
    seed = _seed("seed_interrupt", slot.competency)

    (question,) = instantiate_root_questions(
        (slot,), _bank(seed), interview_id="interview_fixture"
    )
    snapshot = question.rubric_snapshot

    assert snapshot == {
        "schema_version": "1.0.0",
        "source": "approved_seed",
        "seed_schema_version": "1.0.0",
        "seed_id": "seed_interrupt",
        "seed_version": "1.2.3",
        "review_status": "approved",
        "competency_id": "embedded.mcu.interrupt",
        "rubric": list(seed.rubric),
        "reference_ids": ["reference_fixture"],
        "reference_points": list(seed.reference_points),
        "follow_up_strategy": seed.follow_up_strategy,
        "followup_intents": ["detail"],
        "out_of_scope": ["fixture limit"],
    }

    seed.rubric[0]["levels"]["3"] = "mutated after instantiation"
    seed.reference_points[0]["statement"] = "mutated after instantiation"
    seed.follow_up_strategy["max_followups"] = 0

    assert snapshot["rubric"][0]["levels"]["3"] == "supported with boundaries"
    assert snapshot["reference_points"][0]["statement"] == (
        "fixture-only reviewed point"
    )
    assert snapshot["follow_up_strategy"]["max_followups"] == 1


def test_no_candidate_wording_exposes_internal_competency_ids():
    exact_id = "embedded.mcu.interrupt"
    exact = _slot(1, exact_id)
    unsupported = _slot(2, "internal.unsupported.competency")
    seed = _seed(
        "seed_internal_text",
        exact_id,
        stem=f"请解释 {exact_id} 并结合经历。",
    )

    questions = instantiate_root_questions(
        (exact, unsupported), _bank(seed), interview_id="interview_fixture"
    )

    for slot, question in zip((exact, unsupported), questions):
        assert slot.competency not in question.wording
    assert exact_id not in questions[0].wording
    assert "相关岗位能力" in questions[0].wording


def test_unrelated_approved_seed_is_never_bound_to_non_rtos_slot():
    slot = _slot(1, "embedded.communication.protocol_design")
    bank = _bank(
        _seed("seed_interrupt", "embedded.mcu.interrupt"),
        _seed("seed_queue", "embedded.rtos.queue"),
    )

    (question,) = instantiate_root_questions(
        (slot,), bank, interview_id="interview_fixture"
    )

    assert question.seed_id is None
    assert question.rubric_snapshot["source"] == "bounded_fallback"
