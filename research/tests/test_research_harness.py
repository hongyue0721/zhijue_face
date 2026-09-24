"""R2/R3 harness 自检：全部零网络、零模型调用。

这里的 fixture 只证明一件事：harness 的约束方式、留痕与防泄漏逻辑是对的。
任何数值都不构成对真实模型行为的结论。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from zhijue.application.content_workflow import ContentWorkflowError

from zhijue_research.config import ExperimentConfigError, load_experiment_config
from zhijue_research.dataset.loader import (
    DatasetError,
    load_generator_case,
)
from zhijue_research.dataset.models import (
    CandidateBundle,
    GeneratorCaseView,
    GroundTruth,
)
from zhijue_research.evidence import EvidenceError, EvidenceItem, EvidenceSet
from zhijue_research.experiment import (
    build_plan,
    build_scripted_client,
)
from zhijue_research.io_utils import sha256_text
from zhijue_research.model_clients import RaisingModelClient
from zhijue_research.observer import RecordingObserver
from zhijue_research.paths import RUNTIME_DIR
from zhijue_research.prompts import (
    PromptRegistry,
    PromptRegistryError,
    compute_prompt_hashes,
)
from zhijue_research.retrieval import QUERY_TEMPLATE_VERSION, build_retrieval_query
from zhijue_research.runner import (
    LeakageError,
    assert_clean_generation_input,
    trap_texts,
)
from zhijue_research.trace import TraceValidationError, validate_trace

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = RESEARCH_ROOT / "config/experiment.yaml"

# 一条"错误说法"：真实候选人没这么说过，只存在于 trap 清单，用于验证出口守卫。
TRAP_TEXT = "我独立设计了整套 DMA 驱动架构，错误率降低 30%。"
CASE = GeneratorCaseView(
    case_id="case_harness",
    candidate_id="candidate_harness",
    split="pilot",
    question_wording="请说明你排查串口偶发错帧的过程与结果。",
    competency_tags=("uart_debug",),
    turns=(("ans_main", "main", "我先看现象，再看日志，分清串口还是数据处理。"),),
    retrieval_query_template=QUERY_TEMPLATE_VERSION,
)

EVIDENCE = EvidenceSet(
    candidate_id="candidate_harness",
    query="q",
    top_k=2,
    items=(
        EvidenceItem(
            source_id="candidate_harness:F01",
            text="使用 STM32 HAL 与 DMA 完成串口接收。",
            fact_id="F01",
            rank=1,
            score=None,
            generation="gen_cef-1.0.0",
            chunk_id=None,
        ),
        EvidenceItem(
            source_id="candidate_harness:F02",
            text="用逻辑分析仪区分串口接收与数据处理两侧。",
            fact_id="F02",
            rank=2,
            score=None,
            generation="gen_cef-1.0.0",
            chunk_id=None,
        ),
    ),
)


def _bundle(case: GeneratorCaseView) -> CandidateBundle:
    from zhijue_research.dataset.models import EvaluatorCaseView, InterviewCase

    return CandidateBundle(
        ground_truth=GroundTruth(
            candidate_id=case.candidate_id,
            domain="embedded_software",
            data_status="synthetic",
            facts=(),
            trap_claims=({"trap_id": "T01", "value": TRAP_TEXT},),
        ),
        cases=(
            InterviewCase(
                generator=case,
                evaluator=EvaluatorCaseView(
                    case_id=case.case_id,
                    expected_evidence_fact_ids=("F01", "F02"),
                    allowed_context_ids=("self",),
                    injected_drift=(),
                    answer_style_rating="weak",
                ),
            ),
        ),
        private_kb_documents={},
    )


def _config(**overrides):
    config = load_experiment_config(CONFIG_PATH)
    values = {
        "split": "pilot",
        "methods": ("vanilla", "prompt_constraint", "rag_context", "evidence_bound"),
        "allow_paid_calls": False,
    }
    values.update(overrides)
    return replace(config, **values)


def _prompts(config) -> PromptRegistry:
    root = RESEARCH_ROOT / "config/prompts"
    return PromptRegistry(root, compute_prompt_hashes(root))


def _plan(
    config, *, client=None, methods=None, evidence=EVIDENCE, provider_factory=None
):
    case = replace(CASE, case_id=f"case_{'_'.join(methods or config.methods)}")
    bundle = _bundle(case)
    plan = build_plan(
        config if methods is None else replace(config, methods=tuple(methods)),
        bundles=[bundle],
        client=client or build_scripted_client(config),
        prompts=_prompts(config),
        scripted_evidence=None if provider_factory else evidence,
        provider_factory=provider_factory,
    )
    return plan, case


# --- 配置与 prompt 冻结 --------------------------------------------------------


def test_config_fingerprint_is_stable_and_method_scoped() -> None:
    first = load_experiment_config(CONFIG_PATH)
    second = load_experiment_config(CONFIG_PATH)
    assert first.fingerprint == second.fingerprint
    assert first.model.fingerprint() == second.model.fingerprint()
    key = first.experiment_key(
        case_id="case_a",
        method_id="vanilla",
        model_fingerprint=first.model.fingerprint(),
    )
    assert key == first.experiment_key(
        case_id="case_a",
        method_id="vanilla",
        model_fingerprint=first.model.fingerprint(),
    )
    assert key != first.experiment_key(
        case_id="case_a",
        method_id="rag_context",
        model_fingerprint=first.model.fingerprint(),
    )
    assert first.derive_run_id(key) == f"r_{key[:16]}"


def test_config_refuses_paid_calls_and_path_outside_runtime(tmp_path: Path) -> None:
    config = load_experiment_config(CONFIG_PATH)
    assert config.allow_paid_calls is False
    with pytest.raises(ExperimentConfigError, match="付费模型"):
        from zhijue_research.experiment import build_live_client

        build_live_client(config, tmp_path / "missing.env")
    with pytest.raises(ValueError, match="越界"):
        from zhijue_research.paths import runtime_path

        runtime_path("..", "..", "escaped.json")
    assert RUNTIME_DIR.name == "runtime"


def test_prompt_registry_rejects_unregistered_version_and_edited_text(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prompts" / "vanilla"
    root.mkdir(parents=True)
    (root / "p1.0.md").write_text("原始文本", encoding="utf-8")
    hashes = {"vanilla": {"p1.0": sha256_text("原始文本")}}
    registry = PromptRegistry(tmp_path / "prompts", hashes)
    assert registry.load("vanilla", "p1.0").text == "原始文本"

    (root / "p1.0.md").write_text("偷偷改了一句", encoding="utf-8")
    with pytest.raises(PromptRegistryError, match="新建版本"):
        registry.load("vanilla", "p1.0")

    with pytest.raises(PromptRegistryError, match="未在配置中登记"):
        registry.load("vanilla", "p2.0")
    with pytest.raises(PromptRegistryError, match="非法 prompt 版本"):
        registry.load("vanilla", "latest")


def test_experiment_config_requires_registered_prompt_hash(tmp_path: Path) -> None:
    import yaml

    document = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    document["prompt_hashes"] = {}
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="没有登记 hash"):
        load_experiment_config(path)


# --- 可见性与防泄漏 ------------------------------------------------------------


def test_generator_view_drops_evaluator_only_fields() -> None:
    document = {
        "schema_version": "1.0.0",
        "case_id": "case_leak",
        "candidate_id": "candidate_harness",
        "split": "pilot",
        "generator_visible": {
            "question": {
                "wording": "说说你做过的项目。",
                "competency_tags": ["project"],
                "source_seed_id": None,
            },
            "raw_answer": {
                "text": "我参与过一些嵌入式项目。",
                "turns": [
                    {
                        "answer_id": "ans_main",
                        "kind": "main",
                        "text": "我参与过一些嵌入式项目。",
                    }
                ],
            },
            "retrieval_query_spec": {
                "mode": "question_plus_answer",
                "template_version": "rq_1.0",
            },
        },
        "evaluator_only": {
            "expected_evidence_fact_ids": ["F01"],
            "allowed_context_ids": ["self"],
            "injected_drift": [
                {
                    "label": "METRIC_FABRICATION",
                    "probe": {
                        "kind": "trap_claim_available",
                        "value": "错误率降低 30%",
                        "fact_id": None,
                        "trap_id": None,
                    },
                    "note": None,
                }
            ],
            "answer_style_rating": "weak",
        },
    }
    view = load_generator_case(document, forbidden_values=("错误率降低 30%",))
    assert view.question_wording == "说说你做过的项目。"
    assert not hasattr(view, "expected_evidence_fact_ids")
    serialized = json.dumps(asdict(view), ensure_ascii=False, default=list)
    assert "错误率降低 30%" not in serialized
    assert "F01" not in serialized


def test_loader_rejects_trap_text_inside_generator_block() -> None:
    document = {
        "schema_version": "1.0.0",
        "case_id": "case_leak2",
        "candidate_id": "candidate_harness",
        "split": "pilot",
        "generator_visible": {
            "question": {
                "wording": "错误率降低 30% 是怎么做到的？",
                "competency_tags": ["metric"],
                "source_seed_id": None,
            },
            "raw_answer": {
                "text": "我不知道。",
                "turns": [
                    {"answer_id": "ans_main", "kind": "main", "text": "我不知道。"}
                ],
            },
            "retrieval_query_spec": {
                "mode": "question_plus_answer",
                "template_version": "rq_1.0",
            },
        },
        "evaluator_only": {
            "expected_evidence_fact_ids": [],
            "allowed_context_ids": ["self"],
            "injected_drift": [],
            "answer_style_rating": None,
        },
    }
    with pytest.raises(DatasetError, match="泄漏"):
        load_generator_case(
            document, forbidden_values=("错误率降低 30% 是怎么做到的？",)
        )


def test_runner_blocks_payload_carrying_trap_text() -> None:
    config = _config()
    tainted = replace(
        CASE,
        question_wording=f"请展开说明：{TRAP_TEXT}",
    )
    plan, _ = _plan(config, methods=["vanilla"])
    from zhijue_research.methods.four import METHOD_BY_ID

    request = METHOD_BY_ID["vanilla"].build_request(
        case=tainted,
        evidence=None,
        prompt=plan.prompts.load("vanilla", config.prompt_versions["vanilla"]),
    )
    with pytest.raises(LeakageError, match="trap"):
        assert_clean_generation_input(
            request.payload, trap_texts(plan.bundles[0].ground_truth)
        )


def test_unknown_source_is_rejected_not_silently_dropped() -> None:
    foreign = EvidenceSet(
        candidate_id="candidate_other",
        query="q",
        top_k=1,
        items=(EVIDENCE.items[0],),
    )
    with pytest.raises(EvidenceError, match="CROSS_CANDIDATE_SOURCE"):
        foreign.require_candidate()
    with pytest.raises(EvidenceError, match="UNKNOWN_SOURCE"):
        from zhijue_research.evidence import parse_source_id

        parse_source_id("random-id")


# --- 四臂隔离与检索一致性 --------------------------------------------------------


def test_m2_and_m3_receive_identical_ordered_evidence() -> None:
    config = _config()
    plan, _ = _plan(config, methods=["rag_context", "evidence_bound"])
    results = asyncio.run(plan.run())
    by_method = {item.method_id: item.record for item in results}

    m2, m3 = by_method["rag_context"], by_method["evidence_bound"]
    assert m2["retrieval"]["hits"] == m3["retrieval"]["hits"]
    assert [hit["source_id"] for hit in m2["retrieval"]["hits"]] == [
        hit["source_id"] for hit in m3["retrieval"]["hits"]
    ]
    assert m2["evidence_input_hash"] == m3["evidence_input_hash"]
    assert m2["retrieval"]["query"] == m3["retrieval"]["query"]
    assert build_retrieval_query(CASE) == f"{CASE.question_wording}\n{CASE.turns[0][2]}"
    assert plan.providers[0].retrieve_calls == 1  # 每 case 只检索一次
    assert len(m2["retrieval"]["hits"]) == len(m3["retrieval"]["hits"]) > 0


def test_vanilla_and_prompt_constraint_get_no_evidence_at_all() -> None:
    config = _config()
    plan, _ = _plan(config, methods=["vanilla", "prompt_constraint"])
    results = asyncio.run(plan.run())
    for item in results:
        assert item.record["retrieval"] is None
        assert item.record["evidence_input_hash"] is None
        assert item.record["method_id"] in {"vanilla", "prompt_constraint"}
    assert plan.providers[0].retrieve_calls == 0


def test_only_m3_runs_hard_validation_and_all_arms_use_one_attempt() -> None:
    config = _config()
    plan, _ = _plan(config)
    results = asyncio.run(plan.run())
    by_method = {item.method_id: item for item in results}
    assert {
        name: item.record["validation"]["performed"] for name, item in by_method.items()
    } == {
        "vanilla": False,
        "prompt_constraint": False,
        "rag_context": False,
        "evidence_bound": True,
    }
    assert all(item.record["attempts"] == 1 for item in results)
    assert plan.client.call_count == len(results)


def test_deterministic_validator_rejects_unbound_number() -> None:
    config = _config()
    plan, _ = _plan(
        config,
        methods=["evidence_bound"],
        client=build_scripted_client(config, drift_methods=("evidence_bound",)),
    )
    result = asyncio.run(plan.run())[0]
    plan_client = plan.client

    assert result.accepted is False
    assert result.record["validation"]["status"] == "failed"
    assert result.record["validation"]["reasons"] == ["UNBOUND_NUMERIC_FACT"]
    assert result.record["raw_output"]["content"] is not None
    assert "30%" in result.record["raw_output"]["content"]
    assert result.record["attempts"] == 1
    assert plan_client.call_count == 1  # 拒绝后没有偷偷再调一次


def _m3_client(mutate):
    """在合法 M3 输出上做单点改动：报告 id/根题 id 全部来自真实 payload，不手抄常量。"""

    from zhijue_research.model_clients import ScriptedModelClient
    from zhijue_research.scripted import bound_envelope

    def responder(method_id: str, payload: dict) -> str:
        assert method_id == "evidence_bound"
        return json.dumps(
            mutate(json.loads(bound_envelope(payload))), ensure_ascii=False
        )

    return ScriptedModelClient(responder=responder)


def _mutate_bad_quote(document: dict) -> dict:
    document["items"][0]["segments"][0]["source_refs"] = [
        {
            "type": "answer_quote",
            "answer_id": "ans_main",
            "exact_quote": "逐字不存在于回答的引文",
        }
    ]
    document["items"][0]["used_claim_ids"] = []
    return document


def _mutate_foreign_claim(document: dict) -> dict:
    document["items"][0]["segments"][0]["source_refs"] = [
        {"type": "claim", "claim_id": "candidate_harness__F99"}
    ]
    document["items"][0]["used_claim_ids"] = ["candidate_harness__F99"]
    return document


def _mutate_summary_mismatch(document: dict) -> dict:
    document["items"][0]["used_claim_ids"] = []
    return document


def _mutate_segment_gap(document: dict) -> dict:
    item = document["items"][0]
    item["segments"] = [
        {
            "text": item["rewritten_answer"][:-2],
            "source_refs": item["segments"][0]["source_refs"],
        }
    ]
    return document


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (_mutate_bad_quote, "INVALID_ANSWER_QUOTE"),
        (_mutate_foreign_claim, "CLAIM_OUTSIDE_SNAPSHOT"),
        (_mutate_summary_mismatch, "CLAIM_SUMMARY_MISMATCH"),
        (_mutate_segment_gap, "SEGMENT_MISMATCH"),
    ],
)
def test_each_m3_violation_gets_its_own_reason_code(mutate, expected_code: str) -> None:
    config = _config()
    client = _m3_client(mutate)
    plan, _ = _plan(config, methods=["evidence_bound"], client=client)
    result = asyncio.run(plan.run())[0]

    assert result.accepted is False
    assert result.record["validation"]["reasons"] == [expected_code]
    # 被拒绝的原文仍然保留：论文要回答"模型是否试图编造"，不只是"系统有没有放行"。
    assert result.record["raw_output"]["content"] is not None
    assert result.record["normalized_output"] is None
    assert result.record["attempts"] == 1


def test_unvalidated_arms_do_not_reject_the_same_violation() -> None:
    """同一份捏造内容在 M2 被接受：这是"有没有硬校验"这一自变量的定义，不是效果结论。"""

    config = _config()
    from zhijue_research.model_clients import ScriptedModelClient
    from zhijue_research.scripted import open_envelope

    client = ScriptedModelClient(
        responder=lambda method_id, payload: open_envelope(payload, drift=True)
    )
    plan, _ = _plan(config, methods=["rag_context"], client=client)
    result = asyncio.run(plan.run())[0]

    assert result.accepted is True
    assert result.record["validation"] == {
        "performed": False,
        "status": "not_performed",
        "reasons": [],
        "accepted": True,
    }
    assert "30%" in result.record["normalized_output"]["items"][0]["rewritten_answer"]


# --- 观察者与失败路径 -----------------------------------------------------------


def test_observer_records_raw_output_before_validation_fuzzing() -> None:
    observer = RecordingObserver()
    from zhijue.application.content_workflow import run_grounded_content_workflow

    content = json.dumps({"not": "a coaching result"}, ensure_ascii=False)
    client = build_scripted_client(_config(), override={"evidence_bound": content})
    generator = _generator(client)

    with pytest.raises(ContentWorkflowError) as caught:
        asyncio.run(
            run_grounded_content_workflow(
                generator=generator,
                task="coach_answers",
                payload=_coaching_payload(),
                timeout_seconds=20,
                observer=observer,
            )
        )
    assert str(caught.value) == "generated content failed contract validation"
    assert observer.observed.validation_reasons == ("SCHEMA_INVALID",)
    assert observer.observed.raw_content == content
    assert observer.observed.input_hash
    assert observer.observed.usage == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost": None,
    }


def _generator(client):
    from zhijue_research.model_clients import PromptBoundGenerator

    return PromptBoundGenerator(
        method_id="evidence_bound", system_prompt="s", client=client
    )


def _coaching_payload() -> dict:
    return {
        "report_id": "report_case",
        "answers_by_root": {"root_case": {"ans_main": "原回答"}},
        "root_questions": {"root_case": "题面"},
        "allowed_claims": {},
    }


def test_observer_exception_does_not_change_business_result(caplog) -> None:
    """观察者在钩子里抛异常：Workflow 结果必须与无观察者时一致，并且被记录而不是静默。"""

    config = _config()
    baseline = asyncio.run(_plan(config, methods=["vanilla"])[0].run())[0].record

    class Explosive(RecordingObserver):
        def on_raw_generation(self, event) -> None:
            raise RuntimeError("boom")

    import zhijue_research.runner as runner_module

    original = runner_module.RecordingObserver
    runner_module.RecordingObserver = Explosive
    try:
        with caplog.at_level("WARNING", logger="zhijue.content_workflow"):
            polluted = asyncio.run(_plan(config, methods=["vanilla"])[0].run())[
                0
            ].record
    finally:
        runner_module.RecordingObserver = original

    # 除真实计时读数与"观察者自己丢的那一格观测值"外，业务事实必须逐字段一致。
    ignored = {"created_at", "latency_ms", "raw_output"}
    assert {k: v for k, v in polluted.items() if k not in ignored} == {
        k: v for k, v in baseline.items() if k not in ignored
    }
    assert polluted["validation"] == baseline["validation"]
    assert polluted["normalized_output"] == baseline["normalized_output"]
    assert polluted["attempts"] == baseline["attempts"] == 1
    # 崩掉的观察者丢的是自己的数据；业务侧只记日志，不落任何模型内容。
    assert polluted["raw_output"]["content"] is None
    assert baseline["raw_output"]["content"] is not None
    warnings = [
        record.message
        for record in caplog.records
        if record.name == "zhijue.content_workflow"
    ]
    assert warnings == [
        "content workflow observer hook on_raw_generation failed: RuntimeError"
    ]


def test_observer_internal_failure_is_counted_not_raised() -> None:
    """观察者内部真的处理失败时：自己计数，业务侧不受影响。"""

    from zhijue.application.content_workflow import GenerationInputEvent

    observer = RecordingObserver()
    observer.on_generation_input(
        GenerationInputEvent(task="coach_answers", payload={"bad": object()})
    )
    assert observer.observed.observer_failures == 1
    assert observer.observed.input_hash is None

    ok = RecordingObserver()
    ok.on_generation_input(GenerationInputEvent(task="coach_answers", payload={"a": 1}))
    assert ok.observed.observer_failures == 0
    assert ok.observed.input_hash


def test_transport_error_keeps_trace_and_does_not_retry() -> None:
    config = _config()
    from zhijue.application.answer_workflow import ModelRequestTimeoutError

    client = RaisingModelClient(ModelRequestTimeoutError("model request timed out"))
    plan, _ = _plan(config, methods=["vanilla"], client=client)
    result = asyncio.run(plan.run())[0]
    assert result.accepted is False
    assert result.record["attempts"] == 1
    assert result.record["raw_output"]["parse_status"] == "transport_error"
    assert result.record["validation"]["reasons"] == ["TRANSPORT_ERROR"]
    assert client.call_count == 1


# --- trace 契约 ------------------------------------------------------------------


def test_trace_records_validate_against_contract() -> None:
    config = _config()
    plan, _ = _plan(config)
    results = asyncio.run(plan.run())
    for item in results:
        validate_trace(item.record)
    record = results[0].record
    assert record["schema_version"] == "1.0.0"
    assert record["config_fingerprint"] == config.fingerprint
    assert record["cost_basis"] == "not_measured"
    assert record["cost"] is None
    assert record["input_tokens"] is None
    assert record["model_driver"] == "scripted"


def test_trace_rejects_invented_values() -> None:
    broken = {
        "schema_version": "1.0.0",
        "method_id": "vanilla",
        "cost": 0,
        "cost_basis": "provider",
    }
    with pytest.raises(TraceValidationError):
        validate_trace(broken)


def test_scripted_result_is_marked_as_fixture_not_live() -> None:
    plan, _ = _plan(_config(), methods=["vanilla"])
    record = asyncio.run(plan.run())[0].record
    assert record["model_driver"] == "scripted"
    assert record["model"] == "scripted-fixture"
    assert record["provider"] == "fixture-local"
