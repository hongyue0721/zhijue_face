"""Candidate Private KB 的事实级检索：复用真实 openJiuwen Knowledge 网关。

- 每条 confirmed fact = 一个 knowledge source，`source_id = "{candidate_id}:{fact_id}"`，
  任何一条证据都能反查到"候选人的第几条事实"。
- query 由 `interview question + raw answer` 确定性构造，模板版本进 trace。
- ground truth 的结构字段与 trap claims 永不进入索引：只有 `confirmed=true` 的事实被索引。
- RetrievalObserver：每次检索产出一条 `retrieval.result` 事件（run_id/case_id/config/query/
  top_k/有序命中/score/text hash），因此论文可以把失败分成
  A. Retrieval Failure（正确证据没被取回）与 B. Generation Failure（取回了却仍编造）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from zhijue.adapters.knowledge import OpenJiuwenKnowledgeGateway
from zhijue.application.profiles import KnowledgeSource

from zhijue_research.dataset.models import CandidateFact, GeneratorCaseView
from zhijue_research.embeddings import FixtureHashEmbedding
from zhijue_research.evidence import (
    EvidenceError,
    EvidenceItem,
    EvidenceSet,
    claim_ref_for,
    parse_source_id,
)
from zhijue_research.io_utils import sha256_text

#: 检索 query 模板；改动必须升版本号，trace 记录版本，避免"悄悄换 query"。
QUERY_TEMPLATE_VERSION = "rq_1.0"


def build_retrieval_query(case: GeneratorCaseView) -> str:
    """确定性 query：题面 + 候选人原话。不改写、不扩展、不看真值标签。"""

    return f"{case.question_wording}\n{case.answer_text()}"


class RetrievalProvider(Protocol):
    """runner 使用的检索端口。"""

    async def ready(self) -> None: ...

    async def retrieve(self, case: GeneratorCaseView) -> EvidenceSet: ...

    def trace_block(
        self, evidence: EvidenceSet, *, expected_fact_ids: Sequence[str] = ()
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class RetrievalEvent:
    """`retrieval.result` 旁路事件（只读观测，不参与决策）。"""

    case_id: str
    query: str
    query_hash: str
    top_k: int
    embed_mode: str
    ordered_source_ids: tuple[str, ...]
    hits: tuple[dict[str, Any], ...]


class RetrievalObserver:
    """收集 retrieval.result；只做记录，绝不改动命中结果。"""

    def __init__(self) -> None:
        self.events: list[RetrievalEvent] = []
        self.failures = 0

    def on_result(self, event: RetrievalEvent) -> None:
        try:
            self.events.append(event)
        except Exception:  # noqa: BLE001 - 观测失败不得影响实验
            self.failures += 1


@dataclass(slots=True)
class CandidateKnowledge:
    """一个 candidate 一个 KB（profile_id=candidate_id），一个数据集版本一个 generation。"""

    gateway: OpenJiuwenKnowledgeGateway
    candidate_id: str
    generation: str
    embed_mode: str
    observer: RetrievalObserver | None = None
    _indexed: tuple[str, ...] = field(default=(), init=False)
    index_receipt: dict[str, Any] | None = field(default=None, init=False)

    @classmethod
    def build(
        cls,
        *,
        candidate_id: str,
        generation: str,
        settings,
        milvus_uri: Path,
        top_k: int,
        embed_mode: str,
        embed_model: Any | None = None,
        fixture_dimension: int = 256,
        observer: RetrievalObserver | None = None,
    ) -> CandidateKnowledge:
        """构造真实 openJiuwen KB。

        `embed_model=None` 时由网关按私密配置构造 `OpenAIEmbedding`；fixture 模式注入
        确定性哈希 embedding（明确标注，仅用于结构与归因链路验证）。
        """

        if embed_mode not in {"live", "fixture"}:
            raise ValueError(f"未知 embed_mode：{embed_mode}")
        model = embed_model
        if embed_mode == "fixture" and model is None:
            model = FixtureHashEmbedding(dimension=fixture_dimension)
        gateway = OpenJiuwenKnowledgeGateway(
            settings=settings, milvus_uri=milvus_uri, top_k=top_k, embed_model=model
        )
        return cls(
            gateway=gateway,
            candidate_id=candidate_id,
            generation=generation,
            embed_mode=embed_mode,
            observer=observer,
        )

    async def verify_ready(self) -> None:
        """维度契约：live 会真实探测远端 embedding；fixture 只做本地维度自检。"""

        await self.gateway.verify_dimension()

    async def index_facts(self, facts: Sequence[CandidateFact]) -> dict[str, Any]:
        confirmed = [fact for fact in facts if fact.confirmed]
        if not confirmed:
            raise EvidenceError("没有可索引的 confirmed 事实，拒绝建立空 KB")
        sources = [
            KnowledgeSource(
                source_id=fact.source_id_for(candidate_id=self.candidate_id),
                text=fact.value,
            )
            for fact in confirmed
        ]
        receipt = await self.gateway.index_snapshot(
            profile_id=self.candidate_id, generation=self.generation, sources=sources
        )
        self._indexed = tuple(receipt.source_ids)
        self.index_receipt = {
            "generation": receipt.generation,
            "source_ids": list(receipt.source_ids),
            "embedding_logical_calls": receipt.embedding_logical_calls,
        }
        return self.index_receipt

    async def retrieve(self, case: GeneratorCaseView, *, top_k: int) -> EvidenceSet:
        evidence, _ = await self.retrieve_with_hits(case, top_k=top_k)
        return evidence

    async def retrieve_with_hits(
        self, case: GeneratorCaseView, *, top_k: int
    ) -> tuple[EvidenceSet, tuple[dict[str, Any], ...]]:
        if not self._indexed:
            raise EvidenceError("KB 未索引，拒绝检索")
        query = build_retrieval_query(case)
        hits = await self.gateway.search(
            profile_id=self.candidate_id,
            generation=self.generation,
            allowed_source_ids=list(self._indexed),
            query=query,
            top_k=top_k,
        )
        items: list[EvidenceItem] = []
        rows: list[dict[str, Any]] = []
        for rank, hit in enumerate(hits, start=1):
            source_id = str(hit["source_id"])
            candidate_id, fact_id = parse_source_id(source_id)
            if candidate_id != self.candidate_id:
                raise EvidenceError(f"CROSS_CANDIDATE_SOURCE: {source_id}")
            text = str(hit["text"])
            generation = hit.get("generation")
            chunk_id = hit.get("chunk_id")
            score = hit.get("score")
            items.append(
                EvidenceItem(
                    source_id=source_id,
                    text=text,
                    fact_id=fact_id,
                    rank=rank,
                    score=float(score) if isinstance(score, (int, float)) else None,
                    generation=str(generation) if generation is not None else None,
                    chunk_id=str(chunk_id) if chunk_id is not None else None,
                )
            )
            rows.append(
                {
                    "rank": rank,
                    "source_id": source_id,
                    "fact_id": fact_id,
                    "claim_ref": claim_ref_for(source_id),
                    "generation": str(generation) if generation is not None else None,
                    "chunk_id": str(chunk_id) if chunk_id is not None else None,
                    "score": float(score) if isinstance(score, (int, float)) else None,
                    "text_hash": sha256_text(text),
                }
            )
        evidence = EvidenceSet(
            candidate_id=self.candidate_id, query=query, top_k=top_k, items=tuple(items)
        )
        evidence.require_candidate()
        if self.observer is not None:
            self.observer.on_result(
                RetrievalEvent(
                    case_id=case.case_id,
                    query=query,
                    query_hash=sha256_text(query),
                    top_k=top_k,
                    embed_mode=self.embed_mode,
                    ordered_source_ids=evidence.source_ids(),
                    hits=tuple(rows),
                )
            )
        return evidence, tuple(rows)

    def trace_block(
        self,
        evidence: EvidenceSet,
        hits: Sequence[dict[str, Any]],
        *,
        expected_fact_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        """检索中间结果块。

        `expected_fact_ids` 只由离线聚合阶段注入（生成阶段传空），召回率因此是
        离线算出来的，不是生成时"知道答案"后填进去的。
        """

        rows = [dict(row) for row in hits]
        retrieved = {str(row["fact_id"]) for row in rows}
        expected = [str(item) for item in expected_fact_ids]
        recall = (
            None if not expected else len(retrieved & set(expected)) / len(expected)
        )
        return {
            "config": {
                "query_template_version": QUERY_TEMPLATE_VERSION,
                "embed_mode": self.embed_mode,
                "kb_backend": "openjiuwen_simple_knowledge_base+milvus_lite",
            },
            "query": evidence.query,
            "query_hash": sha256_text(evidence.query),
            "top_k": evidence.top_k,
            "hits": rows,
            "expected_evidence_fact_ids": expected or None,
            "recall_at_k": recall,
        }

    async def close(self) -> None:
        await self.gateway.close()
