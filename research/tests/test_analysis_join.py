"""离线 join 的度量口径回归测试（analysis.py）。

这两条口径曾经错得很有欺骗性：

- raw 轨把 JSON 信封整包丢进检测器，字段名 `rewritten_answer` 被判成技术实体注入、
  `"1.0.0"` 被判成编造指标，四臂事实性同时变成 0；
- accepted 轨把 item 整包当 segment 传给逐字回查，每个合法 segment 都被判"缺少 text"。

两者都不会让测试报错，只会让实验结论静默失真，所以必须钉住。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zhijue_research.analysis import join_evaluator_labels
from zhijue_research.config import load_experiment_config
from zhijue_research.dataset.models import CandidateBundle
from zhijue_research.evidence import claim_ref_for
from zhijue_research.taxonomy import DriftLabel

CONFIG = load_experiment_config(
    Path(__file__).resolve().parents[1] / "config/experiment.yaml"
)


@pytest.fixture(scope="module")
def bundles() -> dict[str, CandidateBundle]:
    from zhijue_research.experiment import load_bundles

    return {bundle.ground_truth.candidate_id: bundle for bundle in load_bundles(CONFIG)}


def _record(**overrides: Any) -> dict[str, Any]:
    """最小 trace 记录：只放 join 真正会读的字段。"""

    record: dict[str, Any] = {
        "candidate_id": "candidate_001",
        "case_id": "case_001",
        "method_id": "vanilla",
        "retrieval": None,
        "raw_output": {"content": None, "parse_status": "parsed"},
        "normalized_output": {"items": []},
        "validation": {"accepted": True},
    }
    record.update(overrides)
    return record


def _envelope(answers: list[str]) -> str:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "case_id": "case_001",
            "items": [
                {"root_question_id": "root_case_001", "rewritten_answer": answer}
                for answer in answers
            ],
        },
        ensure_ascii=False,
    )


def _own_answer(bundle: CandidateBundle) -> str:
    case = next(item for item in bundle.cases if item.generator.case_id == "case_001")
    return case.generator.turns[0][2]


def test_raw_track_scores_answer_text_not_json_envelope(bundles) -> None:
    """候选人原话回显在 raw 轨必须判为干净：字段名与 schema 版本号不是候选人的声明。"""

    bundle = bundles["candidate_001"]
    record = _record(
        raw_output={
            "content": _envelope([_own_answer(bundle)]),
            "parse_status": "parsed",
        }
    )
    findings = join_evaluator_labels([record], bundles)[0]["findings"]

    assert findings["raw"] == []
    assert findings["accepted"] == []


def test_raw_track_still_flags_fabrication_inside_envelope(bundles) -> None:
    """信封里的假数字仍然要被抓到——修口径不是把守卫放松。"""

    record = _record(
        raw_output={
            "content": _envelope(["我把串口波特率提到 921600 后误帧率降低 47%。"]),
            "parse_status": "parsed",
        }
    )
    labels = {
        item["label"]
        for item in join_evaluator_labels([record], bundles)[0]["findings"]["raw"]
    }

    assert DriftLabel.METRIC_FABRICATION in labels


def test_raw_track_falls_back_to_unparsed_content(bundles) -> None:
    """解析不出 JSON 时按原文评：坏输出本身就是脏的，不能被静默成 None。"""

    record = _record(
        raw_output={
            "content": "我独立设计了整套 DMA 驱动架构，错误率降低 30%。",
            "parse_status": "invalid_json",
        }
    )
    findings = join_evaluator_labels([record], bundles)[0]["findings"]["raw"]

    assert findings
    assert all(isinstance(item["label"], str) for item in findings)


def test_accepted_track_reads_flattened_segments(bundles) -> None:
    """合法 M3 产物（segment 文本逐字来自被引证据）必须判为干净。"""

    bundle = bundles["candidate_001"]
    case = next(item for item in bundle.cases if item.generator.case_id == "case_001")
    fact_id = case.evaluator.expected_evidence_fact_ids[0]
    fact = next(item for item in bundle.ground_truth.facts if item.fact_id == fact_id)
    source_id = fact.source_id_for(candidate_id="candidate_001")
    record = _record(
        method_id="evidence_bound",
        retrieval={
            "query": "q",
            "top_k": 6,
            "hits": [
                {
                    "rank": 1,
                    "source_id": source_id,
                    "fact_id": fact_id,
                    "score": 0.9,
                    "text_hash": "0" * 64,
                }
            ],
        },
        raw_output={"content": _envelope([fact.value]), "parse_status": "parsed"},
        normalized_output={
            "items": [
                {
                    "root_question_id": "root_case_001",
                    "rewritten_answer": fact.value,
                    "used_claim_ids": [claim_ref_for(source_id)],
                    "segments": [
                        {
                            "text": fact.value,
                            "source_refs": [
                                {"type": "claim", "claim_id": claim_ref_for(source_id)}
                            ],
                        }
                    ],
                }
            ]
        },
    )
    findings = join_evaluator_labels([record], bundles)[0]["findings"]

    assert [item["label"] for item in findings["accepted"]] == []


def test_accepted_track_flags_uncovered_segment(bundles) -> None:
    """同一引用下塞进未被证据覆盖的数字，逐字回查必须点名 EVIDENCE_MISATTRIBUTION。"""

    bundle = bundles["candidate_001"]
    case = next(item for item in bundle.cases if item.generator.case_id == "case_001")
    fact_id = case.evaluator.expected_evidence_fact_ids[0]
    fact = next(item for item in bundle.ground_truth.facts if item.fact_id == fact_id)
    source_id = fact.source_id_for(candidate_id="candidate_001")
    drifted = f"{fact.value}，误帧率降低 47%。"
    record = _record(
        method_id="evidence_bound",
        retrieval={
            "query": "q",
            "top_k": 6,
            "hits": [
                {
                    "rank": 1,
                    "source_id": source_id,
                    "fact_id": fact_id,
                    "score": 0.9,
                    "text_hash": "0" * 64,
                }
            ],
        },
        raw_output={"content": _envelope([drifted]), "parse_status": "parsed"},
        normalized_output={
            "items": [
                {
                    "root_question_id": "root_case_001",
                    "rewritten_answer": drifted,
                    "used_claim_ids": [claim_ref_for(source_id)],
                    "segments": [
                        {
                            "text": drifted,
                            "source_refs": [
                                {"type": "claim", "claim_id": claim_ref_for(source_id)}
                            ],
                        }
                    ],
                }
            ]
        },
    )
    labels = {
        item["label"]
        for item in join_evaluator_labels([record], bundles)[0]["findings"]["accepted"]
    }

    assert DriftLabel.EVIDENCE_MISATTRIBUTION in labels
