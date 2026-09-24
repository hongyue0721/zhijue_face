"""Pilot 数据集（research/data/candidates/ 与 research/splits/）的结构自检。

刻意不依赖 dataset loader：所有 JSON 直接读取，schema 校验用 jsonschema。
契约版本：dataset_version=cef-1.0.0；本文件校验的是 pilot 合成候选人数据。

防泄漏三条硬判据（生成侧 = private_kb/*.md 与 case 的 generator_visible 区块）：
  (a) trap_claims[].value（“错误说法”原文）不得出现在生成侧；
  (b) evaluator 标签字面量不得出现在生成侧：expected_evidence_fact_ids 里的
      fact_id 字面量、probe（kind=trap_claim_available / context_absent）的 value、
      probe 引用的 fact_id；
  (c) 真值结构键名（ground_truth / trap_id / expected_labels / injected_drift /
      provenance 等）不得出现在生成侧文本里。
fact.value 出现在 private_kb 是正确且必须的（材料由真值生成），不作为泄漏判据。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_ROOT = RESEARCH_ROOT / "data" / "candidates"
CONTRACTS_ROOT = RESEARCH_ROOT / "contracts"
SPLITS_ROOT = RESEARCH_ROOT / "splits"

MARKER = "<!-- derived_from_confirmed_facts: true -->"
KB_FILES = ("resume.md", "project_notes.md", "profile_notes.md")
DATASET_VERSION = "cef-1.0.0"

#: 生成侧禁止出现的真值/标签结构键名（子串口径，比带引号的键名匹配更严）。
BANNED_GENERATOR_KEYS = (
    "ground_truth",
    "trap_id",
    "trap_claims",
    "expected_labels",
    "expected_evidence_fact_ids",
    "injected_drift",
    "answer_style_rating",
    "allowed_context_ids",
    "provenance",
    "verbatim",
    "evaluator_only",
    "fact_id",
    "basis_fact_ids",
)

#: 四类漂移在 pilot 里必须每人至少被 trap 与 case 各覆盖一次。
FOUR_DRIFTS = {
    "TECHNOLOGY_INJECTION",
    "METRIC_FABRICATION",
    "RESPONSIBILITY_INFLATION",
    "CROSS_PROJECT_LEAKAGE",
}
ALL_LABELS = FOUR_DRIFTS | {
    "OUTCOME_INFLATION",
    "CAUSAL_FABRICATION",
    "TEMPORAL_DRIFT",
    "EVIDENCE_MISATTRIBUTION",
}
REQUIRED_PREDICATES = {
    "used_technology",
    "responsibility",
    "outcome",
    "metric",
    "project_time",
    "learning_status",
    "tool_used",
    "team_size",
    "personal_scope",
}


def canonical_json(value: object) -> str:
    """与 io_utils / 共享契约同一口径（排序键、无空白、保留非 ASCII）。"""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


CANDIDATE_DIRS = sorted(p for p in CANDIDATES_ROOT.iterdir() if p.is_dir())
assert CANDIDATE_DIRS, "pilot 数据集目录为空"
CANDIDATE_IDS = [p.name for p in CANDIDATE_DIRS]


@pytest.fixture(scope="module")
def gt_schema_validator() -> Draft202012Validator:
    return Draft202012Validator(
        load_json(CONTRACTS_ROOT / "candidate-ground-truth.schema.json")
    )


@pytest.fixture(scope="module")
def case_schema_validator() -> Draft202012Validator:
    return Draft202012Validator(
        load_json(CONTRACTS_ROOT / "interview-case.schema.json")
    )


def test_all_three_contracts_are_valid_draft202012() -> None:
    for name in (
        "candidate-ground-truth.schema.json",
        "interview-case.schema.json",
        "research-trace.schema.json",
    ):
        Draft202012Validator.check_schema(load_json(CONTRACTS_ROOT / name))


def _candidate_view(candidate_id: str) -> dict:
    cand = CANDIDATES_ROOT / candidate_id
    gt = load_json(cand / "ground_truth.json")
    kb = {
        name: (cand / "private_kb" / name).read_text(encoding="utf-8")
        for name in KB_FILES
    }
    cases = {
        p.name: load_json(p)
        for p in sorted((cand / "interview_cases").glob("case_*.json"))
    }
    return {"dir": cand, "gt": gt, "kb": kb, "cases": cases}


@pytest.mark.parametrize("candidate_id", CANDIDATE_IDS)
def test_ground_truth_and_cases_validate_against_contracts(
    candidate_id, gt_schema_validator, case_schema_validator
) -> None:
    view = _candidate_view(candidate_id)
    gt_errors = list(gt_schema_validator.iter_errors(view["gt"]))
    assert not gt_errors, [e.message for e in gt_errors]
    assert len(view["cases"]) == 4, f"{candidate_id}: 应有 4 个 case"
    for name, case in view["cases"].items():
        errors = list(case_schema_validator.iter_errors(case))
        assert not errors, (name, [e.message for e in errors])


@pytest.mark.parametrize("candidate_id", CANDIDATE_IDS)
def test_no_leakage_into_generator_side(candidate_id) -> None:
    view = _candidate_view(candidate_id)
    gt, kb, cases = view["gt"], view["kb"], view["cases"]
    kb_all = "\n".join(kb.values())

    # (a) trap 的“错误说法”原文不得出现在任何生成侧文本
    for trap in gt["trap_claims"]:
        for name, text in kb.items():
            assert trap["value"] not in text, (
                f"{candidate_id}: trap {trap['trap_id']} 泄漏进 {name}"
            )
        for name, case in cases.items():
            gv_dump = json.dumps(case["generator_visible"], ensure_ascii=False)
            assert trap["value"] not in gv_dump, (
                f"{candidate_id}: trap {trap['trap_id']} 泄漏进 {name}"
            )

    # (b) evaluator 标签字面量不得出现在生成侧
    for name, case in cases.items():
        gv_dump = json.dumps(case["generator_visible"], ensure_ascii=False)
        evaluator = case["evaluator_only"]
        leaked_ids = []
        referenced_fact_ids = list(evaluator["expected_evidence_fact_ids"])
        referenced_fact_ids += [
            d["probe"]["fact_id"]
            for d in evaluator["injected_drift"]
            if d["probe"].get("fact_id")
        ]
        for fid in referenced_fact_ids:
            if fid in gv_dump or fid in kb_all:
                leaked_ids.append(fid)
        assert not leaked_ids, f"{candidate_id}/{name}: fact_id 字面量泄漏 {leaked_ids}"
        for drift in evaluator["injected_drift"]:
            probe = drift["probe"]
            if probe["kind"] in ("trap_claim_available", "context_absent"):
                assert probe["value"] not in gv_dump, (
                    f"{candidate_id}/{name}: probe 值 {probe['value']!r} 出现在生成侧"
                )
                assert probe["value"] not in kb_all, (
                    f"{candidate_id}/{name}: probe 值 {probe['value']!r} 出现在 private_kb"
                )

    # (c) 真值结构键名不得出现在生成侧
    for name, text in kb.items():
        for key in BANNED_GENERATOR_KEYS:
            assert key not in text, f"{candidate_id}/{name}: 生成侧含结构键名 {key!r}"
    for name, case in cases.items():
        gv_dump = json.dumps(case["generator_visible"], ensure_ascii=False)
        for key in BANNED_GENERATOR_KEYS:
            assert key not in gv_dump, (
                f"{candidate_id}/{name}: generator_visible 含结构键名 {key!r}"
            )


@pytest.mark.parametrize("candidate_id", CANDIDATE_IDS)
def test_private_kb_marker_and_fact_consistency(candidate_id) -> None:
    view = _candidate_view(candidate_id)
    kb = view["kb"]
    for name, text in kb.items():
        assert text.splitlines()[0] == MARKER, (
            f"{candidate_id}/{name}: 首行必须是派生标记"
        )

    registered = {
        d["artifact"]: set(d["generated_from_fact_ids"])
        for d in view["gt"]["derived_materials"]
    }
    for fact in view["gt"]["facts"]:
        hits = {
            f"private_kb/{name}" for name, text in kb.items() if fact["value"] in text
        }
        if fact["confirmed"]:
            assert hits, (
                f"{candidate_id}: confirmed {fact['fact_id']} 的 value 未进入任何材料"
            )
        else:
            assert not hits, (
                f"{candidate_id}: 未确认 {fact['fact_id']} 泄漏进了 private_kb"
            )
        # 派生登记必须如实：出现即登记，未出现不得登记
        for artifact, ids in registered.items():
            assert (artifact in hits) == (fact["fact_id"] in ids), (
                f"{candidate_id}: {fact['fact_id']} 与 {artifact} 的生成关系登记不实"
            )


@pytest.mark.parametrize("candidate_id", CANDIDATE_IDS)
def test_case_evaluator_fields_resolve_to_own_candidate(candidate_id) -> None:
    view = _candidate_view(candidate_id)
    gt = view["gt"]
    fact_ids = [f["fact_id"] for f in gt["facts"]]
    assert len(fact_ids) == len(set(fact_ids)), f"{candidate_id}: fact_id 文件内重复"
    trap_ids = [t["trap_id"] for t in gt["trap_claims"]]
    assert len(trap_ids) == len(set(trap_ids)), f"{candidate_id}: trap_id 文件内重复"
    contexts = sorted({f["context_id"] for f in gt["facts"]})

    for name, case in view["cases"].items():
        assert case["candidate_id"] == candidate_id
        evaluator = case["evaluator_only"]
        assert evaluator["allowed_context_ids"] == contexts, (
            f"{candidate_id}/{name}: allowed_context_ids 与候选人上下文集合不一致"
        )
        for fid in evaluator["expected_evidence_fact_ids"]:
            assert fid in fact_ids, (
                f"{candidate_id}/{name}: expected {fid} 不属于本候选人"
            )
        for trap in gt["trap_claims"]:
            for basis in trap["basis_fact_ids"]:
                assert basis in fact_ids, (
                    f"{candidate_id}: trap {trap['trap_id']} 基线 {basis} 不存在"
                )
        for drift in evaluator["injected_drift"]:
            assert drift["label"] in ALL_LABELS
            probe = drift["probe"]
            if probe.get("trap_id"):
                matches = [
                    t for t in gt["trap_claims"] if t["trap_id"] == probe["trap_id"]
                ]
                assert matches, f"{candidate_id}/{name}: probe trap 不存在"
                assert drift["label"] in matches[0]["expected_labels"], (
                    f"{candidate_id}/{name}: probe 引用 {probe['trap_id']}，但漂移 label "
                    f"{drift['label']} 不在其 expected_labels 里"
                )
            if probe["kind"] == "raw_answer_contains":
                assert probe["value"] in case["generator_visible"]["raw_answer"]["text"]
            if probe["kind"] == "raw_answer_absent":
                assert (
                    probe["value"]
                    not in case["generator_visible"]["raw_answer"]["text"]
                )


def test_fact_ids_never_cross_candidate_boundaries() -> None:
    """跨 candidate 的 fact_id 不串：任何 case 只引用本目录 ground truth 里的 id。"""

    seen_pairs: dict[tuple[str, str], str] = {}
    for candidate_id in CANDIDATE_IDS:
        view = _candidate_view(candidate_id)
        own_ids = {f["fact_id"] for f in view["gt"]["facts"]}
        for name, case in view["cases"].items():
            refs = set(case["evaluator_only"]["expected_evidence_fact_ids"])
            refs |= {
                d["probe"]["fact_id"]
                for d in case["evaluator_only"]["injected_drift"]
                if d["probe"].get("fact_id")
            }
            refs |= {b for t in view["gt"]["trap_claims"] for b in t["basis_fact_ids"]}
            assert refs <= own_ids, (
                f"{candidate_id}/{name}: 引用了非本候选人编号体系的 id"
            )
        for fact in view["gt"]["facts"]:
            assert (candidate_id, fact["fact_id"]) not in seen_pairs, (
                f"{candidate_id}: fact_id {fact['fact_id']} 重复"
            )
            seen_pairs[(candidate_id, fact["fact_id"])] = fact["value"]


@pytest.mark.parametrize("candidate_id", CANDIDATE_IDS)
def test_pilot_content_invariants(candidate_id) -> None:
    gt = _candidate_view(candidate_id)["gt"]
    facts = gt["facts"]
    assert 12 <= len(facts) <= 20, f"{candidate_id}: facts 数量 {len(facts)} 不在 12–20"
    assert re.fullmatch(r"candidate_[0-9a-z_]{2,}", gt["candidate_id"])
    assert gt["authored_by"] == "owner_approved_synthetic_pilot"
    assert gt["authored_at"] is None
    assert gt["data_status"] == "synthetic"
    predicates = {f["predicate"] for f in facts}
    assert REQUIRED_PREDICATES <= predicates, (
        f"{candidate_id}: 谓词缺口 {REQUIRED_PREDICATES - predicates}"
    )
    contexts = {f["context_id"] for f in facts}
    assert "self" in contexts
    assert sum(1 for c in contexts if c.startswith("proj_")) >= 2, (
        f"{candidate_id}: proj_* 上下文少于 2"
    )
    assert sum(1 for f in facts if f["predicate"] == "metric") >= 3, (
        f"{candidate_id}: metric 少于 3 条"
    )
    weak = [
        f
        for f in facts
        if f["predicate"] == "learning_status"
        and re.search(r"只|仅|听过|上课|课堂|了解|没", f["value"])
    ]
    assert len(weak) >= 2, f"{candidate_id}: 弱声明 learning_status 少于 2 条"
    assert all(f["provenance"]["kind"] == "dataset_authored" for f in facts)
    assert all(f["provenance"]["locator"] for f in facts)

    traps = gt["trap_claims"]
    assert len(traps) >= 4, f"{candidate_id}: trap 少于 4 条"
    trap_labels = {l for t in traps for l in t["expected_labels"]}
    assert FOUR_DRIFTS <= trap_labels, (
        f"{candidate_id}: trap 漂移缺口 {FOUR_DRIFTS - trap_labels}"
    )
    assert trap_labels & {"CAUSAL_FABRICATION", "TEMPORAL_DRIFT"}, (
        f"{candidate_id}: 缺因果捏造或时间漂移 trap"
    )

    case_labels: set[str] = set()
    cases = _candidate_view(candidate_id)["cases"]
    for case in cases.values():
        assert case["split"] == "pilot"
        case_labels |= {d["label"] for d in case["evaluator_only"]["injected_drift"]}
        assert case["evaluator_only"]["answer_style_rating"] in ("weak", "medium")
        spec = case["generator_visible"]["retrieval_query_spec"]
        assert spec == {"mode": "question_plus_answer", "template_version": "rq_1.0"}
    assert FOUR_DRIFTS <= case_labels, (
        f"{candidate_id}: case 漂移诱饵缺口 {FOUR_DRIFTS - case_labels}"
    )


def test_split_files_are_consistent_and_recomputable() -> None:
    pilot = load_json(SPLITS_ROOT / "pilot.json")
    assert pilot["schema_version"] == "1.0.0"
    assert pilot["dataset_version"] == DATASET_VERSION
    assert pilot["frozen_at"] is None
    ids = pilot["case_ids"]
    assert ids == sorted(ids)
    assert ids == [f"{c}/case_{n:03d}" for c in CANDIDATE_IDS for n in (1, 2, 3, 4)], (
        "pilot 成员清单必须恰好覆盖 3 个候选人 × 4 个 case"
    )
    assert pilot["case_ids_sha256"] == sha256_text(canonical_json(ids))
    for entry in ids:
        cand, case = entry.split("/")
        assert (
            CANDIDATES_ROOT / cand / "interview_cases" / f"{case}.json"
        ).is_file(), f"pilot 列出的 case 文件不存在: {entry}"
    for name in ("dev", "test"):
        split = load_json(SPLITS_ROOT / f"{name}.json")
        assert split["split"] == name
        assert split["case_ids"] == []
        assert split["case_ids_sha256"] == sha256_text(canonical_json([]))
        assert split["frozen_at"] is None
