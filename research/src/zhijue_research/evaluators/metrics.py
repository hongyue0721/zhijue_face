"""trace 记录聚合：双轨事实性指标，严格分轨、缺字段不补 0。

输入是"trace JSONL 记录 + 离线 join 进来的 `findings` 列表"（trace 契约本身
禁止 findings，聚合阶段才附加，见 research-trace.schema.json 的说明）。

轨道定义（禁止混算）：
- `raw_generation_factuality`：对**所有**带 findings 的记录（含 validator 拒绝）
  计算 无漂移记录数 / 总记录数；
- `accepted_output_factuality` / `acceptance_rate`：只统计 `validation.accepted == true`；
- `rejection_reason_distribution`：被拒绝记录按 `validation.reasons` 计数；
- `retrieval_recall_at_k_mean`：只用 `retrieval.recall_at_k` 非 null 的记录。

任何取不到的字段一律跳过并计入 `missing_field_counts`，不得当 0。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .findings import Finding


def _as_label(finding_item: Any) -> str | None:
    """从 dict 形态（聚合文件）或 Finding 实例取 label；取不到返回 None（不猜）。"""

    if isinstance(finding_item, Finding):
        return finding_item.label.value
    if isinstance(finding_item, Mapping):
        label = finding_item.get("label")
        if isinstance(label, str):
            return label
        enum_value = getattr(label, "value", None)
        return enum_value if isinstance(enum_value, str) else None
    return None


def _findings_of(
    record: Mapping[str, Any], missing: dict[str, int]
) -> list[str] | None:
    """返回该记录的漂移 label 列表；`None` 表示 findings 字段不可用（计入缺失）。"""

    if "findings" not in record:
        missing["findings"] = missing.get("findings", 0) + 1
        return None
    raw = record["findings"]
    if not isinstance(raw, list):
        missing["findings"] = missing.get("findings", 0) + 1
        return None
    return [label for item in raw if (label := _as_label(item)) is not None]


def _accepted_of(record: Mapping[str, Any], missing: dict[str, int]) -> bool | None:
    """返回 validation.accepted；`None` 表示该字段不可用（计入缺失）。"""

    validation = record.get("validation") if "validation" in record else None
    if not isinstance(validation, Mapping):
        missing["validation"] = missing.get("validation", 0) + 1
        return None
    accepted = validation.get("accepted")
    if not isinstance(accepted, bool):
        missing["validation.accepted"] = missing.get("validation.accepted", 0) + 1
        return None
    return accepted


def aggregate_trace_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """把记录列表聚合为 JSON 友好的双轨指标 dict。

    返回的每个比率在没有可用记录时为 `None`（不是 0），并配套 `*_n` 计数说明分母。
    """

    missing: dict[str, int] = {}
    invalid_records = 0

    raw_total = raw_clean = 0
    accepted_total = accepted_clean = 0
    acceptance_denominator = acceptance_numerator = 0
    rejection_reasons: dict[str, int] = {}
    recall_values: list[float] = []

    for record in records:
        if not isinstance(record, Mapping):
            invalid_records += 1
            continue

        labels = _findings_of(record, missing)
        accepted = _accepted_of(record, missing)

        if labels is not None:
            raw_total += 1
            if not labels:
                raw_clean += 1
            if accepted is True:
                accepted_total += 1
                if not labels:
                    accepted_clean += 1

        if accepted is not None:
            acceptance_denominator += 1
            if accepted:
                acceptance_numerator += 1
            else:
                validation = record.get("validation")
                reasons = (
                    validation.get("reasons")
                    if isinstance(validation, Mapping)
                    else None
                )
                if not isinstance(reasons, list):
                    missing["validation.reasons"] = (
                        missing.get("validation.reasons", 0) + 1
                    )
                else:
                    for reason in reasons:
                        if isinstance(reason, str):
                            rejection_reasons[reason] = (
                                rejection_reasons.get(reason, 0) + 1
                            )
                        else:
                            missing["validation.reasons.item"] = (
                                missing.get("validation.reasons.item", 0) + 1
                            )

        if "retrieval" not in record:
            missing["retrieval"] = missing.get("retrieval", 0) + 1
        elif record["retrieval"] is None:
            pass  # 显式 null = 该方法不做检索（M0/M1），不是数据缺失
        elif isinstance(record["retrieval"], Mapping):
            retrieval = record["retrieval"]
            if "recall_at_k" not in retrieval:
                missing["retrieval.recall_at_k"] = (
                    missing.get("retrieval.recall_at_k", 0) + 1
                )
            else:
                value = retrieval["recall_at_k"]
                if isinstance(value, bool):
                    missing["retrieval.recall_at_k"] = (
                        missing.get("retrieval.recall_at_k", 0) + 1
                    )
                elif isinstance(value, (int, float)):
                    recall_values.append(float(value))
                elif value is not None:
                    missing["retrieval.recall_at_k"] = (
                        missing.get("retrieval.recall_at_k", 0) + 1
                    )
                # value is None：非检索失败，只是该记录没算出 recall，跳过不计。
        else:
            missing["retrieval"] = missing.get("retrieval", 0) + 1

    def _ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    return {
        "record_count": len(records),
        "invalid_record_count": invalid_records,
        "raw_generation_factuality": _ratio(raw_clean, raw_total),
        "raw_generation_n": raw_total,
        "raw_generation_clean_n": raw_clean,
        "accepted_output_factuality": _ratio(accepted_clean, accepted_total),
        "accepted_output_n": accepted_total,
        "accepted_output_clean_n": accepted_clean,
        "acceptance_rate": _ratio(acceptance_numerator, acceptance_denominator),
        "acceptance_n": acceptance_denominator,
        "rejection_reason_distribution": dict(sorted(rejection_reasons.items())),
        "retrieval_recall_at_k_mean": (
            sum(recall_values) / len(recall_values) if recall_values else None
        ),
        "retrieval_recall_at_k_n": len(recall_values),
        "missing_field_counts": {
            key: count for key, count in sorted(missing.items()) if count
        },
    }


def summarize_by_method(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """按 `method_id` 分组分别聚合；拿不到合法 method_id 的记录不猜归属，直接不进组
    （整体口径仍可在 `aggregate_trace_metrics(records)` 里看到）。"""

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        method_id = record.get("method_id")
        if isinstance(method_id, str) and method_id:
            groups.setdefault(method_id, []).append(record)
    return {
        method: aggregate_trace_metrics(groups[method]) for method in sorted(groups)
    }
