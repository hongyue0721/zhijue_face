"""R4 确定性 evaluator 的 fixture 正反例测试（手写内联数据，零网络、零模型）。"""

from __future__ import annotations

import json

from zhijue.domain.grounded_content import HIGH_RISK_ASSERTIONS

from zhijue_research.dataset.models import CandidateFact
from zhijue_research.evaluators import EVALUATOR_VERSION, Finding, evaluate_text
from zhijue_research.evaluators.deterministic import (
    OWNERSHIP_ASSERTIONS,
    cross_project_leakage_detector,
    exact_evidence_attribution,
    new_number_detector,
    responsibility_inflation_detector,
    unsupported_entity_detector,
)
from zhijue_research.evaluators.interfaces import (
    AtomicClaim,
    AtomicClaimExtractor,
    ClaimEvidenceJudge,
    FixtureAtomicClaimExtractor,
    FixtureClaimEvidenceJudge,
    FixtureUtilityJudge,
    UtilityJudge,
    Verdict,
)
from zhijue_research.evidence import EvidenceItem
from zhijue_research.taxonomy import DETECTOR_IDS, DriftLabel

SOURCE_A = "我用 FreeRTOS Queue 传递采样数据"
SOURCE_RESP = "我用 FreeRTOS Queue 传递采样数据，参与 UART 驱动联调"


def make_fact(
    fact_id: str, context_id: str, value: str, verbatim: str | None = None
) -> CandidateFact:
    return CandidateFact(
        fact_id=fact_id,
        context_id=context_id,
        predicate="did",
        value=value,
        polarity="positive",
        confirmed=True,
        provenance_kind="resume",
        provenance_locator="resume.md",
        verbatim=verbatim if verbatim is not None else value,
    )


def labels(findings: list[Finding]) -> set[str]:
    return {finding.label.value for finding in findings}


# --------------------------------------------------------------------------
# new_number_detector → METRIC_FABRICATION
# --------------------------------------------------------------------------


def test_new_number_flags_fabricated_metric() -> None:
    findings = new_number_detector(
        output_text=f"{SOURCE_A}，把错误率降低了 30%", source_texts=[SOURCE_A]
    )
    assert labels(findings) == {DriftLabel.METRIC_FABRICATION.value}
    assert "30" in findings[0].snippet
    assert "合并后均不存在" in findings[0].detail


def test_new_number_clean_on_echo() -> None:
    assert new_number_detector(output_text=SOURCE_A, source_texts=[SOURCE_A]) == []
    assert (
        evaluate_text(
            output_text=SOURCE_A,
            source_texts=[SOURCE_A],
            facts=[],
            allowed_context_ids=[],
        )
        == []
    )


def test_metric_label_absent_without_numbers() -> None:
    # 同文本但没加数字：不得出现 METRIC_FABRICATION（哪怕有别的强断言）。
    findings = evaluate_text(
        output_text="我把错误率降低了",
        source_texts=[SOURCE_A],
        facts=[],
        allowed_context_ids=[],
    )
    assert DriftLabel.METRIC_FABRICATION.value not in labels(findings)
    assert labels(findings) == {DriftLabel.RESPONSIBILITY_INFLATION.value}


# --------------------------------------------------------------------------
# responsibility_inflation_detector → RESPONSIBILITY_INFLATION
# --------------------------------------------------------------------------


def test_ownership_vocabulary_stays_within_public_high_risk_list() -> None:
    assert set(OWNERSHIP_ASSERTIONS) <= set(HIGH_RISK_ASSERTIONS)


def test_responsibility_flags_participated_became_led() -> None:
    findings = responsibility_inflation_detector(
        output_text="我主导 UART 驱动开发", source_texts=[SOURCE_RESP]
    )
    assert labels(findings) == {DriftLabel.RESPONSIBILITY_INFLATION.value}
    escalation = [f for f in findings if "强度升级" in f.detail]
    assert escalation, findings
    detail = escalation[0].detail
    assert "升级前: 参与" in detail and "升级后: 主导" in detail


