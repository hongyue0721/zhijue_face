"""数据集加载：JSON Schema 校验 + 可见性投影 + 划分冻结守卫。

泄漏的定义（与 DESIGN §9 一致，避免把"候选人提到自己经历"误判成泄漏）：

- 禁止进入生成侧：**trap 错误说法文本**、**evaluator 标签**（expected_evidence 的
  fact_id 字面量、injected_drift 的标签与 trap 探针文本）、真值结构键名。
- 允许进入生成侧：候选人自己的回答文本，以及 M2/M3 检索到的 confirmed 事实原文——
  后者本来就是实验处理的对象。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from zhijue_research.dataset.models import (
    EVALUATOR_ONLY_KEYS,
    CandidateBundle,
    CandidateFact,
    EvaluatorCaseView,
    GeneratorCaseView,
    GroundTruth,
    InterviewCase,
)
from zhijue_research.io_utils import canonical_json, read_json, sha256_json

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
DATA_STATUS_VALUES = frozenset(
    {"synthetic", "synthetic_transcribed_from_demo_document"}
)
#: 判定"标签文本泄漏"的最小长度：更短的片段会误伤正常表达。
LEAK_NEEDLE_MIN_CHARS = 8


class DatasetError(ValueError):
    """数据集违反契约；这种情况下禁止跑实验。"""


def _validator(filename: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


_CACHE: dict[str, Draft202012Validator] = {}


def validate_ground_truth_document(document: Mapping[str, Any]) -> None:
    if "ground_truth" not in _CACHE:
        _CACHE["ground_truth"] = _validator("candidate-ground-truth.schema.json")
    _raise_first_error(_CACHE["ground_truth"], document, "ground_truth")


def validate_case_document(document: Mapping[str, Any]) -> None:
    if "case" not in _CACHE:
        _CACHE["case"] = _validator("interview-case.schema.json")
    _raise_first_error(_CACHE["case"], document, "interview_case")


def _raise_first_error(
    validator: Draft202012Validator, document: Any, where: str
) -> None:
    errors = sorted(validator.iter_errors(document), key=lambda item: str(item.path))
    if errors:
        first = errors[0]
        path = "/".join(str(part) for part in first.path) or "<root>"
        raise DatasetError(f"{where} 违反契约 at {path}: {first.message}")


def _fact_from(document: Mapping[str, Any]) -> CandidateFact:
    provenance = document["provenance"]
    return CandidateFact(
        fact_id=document["fact_id"],
        context_id=document["context_id"],
        predicate=document["predicate"],
        value=document["value"],
        polarity=document["polarity"],
        confirmed=bool(document["confirmed"]),
        provenance_kind=provenance["kind"],
        provenance_locator=provenance["locator"],
        verbatim=provenance["verbatim"],
    )


def load_ground_truth(path: Path) -> GroundTruth:
    document = read_json(path)
    validate_ground_truth_document(document)
    facts = tuple(_fact_from(item) for item in document["facts"])
    _require_unique(fact.fact_id for fact in facts)
    return GroundTruth(
        candidate_id=document["candidate_id"],
        domain=document["domain"],
        data_status=document["data_status"],
        facts=facts,
        trap_claims=tuple(document["trap_claims"]),
        raw=document,
    )


def forbidden_generation_text(ground_truth: GroundTruth) -> tuple[str, ...]:
    """生成侧禁止出现的文本：trap 错误说法（真值原文允许，见模块 docstring）。"""

    values = [str(trap.get("value", "")) for trap in ground_truth.trap_claims]
    return tuple(value for value in values if len(value) >= LEAK_NEEDLE_MIN_CHARS)


def load_generator_case(
    document: Mapping[str, Any], *, forbidden_values: Sequence[str] = ()
) -> GeneratorCaseView:
    """只读 `generator_visible`；evaluator-only 字段在返回类型上不可达。"""

    visible = document["generator_visible"]
    case = GeneratorCaseView(
        case_id=document["case_id"],
        candidate_id=document["candidate_id"],
        split=document["split"],
        question_wording=visible["question"]["wording"],
        competency_tags=tuple(visible["question"]["competency_tags"]),
        turns=tuple(
            (turn["answer_id"], turn["kind"], turn["text"])
            for turn in visible["raw_answer"]["turns"]
        ),
        retrieval_query_template=visible["retrieval_query_spec"]["template_version"],
    )
    _assert_no_evaluator_leak(case, document, forbidden_values)
    return case


def _assert_no_evaluator_leak(
    case: GeneratorCaseView,
    document: Mapping[str, Any],
    forbidden_values: Sequence[str],
) -> None:
    serialized = canonical_json(dataclass_to_jsonable(case))
    payload = json.loads(serialized)
    _assert_keys_absent(payload, set(EVALUATOR_ONLY_KEYS))

    evaluator = document["evaluator_only"]
    label_tokens = set(payload_scalar_tokens(payload))
    for fact_id in evaluator["expected_evidence_fact_ids"]:
        if str(fact_id) in label_tokens:
            raise DatasetError(
                f"泄漏：case {case.case_id} 生成侧出现 expected_evidence fact_id {fact_id}"
            )
    trap_like = {
        *[str(value) for value in forbidden_values],
        *[
            str(item["probe"]["value"])
            for item in evaluator["injected_drift"]
            if item["probe"]["kind"] == "trap_claim_available"
        ],
    }
    for needle in {value for value in trap_like if len(value) >= LEAK_NEEDLE_MIN_CHARS}:
        if needle in serialized:
            raise DatasetError(
                f"泄漏：case {case.case_id} 生成侧含 trap/标签文本片段 {needle[:24]}…"
            )


def _assert_keys_absent(payload: Any, forbidden: set[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in forbidden:
                raise DatasetError(f"泄漏：生成侧视图含 evaluator-only 字段 {key}")
            _assert_keys_absent(value, forbidden)
    elif isinstance(payload, list):
        for item in payload:
            _assert_keys_absent(item, forbidden)


def payload_scalar_tokens(payload: Any) -> set[str]:
    tokens: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                tokens.add(str(key))
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)
        elif isinstance(value, str):
            tokens.update(value.split())

    walk(payload)
    return tokens


def dataclass_to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: dataclass_to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [dataclass_to_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): dataclass_to_jsonable(nested) for key, nested in value.items()
        }
    return value


def load_candidate_bundle(candidate_dir: Path) -> CandidateBundle:
    ground_truth_path = candidate_dir / "ground_truth.json"
    if not ground_truth_path.is_file():
        raise DatasetError(f"缺少 ground_truth.json：{candidate_dir}")
    ground_truth = load_ground_truth(ground_truth_path)
    if ground_truth.candidate_id != candidate_dir.name:
        raise DatasetError(
            f"candidate_id 与目录不一致：{ground_truth.candidate_id} != {candidate_dir.name}"
        )
    if ground_truth.data_status not in DATA_STATUS_VALUES:
        raise DatasetError(f"未知 data_status：{ground_truth.data_status}")

    private_kb: dict[str, str] = {}
    kb_dir = candidate_dir / "private_kb"
    for name in ("resume.md", "project_notes.md", "profile_notes.md"):
        path = kb_dir / name
        if path.is_file():
            private_kb[name] = path.read_text(encoding="utf-8")
    if not private_kb:
        raise DatasetError(f"{candidate_dir} 没有 private_kb 材料")

    forbidden = forbidden_generation_text(ground_truth)
    cases: list[InterviewCase] = []
    for path in sorted((candidate_dir / "interview_cases").glob("case_*.json")):
        document = read_json(path)
        validate_case_document(document)
        generator_view = load_generator_case(document, forbidden_values=forbidden)
        evaluator = document["evaluator_only"]
        cases.append(
            InterviewCase(
                generator=generator_view,
                evaluator=EvaluatorCaseView(
                    case_id=document["case_id"],
                    expected_evidence_fact_ids=tuple(
                        evaluator["expected_evidence_fact_ids"]
                    ),
                    allowed_context_ids=tuple(evaluator["allowed_context_ids"]),
                    injected_drift=tuple(evaluator["injected_drift"]),
                    answer_style_rating=evaluator["answer_style_rating"],
                ),
                raw=document,
            )
        )
    if not cases:
        raise DatasetError(f"{candidate_dir} 没有 interview_cases")
    _require_unique(case.case_id for case in cases)
    for case in cases:
        if case.generator.candidate_id != ground_truth.candidate_id:
            raise DatasetError(f"case {case.case_id} 的 candidate_id 与所属目录不一致")

    return CandidateBundle(
        ground_truth=ground_truth,
        cases=tuple(cases),
        private_kb_documents=private_kb,
    )


def load_dataset(
    candidates_root: Path,
    *,
    dataset_version: str,
    split: str,
    split_manifest: Mapping[str, Any],
) -> tuple[CandidateBundle, ...]:
    """按 split 清单加载；清单外一律不进入实验，成员被改动则 hash 不匹配直接失败。"""

    if split_manifest.get("dataset_version") != dataset_version:
        raise DatasetError(
            f"split 清单数据集版本不一致：{split_manifest.get('dataset_version')} != {dataset_version}"
        )
    if split_manifest.get("split") != split:
        raise DatasetError("split 清单与请求的划分不一致")
    case_ids = split_manifest.get("case_ids")
    if not isinstance(case_ids, list) or not case_ids:
        raise DatasetError("split 清单为空，拒绝运行")
    normalized = sorted(str(item) for item in case_ids)
    if sha256_json(normalized) != split_manifest.get("case_ids_sha256"):
        raise DatasetError("split 清单 hash 不匹配：成员被改动过，禁止继续用于正式比较")

    wanted = set(normalized)
    bundles: list[CandidateBundle] = []
    for candidate_dir in sorted(
        path for path in candidates_root.iterdir() if path.is_dir()
    ):
        bundle = load_candidate_bundle(candidate_dir)
        selected = tuple(
            case
            for case in bundle.cases
            if f"{bundle.ground_truth.candidate_id}/{case.case_id}" in wanted
        )
        if not selected:
            continue
        for case in selected:
            if case.split != split:
                raise DatasetError(f"case {case.case_id} 标注的 split 与清单不符")
        bundles.append(
            CandidateBundle(
                ground_truth=bundle.ground_truth,
                cases=selected,
                private_kb_documents=bundle.private_kb_documents,
            )
        )
    covered = {
        f"{bundle.ground_truth.candidate_id}/{case.case_id}"
        for bundle in bundles
        for case in bundle.cases
    }
    missing = sorted(wanted - covered)
    if missing:
        raise DatasetError(f"split 清单里的 case 不存在：{missing}")
    return tuple(bundles)


def load_split_manifest(splits_root: Path, split: str) -> Mapping[str, Any]:
    path = splits_root / f"{split}.json"
    if not path.is_file():
        raise DatasetError(f"split 清单不存在：{path}")
    return read_json(path)


def _require_unique(values: Iterable[Any]) -> None:
    seen: list[Any] = []
    for value in values:
        if value in seen:
            raise DatasetError(f"重复 ID：{value}")
        seen.append(value)
