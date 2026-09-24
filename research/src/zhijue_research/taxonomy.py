"""研究侧事实漂移分类（不改 ZhiJue 业务枚举）。

`DriftLabel` 描述"模型在优化回答时对候选人事实做了什么"；
`ValidationCode` 是确定性 validator 拒绝 raw output 的原因（R1 已在业务侧产出
机器可读 code，本模块只做研究侧的稳定别名，避免业务字符串改动直接冲击论文图表）。
"""

from __future__ import annotations

from enum import StrEnum

TAXONOMY_VERSION = "drift_taxonomy_1.0.0"


class DriftLabel(StrEnum):
    """事实漂移类型。顺序稳定，用于报告列。"""

    TECHNOLOGY_INJECTION = "TECHNOLOGY_INJECTION"
    METRIC_FABRICATION = "METRIC_FABRICATION"
    RESPONSIBILITY_INFLATION = "RESPONSIBILITY_INFLATION"
    OUTCOME_INFLATION = "OUTCOME_INFLATION"
    CAUSAL_FABRICATION = "CAUSAL_FABRICATION"
    CROSS_PROJECT_LEAKAGE = "CROSS_PROJECT_LEAKAGE"
    TEMPORAL_DRIFT = "TEMPORAL_DRIFT"
    EVIDENCE_MISATTRIBUTION = "EVIDENCE_MISATTRIBUTION"


#: 检测器标识；报告里必须连同 evaluator_version 一起出现。
DETECTOR_IDS = (
    "new_number_detector",
    "responsibility_inflation_detector",
    "unsupported_entity_detector",
    "cross_project_leakage_detector",
    "exact_evidence_attribution",
)

#: R1 业务 validator 产出的 code（与 zhijue.domain.grounded_content.VALIDATION_CODES 对齐）。
VALIDATION_CODES = frozenset(
    {
        "SCHEMA_INVALID",
        "REPORT_ID_MISMATCH",
        "DRAFT_ID_MISMATCH",
        "DUPLICATE_ROOT",
        "DUPLICATE_SECTION",
        "DUPLICATE_ITEM",
        "DUPLICATE_CANDIDATE",
        "DUPLICATE_SOURCE_BLOCK",
        "UNKNOWN_ROOT",
        "UNKNOWN_SOURCE",
        "INVALID_ANSWER_QUOTE",
        "INVALID_SOURCE_QUOTE",
        "CLAIM_OUTSIDE_SNAPSHOT",
        "CLAIM_REWRITE_FORBIDDEN",
        "CONTACT_DATA_REJECTED",
        "PLACEHOLDER_CONTENT",
        "UNBOUND_NUMERIC_FACT",
        "UNBOUND_HIGH_RISK_ASSERTION",
        "UNBOUND_TECHNICAL_TOKEN",
        "SEGMENT_MISMATCH",
        "CLAIM_SUMMARY_MISMATCH",
        "COVERAGE_MISMATCH",
        "UNSUPPORTED_TASK",
        "PAYLOAD_KEY_MISSING",
        "PAYLOAD_TYPE_INVALID",
        "UNCLASSIFIED_GROUNDED_CONTENT_FAILURE",
        "UNCLASSIFIED_WORKFLOW_FAILURE",
    }
)

#: validator code → 该拒绝"通常意味着"哪种漂移（只用于聚合报告的分面统计，
#: 不作为事实性判定；事实性判定由 evaluators 在 raw output 上完成）。
CODE_TO_DRIFT_HINT: dict[str, DriftLabel] = {
    "UNBOUND_NUMERIC_FACT": DriftLabel.METRIC_FABRICATION,
    "UNBOUND_HIGH_RISK_ASSERTION": DriftLabel.RESPONSIBILITY_INFLATION,
    "UNBOUND_TECHNICAL_TOKEN": DriftLabel.TECHNOLOGY_INJECTION,
    "CLAIM_OUTSIDE_SNAPSHOT": DriftLabel.EVIDENCE_MISATTRIBUTION,
    "UNKNOWN_SOURCE": DriftLabel.EVIDENCE_MISATTRIBUTION,
    "INVALID_ANSWER_QUOTE": DriftLabel.EVIDENCE_MISATTRIBUTION,
}


def is_known_validation_code(code: str) -> bool:
    return code in VALIDATION_CODES