def test_responsibility_keeps_participation_level() -> None:
    findings = responsibility_inflation_detector(
        output_text="我参与了 UART 驱动联调", source_texts=[SOURCE_RESP]
    )
    assert findings == []


def test_responsibility_no_escalation_when_source_already_claims_ownership() -> None:
    src = "我主导 UART 驱动联调，也参与 FreeRTOS Queue 的采样数据传递"
    findings = responsibility_inflation_detector(
        output_text="我主导 UART 驱动联调", source_texts=[src]
    )
    assert findings == []


# --------------------------------------------------------------------------
# unsupported_entity_detector → TECHNOLOGY_INJECTION
# --------------------------------------------------------------------------


def test_unsupported_entity_flags_injected_buses() -> None:
    findings = unsupported_entity_detector(
        output_text="我用 FreeRTOS Queue，另外用 CAN 与 Modbus 联调",
        source_texts=[SOURCE_A],
    )
    assert labels(findings) == {DriftLabel.TECHNOLOGY_INJECTION.value}
    assert "CAN" in findings[0].detail and "Modbus" in findings[0].detail
    assert findings[0].snippet == "CAN, Modbus"


def test_unsupported_entity_ignores_chinese_and_lowercase_glue() -> None:
    findings = unsupported_entity_detector(
        output_text="我用 FreeRTOS Queue 传数据 and so on", source_texts=[SOURCE_A]
    )
    assert findings == []


def test_unsupported_entity_ignores_case_and_stem_prefix() -> None:
    assert (
        unsupported_entity_detector(
            output_text="我用 freertos queue 传递数据", source_texts=[SOURCE_A]
        )
        == []
    )
    assert (
        unsupported_entity_detector(
            output_text="我按 modbus 协议轮询", source_texts=["ModbusRTU 轮询仪表"]
        )
        == []
    )


# --------------------------------------------------------------------------
# cross_project_leakage_detector → CROSS_PROJECT_LEAKAGE
# --------------------------------------------------------------------------


FACT_A = make_fact("F01", "proj_a", "做过 CAN 总线节点通信")
FACT_B = make_fact("F02", "proj_b", "用 Modbus 主站轮询仪表")
LEAK_OUTPUT = "我在项目里用 Modbus 主站轮询仪表，也接过 CAN 总线"


def test_cross_project_flags_disallowed_context_fact() -> None:
    findings = cross_project_leakage_detector(
        output_text=LEAK_OUTPUT,
        facts=[FACT_A, FACT_B],
        allowed_context_ids=["proj_a"],
        candidate_id="candidate_aa",
    )
    assert labels(findings) == {DriftLabel.CROSS_PROJECT_LEAKAGE.value}
    assert len(findings) == 1
    assert findings[0].source_ids == ("candidate_aa:F02",)
    assert "proj_b" in findings[0].detail


def test_cross_project_clean_when_all_contexts_allowed() -> None:
    findings = cross_project_leakage_detector(
        output_text=LEAK_OUTPUT,
        facts=[FACT_A, FACT_B],
        allowed_context_ids=["proj_a", "proj_b"],
        candidate_id="candidate_aa",
    )
    assert findings == []


def test_cross_project_without_candidate_id_leaves_source_ids_empty() -> None:
    findings = cross_project_leakage_detector(
        output_text=LEAK_OUTPUT, facts=[FACT_A, FACT_B], allowed_context_ids=["proj_a"]
    )
    assert len(findings) == 1
    assert findings[0].source_ids == ()
    assert "candidate_id" in findings[0].detail


# --------------------------------------------------------------------------
# exact_evidence_attribution（M3）→ EVIDENCE_MISATTRIBUTION
# --------------------------------------------------------------------------


FACT_SELF = make_fact("F01", "self", SOURCE_A)


def _segment(text: str, refs: list[dict]) -> dict:
    return {"text": text, "source_refs": refs}


