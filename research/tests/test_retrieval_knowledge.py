"""R3：真实 openJiuwen Knowledge 的事实级索引与检索（零网络，Milvus Lite 本地文件）。

embedding 用显式 fixture 哈希实现：KB / chunker / vector store / retriever 仍是业务
同一套官方组件，索引回执与 allowlist 过滤都是真实链路；但**语义质量不属于本节结论**。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from zhijue_research.config import load_experiment_config
from zhijue_research.dataset.models import (
    CandidateBundle,
    CandidateFact,
    GeneratorCaseView,
    GroundTruth,
)
from zhijue_research.evidence import EvidenceError, parse_source_id
from zhijue_research.knowledge_provider import (
    FIXTURE_BACKEND,
    KnowledgeProvider,
    fixture_knowledge_settings,
)
from zhijue_research.retrieval import RetrievalObserver

CONFIG = load_experiment_config(
    Path(__file__).resolve().parents[1] / "config/experiment.yaml"
)

FACTS = (
    CandidateFact(
        fact_id="F01",
        context_id="proj_uart",
        predicate="used_technology",
        value="使用 STM32 HAL 与 DMA 完成串口接收",
        polarity="positive",
        confirmed=True,
        provenance_kind="dataset_authored",
        provenance_locator="private_kb/project_notes.md",
        verbatim="使用 STM32 HAL 与 DMA 完成串口接收",
    ),
    CandidateFact(
        fact_id="F02",
        context_id="proj_uart",
        predicate="responsibility",
        value="参与串口错帧排查，负责记录复现条件",
        polarity="positive",
        confirmed=True,
        provenance_kind="dataset_authored",
        provenance_locator="private_kb/project_notes.md",
        verbatim="参与串口错帧排查，负责记录复现条件",
    ),
    CandidateFact(
        fact_id="F03",
        context_id="proj_rtos",
        predicate="used_technology",
        value="使用 FreeRTOS Queue 在任务间传递采样数据",
        polarity="positive",
        confirmed=True,
        provenance_kind="dataset_authored",
        provenance_locator="private_kb/project_notes.md",
        verbatim="使用 FreeRTOS Queue 在任务间传递采样数据",
    ),
    CandidateFact(
        fact_id="F04",
        context_id="self",
        predicate="learning_status",
        value="仅上过 RTOS 课程实验，未在产品中使用 Mutex",
        polarity="uncertain",
        confirmed=True,
        provenance_kind="dataset_authored",
        provenance_locator="private_kb/profile_notes.md",
        verbatim="仅上过 RTOS 课程实验，未在产品中使用 Mutex",
    ),
    CandidateFact(
        fact_id="F05",
        context_id="proj_rtos",
        predicate="metric",
        value="未确认的队列深度数字",
        polarity="uncertain",
        confirmed=False,
        provenance_kind="dataset_authored",
        provenance_locator="private_kb/profile_notes.md",
        verbatim="未确认的队列深度数字",
    ),
)

CASE = GeneratorCaseView(
    case_id="case_retrieval",
    candidate_id="candidate_retrieval",
    split="pilot",
    question_wording="请说明你排查串口偶发错帧时用了哪些外设与工具。",
    competency_tags=("uart_debug",),
    turns=(("ans_main", "main", "我先记录复现条件，再看日志，分清串口还是数据处理。"),),
    retrieval_query_template="rq_1.0",
)

BUNDLE = CandidateBundle(
    ground_truth=GroundTruth(
        candidate_id="candidate_retrieval",
        domain="embedded_software",
        data_status="synthetic",
        facts=FACTS,
        trap_claims=(),
    ),
    cases=(),
    private_kb_documents={},
)


def _provider(
    tmp_path: Path, observer: RetrievalObserver | None = None
) -> KnowledgeProvider:
    return KnowledgeProvider(
        bundle=BUNDLE,
        config=CONFIG,
        generation="gen_cef-1.0.0",
        settings=fixture_knowledge_settings(),
        fixture_dimension=256,
        observer=observer,
    )


def test_fact_level_index_and_allowlisted_retrieval(
    tmp_path: Path, monkeypatch
) -> None:
    from zhijue_research import paths

    monkeypatch.setattr(paths, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(
        "zhijue_research.knowledge_provider.knowledge_dir", lambda: tmp_path
    )
    provider = _provider(tmp_path)

    async def go():
        await provider.ready()
        evidence = await provider.retrieve(CASE)
        block = provider.trace_block(evidence, expected_fact_ids=("F01", "F02"))
        receipt = dict(provider.index_receipt or {})
        await provider.close()
        return evidence, block, receipt

    evidence, block, receipt = asyncio.run(go())

    # 只有 confirmed 事实被索引；未确认的 F05 不可检索。
    indexed = set(receipt["source_ids"])
    assert receipt["generation"] == "gen_cef-1.0.0"
    assert receipt["embedding_logical_calls"] > 0
    assert {
        fact.source_id_for(candidate_id="candidate_retrieval") for fact in FACTS[:4]
    } == indexed
    assert "candidate_retrieval:F05" not in indexed
    assert evidence.items, "fixture 哈希 embedding 至少应命中原题相关来源"
    for item in evidence.items:
        assert item.source_id in indexed
        candidate_id, fact_id = parse_source_id(item.source_id)
        assert (candidate_id, fact_id) == ("candidate_retrieval", item.fact_id)
        assert item.rank >= 1
    assert block["config"]["kb_backend"] == FIXTURE_BACKEND
    assert block["config"]["embed_mode"] == "fixture"
    assert block["top_k"] == CONFIG.retrieval.top_k
    assert [hit["rank"] for hit in block["hits"]] == list(
        range(1, len(block["hits"]) + 1)
    )
    assert block["recall_at_k"] is None or 0.0 <= block["recall_at_k"] <= 1.0
    # 只保存 hash，不保存拼接后的 prompt。
    assert all(len(hit["text_hash"]) == 64 for hit in block["hits"])
    assert "query" in block and len(block["query_hash"]) == 64


def test_retrieval_observer_records_ordered_hits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "zhijue_research.knowledge_provider.knowledge_dir", lambda: tmp_path
    )
    observer = RetrievalObserver()
    provider = _provider(tmp_path, observer)

    async def go():
        await provider.ready()
        evidence = await provider.retrieve(CASE)
        await provider.close()
        return evidence

    evidence = asyncio.run(go())
    assert len(observer.events) == 1
    event = observer.events[0]
    assert event.case_id == CASE.case_id
    assert event.ordered_source_ids == evidence.source_ids()
    assert event.query_hash and event.top_k == CONFIG.retrieval.top_k
    assert {row["source_id"] for row in event.hits} == set(evidence.source_ids())


def test_live_embedding_requires_explicit_paid_call_authorization(
    tmp_path: Path, monkeypatch
) -> None:
    """只把 embed_mode 改成 live 不足以开始计费：必须同时显式打开 allow_paid_calls。"""

    from dataclasses import replace

    from zhijue_research.config import ExperimentConfigError
    from zhijue_research.knowledge_provider import build_provider

    monkeypatch.setattr(
        "zhijue_research.knowledge_provider.knowledge_dir", lambda: tmp_path
    )
    live_config = replace(
        replace(CONFIG, retrieval=replace(CONFIG.retrieval, embed_mode="live")),
        allow_paid_calls=False,
    )
    with pytest.raises(ExperimentConfigError, match="付费 embedding"):
        build_provider(BUNDLE, live_config)


def test_empty_confirmed_set_is_refused_not_silently_empty(
    tmp_path: Path, monkeypatch
) -> None:
    """没有 confirmed 事实就建 KB 是配置错误，必须响亮失败。"""

    from zhijue_research.dataset.models import InterviewCase

    monkeypatch.setattr(
        "zhijue_research.knowledge_provider.knowledge_dir", lambda: tmp_path
    )
    bundle = CandidateBundle(
        ground_truth=GroundTruth(
            candidate_id="candidate_empty",
            domain="embedded_software",
            data_status="synthetic",
            facts=tuple(fact for fact in FACTS if not fact.confirmed),
            trap_claims=(),
        ),
        cases=(
            InterviewCase(
                generator=CASE,
                evaluator=type(
                    "E",
                    (),
                    {
                        "case_id": CASE.case_id,
                        "expected_evidence_fact_ids": (),
                        "allowed_context_ids": ("proj_uart",),
                        "injected_drift": (),
                        "answer_style_rating": None,
                    },
                )(),
            ),
        ),
        private_kb_documents={},
    )
    provider = KnowledgeProvider(
        bundle=bundle,
        config=CONFIG,
        generation="gen_cef-1.0.0",
        settings=fixture_knowledge_settings(),
    )
    with pytest.raises(EvidenceError, match="拒绝建立空 KB"):
        asyncio.run(provider.ready())
