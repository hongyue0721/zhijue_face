"""Pure validation and deterministic interview progression policy.

The analyzer may propose an Observation, but it cannot choose the next action.  This
module first validates the proposal against the repository's Draft 2020-12 contract
and the server-frozen question snapshot, then derives a Decision from explicit state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

POLICY_VERSION = "1.0.0"

_ACTIONS = frozenset({"CLARIFY", "PROBE", "NEXT", "END"})
_PROBE_INTENTS = frozenset(
    {"detail", "ownership", "counterfactual", "pushback", "reflection"}
)


class ObservationValidationError(ValueError):
    """The analyzer's Observation failed structural or semantic validation."""


def _contract_validator(filename: str) -> Draft202012Validator:
    here = Path(__file__).resolve()
    schema_path = next(
        (
            parent / "contracts" / filename
            for parent in here.parents
            if (parent / "contracts" / filename).is_file()
        ),
        None,
    )
    if schema_path is None:
        raise RuntimeError(f"cannot locate contracts/{filename}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


_OBSERVATION_VALIDATOR = _contract_validator("observation.schema.json")
_DECISION_VALIDATOR = _contract_validator("policy-decision.schema.json")


def _reject(message: str) -> None:
    raise ObservationValidationError(message)


def _validate_schema(raw: Any) -> dict[str, Any]:
    errors = sorted(
        _OBSERVATION_VALIDATOR.iter_errors(raw),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        _reject(f"Observation schema violation at {location}: {error.message}")
    if not isinstance(raw, dict):  # Kept explicit for type narrowing after validation.
        _reject("Observation must be an object")
    return deepcopy(raw)


def _snapshot_parts(
    rubric_snapshot: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], frozenset[str], frozenset[str]]:
    rubric = rubric_snapshot.get("rubric")
    reference_ids = rubric_snapshot.get("reference_ids")
    if not isinstance(rubric, (list, tuple)) or not rubric:
        _reject("rubric_snapshot.rubric must be a non-empty frozen rubric")
    if not isinstance(reference_ids, (list, tuple)) or any(
        not isinstance(ref, str) or not ref for ref in reference_ids
    ):
        _reject("rubric_snapshot.reference_ids must be a list of IDs")
    if any(not isinstance(criterion, Mapping) for criterion in rubric):
        _reject("rubric_snapshot.rubric contains a non-object criterion")

    criterion_ids = [criterion.get("criterion_id") for criterion in rubric]
    if any(
        not isinstance(identifier, str) or not identifier
        for identifier in criterion_ids
    ):
        _reject("rubric_snapshot contains an invalid criterion_id")
    if len(set(criterion_ids)) != len(criterion_ids):
        _reject("rubric_snapshot contains duplicate criterion IDs")

    allowed_refs = frozenset(reference_ids)
    if len(allowed_refs) != len(reference_ids):
        _reject("rubric_snapshot contains duplicate reference IDs")

    # Question instantiation only marks a snapshot approved_seed after the SeedBank's
    # approved gate.  Consequently its frozen reference_ids are the reviewed set.
    reviewed_refs = (
        allowed_refs
        if rubric_snapshot.get("source") == "approved_seed"
        else frozenset()
    )
    return tuple(rubric), allowed_refs, reviewed_refs


def _validate_server_ids(
    observation: Mapping[str, Any],
    *,
    observation_id: str,
    answer_id: str,
    question_id: str,
    root_question_id: str,
) -> None:
    expected = {
        "id": observation_id,
        "answer_id": answer_id,
        "question_id": question_id,
        "root_question_id": root_question_id,
    }
    for field, value in expected.items():
        if observation[field] != value:
            _reject(f"Observation {field} does not match the server ID")


def _criterion_index(
    rubric: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {str(criterion["criterion_id"]): criterion for criterion in rubric}


def _validate_criteria(
    observation: dict[str, Any],
    *,
    answer_id: str,
    answer_text: str,
    rubric: Sequence[Mapping[str, Any]],
    allowed_refs: frozenset[str],
    reviewed_refs: frozenset[str],
) -> None:
    frozen = _criterion_index(rubric)
    proposed = observation["criteria"]
    proposed_ids = [criterion["criterion_id"] for criterion in proposed]
    if len(set(proposed_ids)) != len(proposed_ids):
        _reject("Observation contains duplicate criterion IDs")
    if set(proposed_ids) != set(frozen):
        _reject("Observation criterion IDs do not equal the frozen rubric")

    proposed_by_id = {criterion["criterion_id"]: criterion for criterion in proposed}
    for criterion_id, rubric_criterion in frozen.items():
        criterion = proposed_by_id[criterion_id]
        if criterion["kind"] != rubric_criterion.get("kind"):
            _reject(f"criterion {criterion_id} changed the frozen kind")
        if criterion["weight"] != rubric_criterion.get("weight"):
            _reject(f"criterion {criterion_id} changed the frozen weight")

        quotes = criterion["answer_quotes"]
        if criterion["finding"] in {"supported", "contradicted"} and not quotes:
            _reject(f"criterion {criterion_id} has an ungrounded finding")
        for quote in quotes:
            if quote["answer_id"] != answer_id:
                _reject(f"criterion {criterion_id} quote has the wrong answer_id")
            if quote["exact_quote"] not in answer_text:
                _reject(
                    f"criterion {criterion_id} quote is not a literal answer substring"
                )

        refs = set(criterion["knowledge_refs"])
        if not refs <= allowed_refs:
            _reject(f"criterion {criterion_id} cites a non-frozen knowledge reference")
        if (
            criterion["kind"] == "technical"
            and criterion["finding"] in {"supported", "contradicted"}
            and (not refs or not refs <= reviewed_refs)
        ):
            _reject(
                f"criterion {criterion_id} technical finding lacks reviewed references"
            )

    # Do not let analyzer-controlled ordering decide which equal-weight gap is probed.
    observation["criteria"] = [
        proposed_by_id[str(criterion["criterion_id"])] for criterion in rubric
    ]


def validate_observation(
    raw: Any,
    *,
    observation_id: str,
    answer_id: str,
    question_id: str,
    root_question_id: str,
    answer_text: str,
    rubric_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a validated, detached Observation or raise a typed error.

    Schema validation alone is insufficient: all IDs, quotations, rubric fields, and
    knowledge references are checked against server-owned inputs.  No partial or
    repaired Observation is returned.
    """

    observation = _validate_schema(raw)
    if not isinstance(rubric_snapshot, Mapping):
        _reject("rubric_snapshot must be an object")
    rubric, allowed_refs, reviewed_refs = _snapshot_parts(rubric_snapshot)
    _validate_server_ids(
        observation,
        observation_id=observation_id,
        answer_id=answer_id,
        question_id=question_id,
        root_question_id=root_question_id,
    )
    _validate_criteria(
        observation,
        answer_id=answer_id,
        answer_text=answer_text,
        rubric=rubric,
        allowed_refs=allowed_refs,
        reviewed_refs=reviewed_refs,
    )
    return observation


def _remaining_count(remaining_roots: int) -> int:
    if isinstance(remaining_roots, bool) or not isinstance(remaining_roots, int):
        raise TypeError("remaining_roots must be an integer count")
    if remaining_roots < 0:
        raise ValueError("remaining_roots cannot be negative")
    return remaining_roots


def _make_decision(
    *,
    decision_id: str,
    observation: Mapping[str, Any],
    action: str,
    reason_code: str,
    reason_summary: str,
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    if action not in _ACTIONS:
        raise AssertionError(f"unsupported policy action: {action}")
    decision = {
        "schema_version": "1.0.0",
        "id": decision_id,
        "observation_id": observation["id"],
        "root_question_id": observation["root_question_id"],
        "action": action,
        "reason_code": reason_code,
        "reason_summary": reason_summary,
        "target": target,
        "policy_version": POLICY_VERSION,
    }
    errors = list(_DECISION_VALIDATOR.iter_errors(decision))
    if errors:
        raise ValueError(f"program produced an invalid Decision: {errors[0].message}")
    return decision


def _advance(
    *,
    decision_id: str,
    observation: Mapping[str, Any],
    remaining_roots: int,
    reason_code: str,
    reason_summary: str,
) -> dict[str, Any]:
    if remaining_roots == 0:
        return _make_decision(
            decision_id=decision_id,
            observation=observation,
            action="END",
            reason_code="ALL_ROOTS_COMPLETED",
            reason_summary="当前根问题处理完成，且没有剩余主问题。",
            target=None,
        )
    return _make_decision(
        decision_id=decision_id,
        observation=observation,
        action="NEXT",
        reason_code=reason_code,
        reason_summary=reason_summary,
        target=None,
    )


def _clarification_reason(observation: Mapping[str, Any]) -> tuple[str, str] | None:
    if observation["knowledge_status"] == "conflicted":
        return "CONFLICTING_EVIDENCE", "回答与现有材料存在冲突，先澄清而不据此扣分。"
    if (
        observation["relevance"] in {"ambiguous", "off_topic"}
        or observation["clarification_needed"]
    ):
        return "AMBIGUOUS_ANSWER", "回答偏题或指代不清，需要一个简短澄清。"
    return None


def _most_important_missing(
    observation: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    missing = [
        criterion
        for criterion in observation["criteria"]
        if criterion["finding"] == "missing"
    ]
    if not missing:
        return None
    return min(missing, key=lambda item: (-item["weight"], item["criterion_id"]))


def decide_next(
    *,
    observation: Mapping[str, Any],
    competency_id: str,
    followup_count: int,
    remaining_roots: int,
    allowed_followup_intents: Sequence[str],
    decision_id: str,
) -> dict[str, Any]:
    """Derive the next action without accepting an action proposed by the model."""

    remaining = _remaining_count(remaining_roots)
    if isinstance(followup_count, bool) or not isinstance(followup_count, int):
        raise TypeError("followup_count must be an integer")
    if followup_count < 0:
        raise ValueError("followup_count cannot be negative")

    # The one-followup budget is checked before any desire to clarify or probe.
    if followup_count >= 1:
        return _advance(
            decision_id=decision_id,
            observation=observation,
            remaining_roots=remaining,
            reason_code="FOLLOWUP_LIMIT_REACHED",
            reason_summary="当前根问题已使用一次补充机会，保留未验证项并停止追问。",
        )

    clarification = _clarification_reason(observation)
    if clarification is not None:
        reason_code, summary = clarification
        return _make_decision(
            decision_id=decision_id,
            observation=observation,
            action="CLARIFY",
            reason_code=reason_code,
            reason_summary=summary,
            target={
                "competency_id": competency_id,
                "criterion_id": None,
                "followup_intent": "clarification",
            },
        )

    missing = _most_important_missing(observation)
    legal_intent = next(
        (intent for intent in allowed_followup_intents if intent in _PROBE_INTENTS),
        None,
    )
    if missing is not None and legal_intent is not None:
        return _make_decision(
            decision_id=decision_id,
            observation=observation,
            action="PROBE",
            reason_code="MISSING_REQUIRED_DETAIL",
            reason_summary="一个已明确询问的关键评价点仍缺少证据，仅追问最重要缺口。",
            target={
                "competency_id": competency_id,
                "criterion_id": missing["criterion_id"],
                "followup_intent": legal_intent,
            },
        )

    has_unassessable = any(
        criterion["finding"] == "not_assessable"
        for criterion in observation["criteria"]
    )
    if missing is not None or has_unassessable:
        return _advance(
            decision_id=decision_id,
            observation=observation,
            remaining_roots=remaining,
            reason_code="NO_LEGAL_PROBE",
            reason_summary="没有有价值且合法的追问；未知或不可评价项不作为负面结果。",
        )
    return _advance(
        decision_id=decision_id,
        observation=observation,
        remaining_roots=remaining,
        reason_code="ADEQUATE_EVIDENCE",
        reason_summary="本轮证据已足够，不为展示能力而强行追问。",
    )
