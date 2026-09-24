"""R5 出口守卫：pilot 全量 dry run 的最终模型输入里不得出现真值/标签/trap。

与 `runner.assert_clean_generation_input` 的逐 cell 断言不同，这里跑**真实数据集**
（3 candidate × 4 case × 4 method），把每一次实际发往模型的 system_prompt + payload
全部序列化后扫描，证明"生成侧看不到答案"是数据事实，而不只是单测里的构造。

模型驱动是 scripted：本节只证明**可见性边界**，不证明模型质量。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from zhijue_research.config import load_experiment_config
from zhijue_research.dataset.models import CandidateBundle
from zhijue_research.experiment import (
    build_plan,
    build_prompt_registry,
    build_scripted_client,
    load_bundles,
    scripted_evidence_for,
)
from zhijue_research.methods.base import CoachingMethod
from zhijue_research.methods.four import METHOD_BY_ID
from zhijue_research.runner import (
    LABEL_MARKERS,
    LeakageError,
    assert_clean_generation_input,
    trap_texts,
)
from zhijue_research.trace import validate_trace

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/experiment.yaml"
EVIDENCE_METHODS = frozenset({"rag_context", "evidence_bound"})


def _run_bundle(bundle: CandidateBundle, config: Any) -> dict[str, Any]:
    """单个 candidate 一次独立运行：client 不共享，调用可归属到 candidate。"""

    client = build_scripted_client(config)
    prompts = build_prompt_registry(config)

    async def go() -> list[dict[str, Any]]:
        plan = build_plan(
            config,
            bundles=[bundle],
            client=client,
            prompts=prompts,
            scripted_evidence=scripted_evidence_for(bundle),
        )
        try:
            return [result.record for result in await plan.run()]
        finally:
            await plan.close()

    records = asyncio.run(go())
    return {"bundle": bundle, "client": client, "records": records}


@pytest.fixture(scope="module")
def pilot() -> dict[str, Any]:
    config = load_experiment_config(CONFIG_PATH)
    runs = [_run_bundle(bundle, config) for bundle in load_bundles(config)]
    return {
        "config": config,
        "runs": runs,
        "calls": [call for item in runs for call in item["client"].calls],
        "records": [record for item in runs for record in item["records"]],
    }


def _blob(call: dict[str, Any]) -> str:
    return json.dumps(call["payload"], ensure_ascii=False, sort_keys=True) + str(
        call["system_prompt"]
    )


def _answer_text(bundle: CandidateBundle, case_id: str) -> str:
    case = next(item for item in bundle.cases if item.generator.case_id == case_id)
    return "\n".join(text for _, _, text in case.generator.turns)


def test_pilot_split_covers_every_cell_with_one_model_call(
    pilot: dict[str, Any],
) -> None:
    """48 cell = 12 case × 4 method，模型调用次数与 cell 数相等：没有隐藏重试。"""

    methods = pilot["config"].methods
    expected = sum(len(item["bundle"].cases) for item in pilot["runs"]) * len(methods)
    assert expected == 48
    assert len(pilot["records"]) == expected
    assert len(pilot["calls"]) == expected


def test_every_cell_validates_against_trace_schema(pilot: dict[str, Any]) -> None:
    for record in pilot["records"]:
        validate_trace(record)


def test_no_model_input_contains_trap_text_or_evaluator_keys(
    pilot: dict[str, Any],
) -> None:
    """任何一次真实模型输入都不得含 trap 文本或真值/标签结构键。"""

    needles: set[str] = set()
    for item in pilot["runs"]:
        needles.update(trap_texts(item["bundle"].ground_truth))
    assert needles, "pilot 数据集必须带 trap，否则本守卫是空跑"

    for call in pilot["calls"]:
        blob = _blob(call)
        for needle in needles:
            assert needle not in blob, f"trap 泄漏进模型输入：{needle[:24]}…"
        for marker in LABEL_MARKERS:
            assert f'"{marker}"' not in blob, f"标签键 {marker} 泄漏进模型输入"


def test_ground_truth_values_reach_generator_only_through_allowed_channel(
    pilot: dict[str, Any],
) -> None:
    """真值原文只能经证据通道进入 M2/M3；M0/M1 只能看到候选人自己说过的话。"""

    violations: list[str] = []
    for item in pilot["runs"]:
        bundle = item["bundle"]
        for call in item["client"].calls:
            method_id = str(call["method_id"])
            payload = call["payload"]
            case_id = str(payload["case_id"])
            answer_text = _answer_text(bundle, case_id)
            blob = _blob(call)
            evidence_texts = [
                str(row["text"]) for row in payload.get("candidate_facts") or []
            ]
            for fact in bundle.ground_truth.facts:
                if fact.value not in blob or fact.value in answer_text:
                    continue
                if method_id in EVIDENCE_METHODS and any(
                    fact.value in text for text in evidence_texts
                ):
                    continue
                violations.append(
                    f"{method_id}/{case_id}: 真值 {fact.fact_id} 越界进入输入"
                )
    assert violations == []


def test_no_evidence_methods_receive_no_evidence_channel(pilot: dict[str, Any]) -> None:
    """结构保证：M0/M1 的请求体里根本没有证据字段，而不是"记得不用"。"""

    seen = set()
    for call in pilot["calls"]:
        method_id = str(call["method_id"])
        method: CoachingMethod = METHOD_BY_ID[method_id]
        seen.add(method_id)
        has_evidence_channel = "candidate_facts" in call["payload"]
        assert has_evidence_channel is method.requires_evidence
        assert method.requires_evidence is (method_id in EVIDENCE_METHODS)
    assert seen == set(pilot["config"].methods)


def test_guard_actually_triggers_on_trap_text(pilot: dict[str, Any]) -> None:
    """守卫可被触发：把 trap 塞进 payload 必须立刻失败，而不是静默通过。"""

    bundle = pilot["runs"][0]["bundle"]
    trap_value = str(bundle.ground_truth.trap_claims[0]["value"])
    assert trap_value in trap_texts(bundle.ground_truth)
    with pytest.raises(LeakageError, match="trap"):
        assert_clean_generation_input(
            {"answer": f"请展开：{trap_value}"}, trap_texts(bundle.ground_truth)
        )
