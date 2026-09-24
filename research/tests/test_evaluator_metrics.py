"""metrics 双轨聚合测试：raw 与 accepted 不得混算，缺字段不补 0。

数据全部手写内联（不依赖 research/data/**，避免与 DataForge 互相阻塞）。
"""

from __future__ import annotations

import json
from typing import Any

from zhijue_research.evaluators.findings import Finding
from zhijue_research.evaluators.metrics import (
    aggregate_trace_metrics,
    summarize_by_method,
)
from zhijue_research.taxonomy import DriftLabel

DRIFT: list[dict[str, Any]] = [
    {"label": "TECHNOLOGY_INJECTION", "detector_id": "unsupported_entity_detector"}
]
METRIC_DRIFT: list[dict[str, Any]] = [
    {"label": "METRIC_FABRICATION", "detector_id": "new_number_detector"}
]

_ABSENT = "<<absent>>"


def record(
    method_id: str,
    *,
    accepted: bool | None = None,
    reasons: list[str] | None = None,
    findings: list[Any] | None | str = _ABSENT,
    recall: float | None | str = _ABSENT,
) -> dict[str, Any]:
    """哨兵 `_ABSENT` 表示字段整体缺失（区别于显式 null）。

    recall=None → retrieval 整体 null（M0/M1）；recall=_ABSENT → retrieval 对象存在但无键。
    """

    rec: dict[str, Any] = {"method_id": method_id}
    if accepted is not None:
        rec["validation"] = {
            "performed": True,
            "status": "passed" if accepted else "failed",
            "reasons": reasons if reasons is not None else [],
            "accepted": bool(accepted),
        }
    if findings != _ABSENT:
        rec["findings"] = [] if findings is None else findings
    if recall == _ABSENT:
        rec["retrieval"] = {"top_k": 4}
    elif recall is None:
        rec["retrieval"] = None
    else:
        rec["retrieval"] = {"recall_at_k": recall}
    return rec


def test_dual_track_never_mixed_and_missing_fields_counted() -> None:
    r1 = record(
        "vanilla",
        accepted=False,
        reasons=["UNBOUND_TECHNICAL_TOKEN"],
        findings=DRIFT,
        recall=None,
    )
    r2 = record("vanilla", accepted=True, reasons=[], findings=[], recall=0.5)
    r3 = record(
        "rag_context", accepted=True, reasons=[], findings=METRIC_DRIFT, recall=None
    )
    r4 = record(
        "rag_context", accepted=True, reasons=[], recall=_ABSENT
    )  # 缺 findings 键
    r5 = record(
        "prompt_constraint",
        accepted=False,
        reasons=["SCHEMA_INVALID"],
        findings=[],
        recall=None,
    )
    r6: dict[str, Any] = {
        "method_id": "evidence_bound",
        "findings": [],
        "retrieval": {"recall_at_k": 1.0},
    }  # 缺 validation
    metrics = aggregate_trace_metrics([r1, r2, r3, r4, r5, r6])

    # raw 轨：r1,r2,r3,r5,r6（5 条含 findings），干净 3 → 0.6
    assert metrics["raw_generation_factuality"] == 3 / 5
    assert metrics["raw_generation_n"] == 5
    # accepted 轨：只 r2、r3（r4 缺 findings 不进）→ 1/2 = 0.5；两轨不同、未混算
    assert metrics["accepted_output_factuality"] == 1 / 2
    assert metrics["accepted_output_n"] == 2
    assert metrics["raw_generation_factuality"] != metrics["accepted_output_factuality"]
    # acceptance：r1..r5 有 accepted（r6 缺 validation）→ 3/5
    assert metrics["acceptance_rate"] == 3 / 5
    assert metrics["acceptance_n"] == 5
    assert metrics["rejection_reason_distribution"] == {
        "SCHEMA_INVALID": 1,
        "UNBOUND_TECHNICAL_TOKEN": 1,
    }
    # recall mean：0.5 与 1.0；显式 null（r1/r3/r5）不拉低分母、不算缺失
    assert metrics["retrieval_recall_at_k_mean"] == 0.75
    assert metrics["retrieval_recall_at_k_n"] == 2
    assert metrics["missing_field_counts"] == {
        "findings": 1,
        "retrieval.recall_at_k": 1,
        "validation": 1,
    }
    assert metrics["invalid_record_count"] == 0
    json.dumps(metrics)  # 输出必须 JSON 友好


def test_ratio_is_none_not_zero_when_no_eligible_records() -> None:
    metrics = aggregate_trace_metrics([{"method_id": "vanilla"}])
    assert metrics["raw_generation_factuality"] is None
    assert metrics["accepted_output_factuality"] is None
    assert metrics["acceptance_rate"] is None
    assert metrics["retrieval_recall_at_k_mean"] is None
    assert metrics["missing_field_counts"] == {
        "findings": 1,
        "retrieval": 1,
        "validation": 1,
    }


def test_findings_accepts_finding_objects() -> None:
    finding = Finding(
        label=DriftLabel.TEMPORAL_DRIFT,
        detector_id="new_number_detector",
        snippet="2019",
        detail="demo",
        source_ids=(),
        deterministic=True,
    )
    rec = record("vanilla", accepted=True, reasons=[], findings=[finding], recall=None)
    metrics = aggregate_trace_metrics([rec])
    assert metrics["raw_generation_factuality"] == 0.0  # 有漂移 → 不干净
    assert metrics["accepted_output_factuality"] == 0.0


def test_summarize_by_method_groups_per_track() -> None:
    r1 = record(
        "vanilla",
        accepted=False,
        reasons=["UNBOUND_TECHNICAL_TOKEN"],
        findings=DRIFT,
        recall=None,
    )
    r2 = record("vanilla", accepted=True, reasons=[], findings=[], recall=0.5)
    r3 = record(
        "rag_context", accepted=True, reasons=[], findings=METRIC_DRIFT, recall=None
    )
    r4 = record("rag_context", accepted=True, reasons=[], recall=_ABSENT)
    grouped = summarize_by_method([r1, r2, r3, r4, {"findings": []}, 42])
    assert set(grouped) == {"rag_context", "vanilla"}

    vanilla = grouped["vanilla"]
    assert vanilla["raw_generation_factuality"] == 1 / 2
    assert vanilla["accepted_output_factuality"] == 1.0
    assert vanilla["acceptance_rate"] == 1 / 2
    assert vanilla["retrieval_recall_at_k_mean"] == 0.5

    rag = grouped["rag_context"]
    assert rag["raw_generation_factuality"] == 0.0  # 只有 r3 带 findings，且含漂移
    assert rag["missing_field_counts"] == {"findings": 1, "retrieval.recall_at_k": 1}
    json.dumps(grouped)


def test_non_mapping_records_counted_as_invalid() -> None:
    metrics = aggregate_trace_metrics(
        [{"method_id": "vanilla", "findings": []}, "junk"]
    )
    assert metrics["record_count"] == 2
    assert metrics["invalid_record_count"] == 1
