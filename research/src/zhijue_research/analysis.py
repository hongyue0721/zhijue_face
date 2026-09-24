"""离线聚合：trace（生成事实）+ evaluator 视图（标签）→ findings 与双轨指标。

方向是单向的：本模块读 trace 与 ground truth，产出诊断；生成阶段永远拿不到这里的结果
（防污染规则 3）。`findings` 键只存在于聚合产物，不属于 research-trace 契约。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zhijue_research.dataset.models import CandidateBundle
from zhijue_research.evaluators import evaluate_text
from zhijue_research.evaluators.metrics import (
    aggregate_trace_metrics,
    summarize_by_method,
)
from zhijue_research.evidence import claim_ref_for, source_id_from_claim_ref
from zhijue_research.taxonomy import TAXONOMY_VERSION


@dataclass(frozen=True, slots=True)
class CaseIndex:
    """把 candidate_id/case_id 映到 evaluator 视图，供 trace 反查。"""

    cases: Mapping[str, dict[str, Any]]

    @classmethod
    def build(cls, bundles: Mapping[str, CandidateBundle]) -> CaseIndex:
        index: dict[str, dict[str, Any]] = {}
        for candidate_id, bundle in bundles.items():
            ground_truth = bundle.ground_truth
            for case in bundle.cases:
                index[f"{candidate_id}/{case.case_id}"] = {
                    "bundle": bundle,
                    "evaluator": case.evaluator,
                    "facts": ground_truth.facts,
                }
        return cls(cases=index)

    def require(self, record: Mapping[str, Any]) -> dict[str, Any]:
        key = f"{record['candidate_id']}/{record['case_id']}"
        entry = self.cases.get(key)
        if entry is None:
            raise KeyError(f"trace 指向未知 case：{key}")
        return entry


def join_evaluator_labels(
    records: Sequence[dict[str, Any]], bundles: Mapping[str, CandidateBundle]
) -> list[dict[str, Any]]:
    """补两件事：检索召回（离线才知道"该召回什么"）与 evaluator findings。"""

    index = CaseIndex.build(bundles)
    enriched: list[dict[str, Any]] = []
    for record in records:
        row = dict(record)
        entry = index.require(row)
        evaluator = entry["evaluator"]

        retrieval = row.get("retrieval")
        if isinstance(retrieval, dict):
            retrieved = {str(hit["fact_id"]) for hit in retrieval.get("hits", [])}
            expected = list(evaluator.expected_evidence_fact_ids)
            retrieval = dict(retrieval)
            retrieval["expected_evidence_fact_ids"] = expected or None
            retrieval["recall_at_k"] = (
                None if not expected else len(retrieved & set(expected)) / len(expected)
            )
            row["retrieval"] = retrieval

        row["findings"] = {
            "raw": [
                finding.as_dict()
                for finding in _findings_for(row, entry, use_accepted=False)
            ],
            "accepted": (
                [f.as_dict() for f in _findings_for(row, entry, use_accepted=True)]
                if row.get("validation", {}).get("accepted")
                else []
            ),
        }
        enriched.append(row)
    return enriched


def _findings_for(
    record: Mapping[str, Any], entry: Mapping[str, Any], *, use_accepted: bool
) -> tuple:
    """raw 轨看模型原文，accepted 轨看通过校验后的规范化产物。

    两轨共用同一套检测口径；区别只是输入文本来源，这正是"系统拦住了"与
    "模型本来就没编"的分界。
    """

    text = _output_text(record, use_accepted=use_accepted)
    if text is None:
        return ()
    bundle: CandidateBundle = entry["bundle"]
    evidence_texts = _evidence_texts(record, bundle)
    segments = _segments(record) if use_accepted else None
    return tuple(
        evaluate_text(
            output_text=text,
            source_texts=evidence_texts,
            facts=entry["facts"],
            allowed_context_ids=entry["evaluator"].allowed_context_ids,
            segments=segments,
            claim_ref_to_source_id=_claim_map(record, bundle),
            candidate_id=bundle.ground_truth.candidate_id,
        )
    )


def _output_text(record: Mapping[str, Any], *, use_accepted: bool) -> str | None:
    if not use_accepted:
        return _raw_answer_text(record)
    normalized = record.get("normalized_output")
    if not isinstance(normalized, dict):
        return None
    return _joined_answers(normalized.get("items")) or None


def _raw_answer_text(record: Mapping[str, Any]) -> str | None:
    """raw 轨评的是"模型说的话"，不是"模型说的话外面那层 JSON 信封"。

    直接把信封字符串丢进检测器会把 `schema_version`、`rewritten_answer` 这类字段名
    判成技术实体注入、把 `"1.0.0"` 判成编造指标，四臂同时变成 0% 事实性——那是
    度量口径坏了，不是模型坏了。JSON 解析不出来时才退回原文：那种输出本身就是脏的。
    """

    raw = record.get("raw_output")
    content = raw.get("content") if isinstance(raw, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        document = json.loads(content)
    except json.JSONDecodeError:
        return content
    if isinstance(document, Mapping) and isinstance(document.get("items"), list):
        return _joined_answers(document["items"]) or content
    return content


def _joined_answers(items: Any) -> str:
    answers = [
        str(item.get("rewritten_answer", ""))
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping)
    ]
    return "\n".join(answer for answer in answers if answer)


def _evidence_texts(record: Mapping[str, Any], bundle: CandidateBundle) -> list[str]:
    """比较基准 = 候选人自己说的话 + 该方法实际拿到的证据。

    M0/M1 没有证据，基准只有回答文本——所以它们报出的漂移更多，是定义使然，
    不是"效果差异"的结论。
    """

    texts: list[str] = []
    for case in bundle.cases:
        if case.case_id != record["case_id"]:
            continue
        texts.extend(text for _, _, text in case.generator.turns)
    retrieval = record.get("retrieval")
    if isinstance(retrieval, dict):
        hits = {str(hit["source_id"]) for hit in retrieval.get("hits", [])}
        texts.extend(
            fact.value
            for fact in bundle.ground_truth.facts
            if fact.source_id_for(candidate_id=bundle.ground_truth.candidate_id) in hits
        )
    return texts


def _segments(record: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """摊平成 `exact_evidence_attribution` 要的 segment 层。

    检测器逐 segment 读 `text` / `source_refs`；把 item 整包递进去会让每个合法
    segment 都被判成"缺少 text"，M3 的 accepted 轨于是恒为脏。
    """

    normalized = record.get("normalized_output")
    if not isinstance(normalized, dict):
        return None
    rows: list[dict[str, Any]] = []
    for item in normalized.get("items", []):
        if not isinstance(item, dict):
            continue
        segments = item.get("segments")
        if isinstance(segments, list):
            rows.extend(segment for segment in segments if isinstance(segment, dict))
    return rows or None


def _claim_map(record: Mapping[str, Any], bundle: CandidateBundle) -> dict[str, str]:
    mapping: dict[str, str] = {}
    retrieval = record.get("retrieval")
    if isinstance(retrieval, dict):
        for hit in retrieval.get("hits", []):
            source_id = str(hit["source_id"])
            mapping[claim_ref_for(source_id)] = source_id
    for fact in bundle.ground_truth.facts:
        source_id = fact.source_id_for(candidate_id=bundle.ground_truth.candidate_id)
        mapping.setdefault(claim_ref_for(source_id), source_id)
    return mapping


def score_traces(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """双轨指标。raw 轨含被拒绝的 cell；accepted 轨只含通过硬校验的产物。"""

    findings_of = {
        _cell_key(record): [
            found for found in record.get("findings", {}).get("raw", ())
        ]
        for record in records
    }
    prepared = [
        dict(record, findings=findings_of[_cell_key(record)]) for record in records
    ]
    metrics = aggregate_trace_metrics(prepared)
    accepted_only = [
        dict(record, findings=record.get("findings", {}).get("accepted", ()))
        for record in records
    ]
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "metrics": metrics,
        "by_method": summarize_by_method(prepared),
        "accepted_track": aggregate_trace_metrics(
            [record for record in accepted_only if record["validation"]["accepted"]]
        ),
        "records": [
            dict(record, findings=findings_of[_cell_key(record)]) for record in records
        ],
    }


def _cell_key(record: Mapping[str, Any]) -> str:
    return f"{record['candidate_id']}/{record['case_id']}/{record['method_id']}"


def source_id_of_claim_ref(claim_ref: str) -> str:
    return source_id_from_claim_ref(claim_ref)
