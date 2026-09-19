"""Deterministic root-question instantiation from interview slots.

The planner decides what must be verified.  This module binds that decision to
caller-supplied, live-eligible seed content without loading a seed bank itself.
When no approved seed is suitable, it produces a deliberately non-technical
experience/evidence question rather than inventing a technical answer key.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from zhijue.domain.planning import InterviewSlot
from zhijue.domain.requisition import CoverageStatus

if TYPE_CHECKING:
    from zhijue.application.seed_bank import Seed, SeedBank

_RTO_FUNDAMENTALS = "embedded.rtos.fundamentals"
_RTO_FAMILY_PREFIX = "embedded.rtos."


@dataclass(frozen=True)
class QuestionDraft:
    """Persistence-ready root question before an interview owns it."""

    id: str
    root_id: str
    kind: str
    seed_id: str | None
    wording: str
    basis: dict[str, Any]
    rubric_snapshot: dict[str, Any]
    order_index: int


def instantiate_root_questions(
    slots: tuple[InterviewSlot, ...] | list[InterviewSlot],
    seed_bank: SeedBank,
    *,
    interview_id: str,
) -> tuple[QuestionDraft, ...]:
    """Instantiate exactly one deterministic root question per input slot.

    Exact competency matches are allocated before the one permitted family
    mapping.  This prevents an early generic RTOS slot from consuming a seed
    needed by a later exact slot.  A seed is never reused within one plan.
    """

    ordered_slots = tuple(slots)
    eligible = tuple(
        sorted(seed_bank.live_eligible(), key=lambda seed: (seed.id, seed.version))
    )
    assigned: list[Seed | None] = [None] * len(ordered_slots)
    used_seed_ids: set[str] = set()

    # Reserve all exact matches first, independent of slot order.
    for index, slot in enumerate(ordered_slots):
        seed = _first_unused(
            eligible,
            used_seed_ids,
            competency_id=slot.competency,
        )
        if seed is not None:
            assigned[index] = seed
            used_seed_ids.add(seed.id)

    # Only the explicitly approved broad RTOS slot may borrow within its family.
    family_candidates = tuple(
        sorted(
            (
                seed
                for seed in eligible
                if seed.competency_id.startswith(_RTO_FAMILY_PREFIX)
            ),
            key=lambda seed: (seed.competency_id, seed.id, seed.version),
        )
    )
    for index, slot in enumerate(ordered_slots):
        if assigned[index] is not None or slot.competency != _RTO_FUNDAMENTALS:
            continue
        seed = _first_unused(family_candidates, used_seed_ids)
        if seed is not None:
            assigned[index] = seed
            used_seed_ids.add(seed.id)

    drafts: list[QuestionDraft] = []
    for order_index, (slot, seed) in enumerate(zip(ordered_slots, assigned)):
        question_id = _root_question_id(interview_id, slot, order_index)
        if seed is None:
            wording = _fallback_wording(slot)
            snapshot = _fallback_rubric_snapshot(slot.competency)
        else:
            wording = _candidate_safe_seed_wording(seed, slot)
            snapshot = _seed_rubric_snapshot(seed, seed_bank.schema_version)
        drafts.append(
            QuestionDraft(
                id=question_id,
                root_id=question_id,
                kind="main",
                seed_id=seed.id if seed is not None else None,
                wording=wording,
                basis=_slot_basis(slot),
                rubric_snapshot=snapshot,
                order_index=order_index,
            )
        )
    return tuple(drafts)


def _first_unused(
    candidates: tuple[Seed, ...],
    used_seed_ids: set[str],
    *,
    competency_id: str | None = None,
) -> Seed | None:
    for seed in candidates:
        if seed.id in used_seed_ids:
            continue
        if competency_id is not None and seed.competency_id != competency_id:
            continue
        return seed
    return None


def _root_question_id(interview_id: str, slot: InterviewSlot, order_index: int) -> str:
    digest = hashlib.sha256(
        f"{interview_id}:{slot.slot_id}:{order_index}".encode()
    ).hexdigest()[:12]
    return f"question_main_{order_index + 1:02d}_{digest}"


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _slot_basis(slot: InterviewSlot) -> dict[str, Any]:
    if (
        slot.current_verification_status is CoverageStatus.CONTRADICTED
        or slot.candidate_evidence_ids
    ):
        basis_type = "resume"
    else:
        basis_type = "gap"
    return {
        "schema_version": "1.0.0",
        "basis_type": basis_type,
        "slot_id": slot.slot_id,
        "competency_id": slot.competency,
        "verification_goal": slot.verification_goal,
        "jd_requirement_ids": list(slot.jd_requirement_ids),
        "candidate_evidence_ids": list(slot.candidate_evidence_ids),
        "current_verification_status": _enum_value(slot.current_verification_status),
        "reason_code": _enum_value(slot.reason_code),
        "structured_reason": slot.structured_reason,
    }


def _seed_rubric_snapshot(seed: Seed, schema_version: str) -> dict[str, Any]:
    # Seed contains nested mutable JSON values.  A deep copy is required so an
    # interview's evaluation contract cannot drift if caller-owned data changes.
    return deepcopy(
        {
            "schema_version": "1.0.0",
            "source": "approved_seed",
            "seed_schema_version": schema_version,
            "seed_id": seed.id,
            "seed_version": seed.version,
            "review_status": seed.review_status,
            "competency_id": seed.competency_id,
            "rubric": list(seed.rubric),
            "reference_ids": list(seed.reference_ids),
            "reference_points": list(seed.reference_points),
            "follow_up_strategy": seed.follow_up_strategy,
            "followup_intents": list(seed.followup_intents),
            "out_of_scope": list(seed.out_of_scope),
        }
    )


def _fallback_rubric_snapshot(competency_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "source": "bounded_fallback",
        "seed_schema_version": None,
        "seed_id": None,
        "seed_version": None,
        "review_status": None,
        "competency_id": competency_id,
        "rubric": [
            {
                "criterion_id": "fallback_expression",
                "kind": "expression",
                "weight": 1,
                "levels": {
                    "0": "未说明可理解的经历或处理思路",
                    "1": "只给出结论，缺少过程与边界",
                    "2": "说明了目标、做法和基本边界",
                    "3": "说明清晰，能区分事实、判断和不确定部分",
                },
            },
            {
                "criterion_id": "fallback_evidence_reasoning",
                "kind": "evidence_reasoning",
                "weight": 1,
                "levels": {
                    "0": "未提供可核对的观察或证据计划",
                    "1": "提到结果，但无法说明如何判断",
                    "2": "给出可观察证据及其与结论的关系",
                    "3": "给出证据、判断依据、限制及可复核方式",
                },
            },
        ],
        "reference_ids": [],
        "reference_points": [],
        "follow_up_strategy": {
            "max_followups": 1,
            "preferred_intents": ["clarification", "detail"],
            "stop_conditions": ["已说明具体做法和可核对证据"],
        },
        "followup_intents": ["clarification", "detail"],
        "out_of_scope": [
            "不对具体技术结论作正确性判断",
            "不把材料未提及视为不会",
            "不给出录用结论",
        ],
    }


def _candidate_safe_seed_wording(seed: Seed, slot: InterviewSlot) -> str:
    wording = seed.stem.strip()
    # Approved stems should already be candidate-safe.  This final boundary
    # prevents accidental leakage if fixture or future seed text embeds an
    # internal taxonomy identifier verbatim.
    for internal_id in {seed.competency_id, slot.competency}:
        wording = wording.replace(internal_id, "相关岗位能力")
    return wording


def _fallback_wording(slot: InterviewSlot) -> str:
    safe_goal = (
        slot.verification_goal.replace(slot.competency, "这项岗位相关能力")
        .strip()
        .rstrip("。；;")
    )
    if slot.current_verification_status is CoverageStatus.CONTRADICTED:
        return (
            f"{safe_goal}。材料中相关描述存在差异，请说明实际情况、你的具体做法"
            "和可以核对的证据；不确定的部分请明确指出。"
        )
    if slot.candidate_evidence_ids:
        return (
            f"{safe_goal}。请结合材料中的一次真实经历，说明当时的目标、你的具体"
            "做法、观察到的证据，以及你如何判断结果；不确定的部分请明确指出。"
        )
    return (
        f"{safe_goal}。请结合一次相关经历或练习，说明目标、你的具体做法、观察"
        "到的证据，以及你如何判断结果。如果没有直接经历，也可以说明你会如何"
        "收集证据；不需要猜测具体技术结论。"
    )