def test_attribution_clean_for_verbatim_claim() -> None:
    segments = [
        _segment(SOURCE_A, [{"type": "claim", "claim_id": "candidate_aa__F01"}])
    ]
    assert (
        exact_evidence_attribution(
            segments=segments,
            source_texts=[SOURCE_A],
            facts=[FACT_SELF],
            candidate_id="candidate_aa",
        )
        == []
    )


def test_attribution_flags_unknown_claim_ref() -> None:
    segments = [
        _segment(SOURCE_A, [{"type": "claim", "claim_id": "candidate_aa__F99"}])
    ]
    findings = evaluate_text(
        output_text=SOURCE_A,
        source_texts=[SOURCE_A],
        facts=[FACT_SELF],
        allowed_context_ids=["self"],
        segments=segments,
        candidate_id="candidate_aa",
    )
    assert labels(findings) == {DriftLabel.EVIDENCE_MISATTRIBUTION.value}
    assert "F99" in findings[0].detail


def test_attribution_flags_uncovered_segment_numbers() -> None:
    segments = [
        _segment(
            "我用 FreeRTOS Queue 以 30% 频率传递采样数据",
            [{"type": "claim", "claim_id": "candidate_aa__F01"}],
        )
    ]
    findings = exact_evidence_attribution(
        segments=segments,
        source_texts=[SOURCE_A],
        facts=[FACT_SELF],
        candidate_id="candidate_aa",
    )
    assert labels(findings) == {DriftLabel.EVIDENCE_MISATTRIBUTION.value}
    assert findings[0].source_ids == ("candidate_aa:F01",)
    assert "30%" in findings[0].detail


def test_attribution_checks_answer_quote_verbatim() -> None:
    answer_text = "我答：我用 FreeRTOS Queue 传数据"
    good = [
        _segment(
            "我用 FreeRTOS Queue 传数据",
            [
                {
                    "type": "answer_quote",
                    "answer_id": "ans_01",
                    "exact_quote": "我用 FreeRTOS Queue 传数据",
                },
            ],
        )
    ]
    assert (
        exact_evidence_attribution(segments=good, source_texts=[answer_text], facts=[])
        == []
    )
    bad = [
        _segment(
            "我独立完成全部调度",
            [
                {
                    "type": "answer_quote",
                    "answer_id": "ans_01",
                    "exact_quote": "我独立完成全部调度",
                },
            ],
        )
    ]
    findings = exact_evidence_attribution(
        segments=bad, source_texts=[answer_text], facts=[]
    )
    assert labels(findings) == {DriftLabel.EVIDENCE_MISATTRIBUTION.value}


def test_attribution_supports_mapping_resolver() -> None:
    resolver = {"candidate_aa__F01": "candidate_aa:F01"}
    segments = [
        _segment(SOURCE_A, [{"type": "claim", "claim_id": "candidate_aa__F02"}])
    ]
    findings = exact_evidence_attribution(
        segments=segments,
        source_texts=[SOURCE_A],
        facts=[FACT_SELF],
        claim_ref_to_source_id=resolver,
        candidate_id="candidate_aa",
    )
    assert len(findings) == 1
    assert "映射不到" in findings[0].detail


def test_attribution_skipped_without_segments() -> None:
    bad_segment = _segment(
        SOURCE_A, [{"type": "claim", "claim_id": "candidate_aa__F99"}]
    )
    assert (
        evaluate_text(
            output_text=SOURCE_A,
            source_texts=[SOURCE_A],
            facts=[FACT_SELF],
            allowed_context_ids=["self"],
            segments=None,
            candidate_id="candidate_aa",
        )
        == []
    )
    with_segments = evaluate_text(
        output_text=SOURCE_A,
        source_texts=[SOURCE_A],
        facts=[FACT_SELF],
        allowed_context_ids=["self"],
        segments=[bad_segment],
        candidate_id="candidate_aa",
    )
    assert labels(with_segments) == {DriftLabel.EVIDENCE_MISATTRIBUTION.value}


