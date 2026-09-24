"""事实漂移 taxonomy 与校验分类（研究侧；不改 ZhiJue 业务枚举）。"""

from __future__ import annotations

from enum import StrEnum

TAXONOMY_VERSION = "cef_taxonomy_1.0.0"


class DriftLabel(StrEnum):
    """模型对候选人事实做了不允许的改动。"""

    TECHNOLOGY_INJECTION = "TECHNOLOGY_INJECTION"
    METRIC_FABRICATION = "METRIC_FABRICATION"
    RESPONSIBILITY_INFLATION = "RESPONSIBILITY_INFLATION"
    OUTCOME_INFLATION = "OUTCOME_INFLATION"
    CAUSAL_FABRICATION = "CAUSAL_FABRICATION"
    CROSS_PROJECT_LEAKAGE = "CROSS_PROJECT_LEAKAGE"
    TEMPORAL_DRIFT = "TEMPORAL_DRIFT"
    EVIDENCE_MISATTRIBUTION = "EVIDENCE_MISATTRIBUTION"


#: 确定性 validator 拒绝 raw output 的原因分类（R1 由业务侧产生稳定 code）。
VALIDATION_REASON_CODES = (
    "SCHEMA_INVALID",
    "REPORT_ID_MISMATCH",
    "DUPLICATE_ROOT",
    "UNKNOWN_ROOT",
    "INVALID_ANSWER_QUOTE",
    "CLAIM_OUTSIDE_SNAPSHOT",
    "UNKNOWN_SOURCE",
    "UNBOUND_NUMERIC_FACT",
    "UNBOUND_HIGH_RISK_ASSERTION",
    "UNBOUND_TECHNICAL_TOKEN",
    "SEGMENT_MISMATCH",
    "CLAIM_SUMMARY_MISMATCH",
    "COVERAGE_MISMATCH",
    "PAYLOAD_KEY_MISSING",
    "PAYLOAD_TYPE_INVALID",
    "UNCLASSIFIED_GROUNDED_CONTENT_FAILURE",
)

#: validator 拒绝类别 → 该次拒绝"最可能对应的漂移类型"。
#: 只用于报告分面统计，不作为事实性判定本身。
REASON_TO_DRIFT_HINT: dict[str, DriftLabel] = {
    "UNBOUND_NUMERIC_FACT": DriftLabel.METRIC_FABRICATION,
    "UNBOUND_HIGH_RISK_ASSERTION": DriftLabel.RESPONSIBILITY_INFLATION,
    "UNBOUND_TECHNICAL_TOKEN": DriftLabel.TECHNOLOGY_INJECTION,
    "CLAIM_OUTSIDE_SNAPSHOT": DriftLabel.EVIDENCE_MISATTRIBUTION,
    "UNKNOWN_SOURCE": DriftLabel.EVIDENCE_MISATTRIBUTION,
    "INVALID_ANSWER_QUOTE": DriftLabel.EVIDENCE_MISATTRIBUTION,
}

DETECTOR_IDS = (
    "new_number_detector",
    "responsibility_inflation_detector",
    "unsupported_entity_detector",
    "cross_project_leakage_detector",
    "exact_evidence_attribution",
)
