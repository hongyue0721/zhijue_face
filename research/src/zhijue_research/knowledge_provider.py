"""runner 用的检索供给：真实 openJiuwen KB（live embedding）与离线 fixture。

`embed_mode=fixture` 完全离线：embedding 换成确定性哈希实现，KB / chunker /
Milvus Lite vector store / retriever 仍是业务同一套官方组件，结果只能用于
结构与归因链路验证，**不能**用于 Retrieval Failure 结论。
`embed_mode=live` 复用 `zhijue.adapters.knowledge` 的 `OpenAIEmbedding` 构造路径。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zhijue.adapters.knowledge import KnowledgeSettings

from zhijue_research.config import ExperimentConfig, ExperimentConfigError
from zhijue_research.dataset.models import CandidateBundle, GeneratorCaseView
from zhijue_research.evidence import EvidenceSet
from zhijue_research.io_utils import require_private_file
from zhijue_research.paths import knowledge_dir
from zhijue_research.retrieval import (
    CandidateKnowledge,
    RetrievalEvent,
    RetrievalObserver,
)

#: fixture 模式下写入 trace 的 kb_backend，明确区别于 live。
FIXTURE_BACKEND = "openjiuwen_simple_knowledge_base+milvus_lite+hash_embedding"
LIVE_BACKEND = (
    "openjiuwen_simple_knowledge_base+milvus_lite+openai_compatible_embedding"
)


def fixture_knowledge_settings(*, dimension: int = 256) -> KnowledgeSettings:
    """离线 fixture 配置：端点与密钥都是显式假值，且永不发起网络。

    这是刻意标注的 fixture，不是"可用的 embedding 服务"；`verify_ready()` 只用来
    断言维度契约一致（fixture embedding 的 dimension 是本地属性）。
    """

    return KnowledgeSettings(
        embedding_provider="openjiuwen_api",
        embedding_model="fixture-hash-embedding-1.0.0",
        embedding_api_base="https://fixture.invalid/v1",
        embedding_api_key="fixture-not-a-secret",
        embedding_timeout=30,
        embedding_max_retries=1,
        embedding_expected_dimension=dimension,
    )


def live_knowledge_settings(env_file: Path | str) -> KnowledgeSettings:
    """真实 embedding：沿用业务侧 0600 私密文件与 HTTPS 校验。"""

    from zhijue.adapters.knowledge import load_settings

    return load_settings(require_private_file(Path(str(env_file)).expanduser()))


@dataclass(slots=True)
class KnowledgeProvider:
    """一个 candidate 一个 KB；每 case 只检索一次，M2/M3 共用同一结果（I4）。"""

    bundle: CandidateBundle
    config: ExperimentConfig
    generation: str
    settings: KnowledgeSettings
    embed_model: Any | None = None
    fixture_dimension: int = 256
    observer: RetrievalObserver | None = field(default=None)
    _knowledge: CandidateKnowledge | None = field(default=None, init=False)
    _last_hits: tuple[dict[str, Any], ...] = field(default=(), init=False)
    retrieve_calls: int = field(default=0, init=False)

    @property
    def embed_mode(self) -> str:
        return self.config.retrieval.embed_mode

    @property
    def index_receipt(self) -> dict[str, Any] | None:
        return self._knowledge.index_receipt if self._knowledge is not None else None

    @property
    def backend(self) -> str:
        return LIVE_BACKEND if self.embed_mode == "live" else FIXTURE_BACKEND

    async def ready(self) -> None:
        if self._knowledge is not None:
            return
        candidate_id = self.bundle.ground_truth.candidate_id
        milvus_uri = (
            Path(knowledge_dir()) / f"{candidate_id}_{self.config.dataset_version}.db"
        )
        self._knowledge = CandidateKnowledge.build(
            candidate_id=candidate_id,
            generation=self.generation,
            settings=self.settings,
            milvus_uri=milvus_uri,
            top_k=self.config.retrieval.top_k,
            embed_mode=self.embed_mode,
            embed_model=self.embed_model,
            fixture_dimension=self.fixture_dimension,
            observer=self.observer,
        )
        await self._knowledge.verify_ready()
        await self._knowledge.index_facts(self.bundle.ground_truth.confirmed_facts())

    async def retrieve(self, case: GeneratorCaseView) -> EvidenceSet:
        if self._knowledge is None:
            await self.ready()
        assert self._knowledge is not None
        self.retrieve_calls += 1
        evidence, hits = await self._knowledge.retrieve_with_hits(
            case, top_k=self.config.retrieval.top_k
        )
        self._last_hits = hits
        return evidence

    def trace_block(
        self, evidence: EvidenceSet, *, expected_fact_ids: Sequence[str] = ()
    ) -> dict[str, Any]:
        assert self._knowledge is not None, "检索前必须先 ready()"
        block = self._knowledge.trace_block(
            evidence, self._last_hits, expected_fact_ids=expected_fact_ids
        )
        block["config"]["kb_backend"] = self.backend
        return block

    @property
    def retrieval_events(self) -> list[RetrievalEvent]:
        return list(self.observer.events) if self.observer is not None else []

    async def close(self) -> None:
        if self._knowledge is not None:
            await self._knowledge.close()
            self._knowledge = None


def build_provider(
    bundle: CandidateBundle,
    config: ExperimentConfig,
    *,
    observer: RetrievalObserver | None = None,
) -> KnowledgeProvider:
    """按配置构造 provider；fixture 零网络，live 必须给私密 env 路径。

    live embedding 与 live chat 一样是花钱的外部调用，所以共用同一个显式授权开关：
    只把 `embed_mode` 改成 live 不足以开始计费，必须同时打开 `allow_paid_calls`。
    """

    if config.retrieval.embed_mode == "live":
        if not config.allow_paid_calls:
            raise ExperimentConfigError(
                "embed_mode=live 会调用付费 embedding：确认预算后显式设置 "
                "allow_paid_calls=true，或改用 scripts/live_embedding_probe.py 的确认开关。"
            )
        settings = live_knowledge_settings(config.retrieval.embed_env_file)
        embed_model = None
    else:
        settings = fixture_knowledge_settings()
        embed_model = None  # CandidateKnowledge.build 内部构造 fixture embedding
    return KnowledgeProvider(
        bundle=bundle,
        config=config,
        generation=f"gen_{config.dataset_version}",
        settings=settings,
        embed_model=embed_model,
        observer=observer or RetrievalObserver(),
    )