# --------------------------------------------------------------------------
# 汇总入口 / Finding 形状 / 接口占位
# --------------------------------------------------------------------------


def test_evaluate_text_dedupes_sorts_and_stays_deterministic() -> None:
    findings = evaluate_text(
        output_text="我主导 UART 驱动开发，另用 CAN 与 Modbus 联调，错误率降低 30%",
        source_texts=[SOURCE_RESP],
        facts=[FACT_A, FACT_B],
        allowed_context_ids=["self"],
        candidate_id="candidate_aa",
    )
    assert findings == evaluate_text(
        output_text="我主导 UART 驱动开发，另用 CAN 与 Modbus 联调，错误率降低 30%",
        source_texts=[SOURCE_RESP],
        facts=[FACT_A, FACT_B],
        allowed_context_ids=["self"],
        candidate_id="candidate_aa",
    )
    keys = [(f.label.value, f.snippet) for f in findings]
    assert len(keys) == len(set(keys))
    assert keys == sorted(keys)
    assert {f.detector_id for f in findings} <= set(DETECTOR_IDS)
    assert all(f.deterministic for f in findings)
    assert DriftLabel.METRIC_FABRICATION.value in labels(findings)
    assert DriftLabel.TECHNOLOGY_INJECTION.value in labels(findings)


def test_finding_as_dict_is_json_friendly() -> None:
    finding = Finding(
        label=DriftLabel.CROSS_PROJECT_LEAKAGE,
        detector_id="cross_project_leakage_detector",
        snippet="modbus",
        detail="demo",
        source_ids=("candidate_aa:F02",),
        deterministic=True,
    )
    payload = json.loads(json.dumps(finding.as_dict(), ensure_ascii=False))
    assert payload["label"] == "CROSS_PROJECT_LEAKAGE"
    assert payload["source_ids"] == ["candidate_aa:F02"]
    assert isinstance(EVALUATOR_VERSION, str) and EVALUATOR_VERSION


def test_judge_interfaces_and_fixtures_are_offline_and_unknown_capable() -> None:
    extractor: AtomicClaimExtractor = FixtureAtomicClaimExtractor()
    judge: ClaimEvidenceJudge = FixtureClaimEvidenceJudge()
    utility: UtilityJudge = FixtureUtilityJudge()
    assert isinstance(extractor, AtomicClaimExtractor)

    claims = extractor.extract(output_text="我用 Queue 传数据。错误率降低 30%！")
    assert [c.text for c in claims] == ["我用 Queue 传数据", "错误率降低 30%"]

    evidence = EvidenceItem(
        source_id="candidate_aa:F01",
        text="错误率降低 30%，用了 FreeRTOS Queue",
        fact_id="F01",
        rank=1,
        score=None,
        generation=None,
        chunk_id=None,
    )
    supported = judge.judge(claim=claims[1], evidences=[evidence])
    assert supported.verdict is Verdict.SUPPORTED
    assert supported.evidence_source_ids == ("candidate_aa:F01",)

    unsupported = judge.judge(
        claim=AtomicClaim("c", "错误率降低 50%"), evidences=[evidence]
    )
    assert unsupported.verdict is Verdict.UNSUPPORTED
    no_evidence = judge.judge(claim=claims[1], evidences=[])
    assert no_evidence.verdict is Verdict.UNKNOWN
    assert {v.value for v in Verdict} == {
        "SUPPORTED",
        "UNSUPPORTED",
        "CONTRADICTED",
        "UNKNOWN",
    }

    scored = utility.score(
        question="请讲讲你用 FreeRTOS Queue 传递采样数据的细节",
        answer="我当时就是传了传数据",
        candidate_answer="我用 FreeRTOS Queue 传递采样数据",
    )
    assert scored.score == 1.0
    empty = utility.score(question="随便聊聊", answer="", candidate_answer="我用 Queue")
    assert empty.score == 0.0 and "锚点" in empty.rationale
