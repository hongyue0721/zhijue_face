"""Deterministic M4 scoring over validated observations and frozen rubrics.

The model proposes criterion findings and levels.  This module alone computes
coverage and numeric scores; missing, skipped, unmeasured, or disputed evidence
never becomes an invented zero.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

SCORING_VERSION = "1.0.0"
_MINIMUM_ROOT_COVERAGE = Decimal("0.60")
_MINIMUM_OVERALL_ROOTS = 3


def _unique(values: list[Any], *, key) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        identity = key(value)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return result


def _level(result: dict[str, Any]) -> int:
    value = result.get("level")
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3:
        raise ValueError("assessable criterion must contain level 0..3")
    return value


def _merge_finding(results: list[dict[str, Any]]) -> tuple[str, int | None]:
    supported = [item for item in results if item.get("finding") == "supported"]
    contradicted = [item for item in results if item.get("finding") == "contradicted"]
    if supported and contradicted:
        return "disputed", None
    if supported:
        return "supported", max(_level(item) for item in supported)
    if contradicted:
        return "contradicted", min(_level(item) for item in contradicted)
    missing = [item for item in results if item.get("finding") == "missing"]
    if missing:
        return "missing", max(_level(item) for item in missing)
    return "not_assessable", None


def _merge_criterion(
    frozen: dict[str, Any], results: list[dict[str, Any]]
) -> dict[str, Any]:
    finding, level = _merge_finding(results)
    quotes = [quote for item in results for quote in item.get("answer_quotes", [])]
    references = [ref for item in results for ref in item.get("knowledge_refs", [])]
    explanations = [
        str(item["explanation"])
        for item in results
        if str(item.get("explanation") or "").strip()
    ]
    return {
        "criterion_id": str(frozen["criterion_id"]),
        "kind": str(frozen["kind"]),
        "weight": frozen["weight"],
        "level": level,
        "finding": finding,
        "answer_quotes": _unique(
            quotes,
            key=lambda quote: (quote.get("answer_id"), quote.get("exact_quote")),
        ),
        "knowledge_refs": _unique(references, key=lambda ref: ref),
        "explanations": _unique(explanations, key=lambda explanation: explanation),
    }


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def score_root(
    *,
    root_question_id: str,
    rubric_snapshot: dict[str, Any],
    observations: list[dict[str, Any]],
    answer_ids: list[str],
    skipped: bool = False,
) -> dict[str, Any]:
    """Merge a root's turns by criterion, then apply the frozen weighted rubric."""
    frozen_rubric = list(rubric_snapshot.get("rubric") or [])
    if not frozen_rubric:
        raise ValueError("root question has no frozen rubric")
    evidence_by_id: dict[str, list[dict[str, Any]]] = {
        str(item["criterion_id"]): [] for item in frozen_rubric
    }
    for observation in observations:
        for result in observation.get("criteria", []):
            criterion_id = str(result.get("criterion_id") or "")
            if criterion_id not in evidence_by_id:
                raise ValueError("observation contains criterion outside frozen rubric")
            evidence_by_id[criterion_id].append(result)

    merged = [
        _merge_criterion(item, evidence_by_id[str(item["criterion_id"])])
        for item in frozen_rubric
    ]
    weights = [Decimal(str(item["weight"])) for item in merged]
    if any(weight <= 0 for weight in weights):
        raise ValueError("frozen rubric weights must be positive")
    assessable = [
        (item, weight)
        for item, weight in zip(merged, weights)
        if item["finding"] not in {"not_assessable", "disputed"}
        and item["level"] is not None
    ]
    total_weight = sum(weights, start=Decimal(0))
    covered_weight = sum((weight for _, weight in assessable), start=Decimal(0))
    coverage_decimal = covered_weight / total_weight
    has_dispute = any(item["finding"] == "disputed" for item in merged)

    score: int | None = None
    if skipped and not observations:
        status = "skipped"
    elif not observations:
        status = "unmeasured"
    elif has_dispute:
        status = "disputed"
    elif not assessable or coverage_decimal < _MINIMUM_ROOT_COVERAGE:
        status = "insufficient"
    else:
        weighted_level = sum(
            (weight * Decimal(int(item["level"])) / Decimal(3))
            for item, weight in assessable
        )
        score = _round_half_up(Decimal(100) * weighted_level / covered_weight)
        status = "scored"

    return {
        "root_question_id": root_question_id,
        "status": status,
        "score": score,
        "coverage": float(coverage_decimal),
        "criterion_results": merged,
        "answer_ids": _unique(answer_ids, key=lambda answer_id: answer_id),
    }


def aggregate_report(
    root_assessments: list[dict[str, Any]],
    *,
    planned_root_count: int,
    asked_root_count: int,
    answered_root_count: int,
    skipped_question_count: int,
) -> tuple[int | None, dict[str, Any]]:
    """Compute equal-root overall score plus explicit assessment-range counts."""
    statuses = [str(item["status"]) for item in root_assessments]
    scores = [
        int(item["score"])
        for item in root_assessments
        if item["status"] == "scored" and item["score"] is not None
    ]
    eligible = len(scores) >= _MINIMUM_OVERALL_ROOTS
    overall = (
        _round_half_up(
            sum((Decimal(score) for score in scores), Decimal(0)) / len(scores)
        )
        if eligible
        else None
    )
    coverage = {
        "planned_root_count": planned_root_count,
        "asked_root_count": asked_root_count,
        "answered_root_count": answered_root_count,
        "scored_root_count": statuses.count("scored"),
        "insufficient_root_count": statuses.count("insufficient"),
        "disputed_root_count": statuses.count("disputed"),
        "skipped_root_count": statuses.count("skipped"),
        "unmeasured_root_count": statuses.count("unmeasured"),
        "skipped_question_count": skipped_question_count,
        "overall_eligible": eligible,
    }
    return overall, coverage
