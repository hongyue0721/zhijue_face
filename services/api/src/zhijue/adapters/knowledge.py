"""Knowledge 端口的真实实现：openJiuwen SimpleKnowledgeBase + Milvus Lite。

本模块是 Knowledge 构造的唯一权威（`smoke.knowledge` 复用它做 M0-03 探针），
保证生产链路与已验证探针使用同一套组件、同一环境契约。
密钥只从显式私有 env 文件读取，不外泄、不打印。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from openjiuwen.core.foundation.store.base_embedding import EmbeddingConfig
from openjiuwen.core.foundation.store.vector_fields.milvus_fields import MilvusFLAT
from openjiuwen.core.retrieval import (
    KnowledgeBaseConfig,
    RetrievalConfig,
    SimpleKnowledgeBase,
    VectorStoreConfig,
)
from openjiuwen.core.retrieval.common.document import Document
from openjiuwen.core.retrieval.embedding.openai_embedding import OpenAIEmbedding
from openjiuwen.core.retrieval.indexing.indexer.milvus_indexer import MilvusIndexer
from openjiuwen.core.retrieval.indexing.processor.chunker import CharChunker
from openjiuwen.core.retrieval.indexing.processor.parser import TxtMdParser
from openjiuwen.core.retrieval.vector_store.milvus_store import MilvusVectorStore
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CHUNK_SIZE = 300
CHUNK_OVERLAP = 40

# 生产链路实际使用的官方组件清单（M0-03 探针的 sdk_sources 证据直接用这份，
# 防止"探针记录的组件"与"应用实际导入的组件"漂移）。
SDK_COMPONENTS = (
    OpenAIEmbedding,
    SimpleKnowledgeBase,
    TxtMdParser,
    CharChunker,
    MilvusVectorStore,
    MilvusIndexer,
)


class KnowledgeSettings(BaseSettings):
    """embedding/Knowledge 环境契约；密钥值只在内存中使用。"""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    embedding_provider: Literal["openjiuwen_api"]
    embedding_model: str = Field(min_length=1)
    embedding_api_base: str = Field(min_length=1)
    embedding_api_key: SecretStr
    embedding_timeout: int = Field(default=30, ge=1, le=120)
    embedding_max_retries: int = Field(default=1, ge=1, le=3)
    embedding_expected_dimension: int = Field(default=1024, ge=1, le=65536)

    @field_validator("embedding_model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("EMBEDDING_MODEL must not be empty")
        return value

    @field_validator("embedding_api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("EMBEDDING_API_KEY must not be empty")
        return value

    @field_validator("embedding_api_base")
    @classmethod
    def validate_api_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme != "https":
            raise ValueError("EMBEDDING_API_BASE must use HTTPS")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("EMBEDDING_API_BASE must have a plain host")
        if parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/v1":
            raise ValueError(
                "EMBEDDING_API_BASE must be the explicit OpenAI-compatible /v1 base"
            )
        return value

    def public_summary(self) -> dict[str, Any]:
        parsed = urlsplit(self.embedding_api_base)
        return {
            "provider": self.embedding_provider,
            "model": self.embedding_model,
            "api_origin": f"{parsed.scheme}://{parsed.netloc}",
            "api_route": "v1/embeddings",
            "timeout_seconds": self.embedding_timeout,
            "max_retries": self.embedding_max_retries,
            "expected_dimension": self.embedding_expected_dimension,
            "api_key_configured": bool(self.embedding_api_key.get_secret_value()),
        }


def load_settings(env_file: Path) -> KnowledgeSettings:
    """只读一个显式私有 env 文件；绝不回退到隐式密钥。"""
    import stat

    path = env_file.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("private env file does not exist")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(
            "private env file must not be accessible by group or others"
        )
    return KnowledgeSettings(_env_file=path, _env_file_encoding="utf-8")


def build_embedding(settings: KnowledgeSettings) -> OpenAIEmbedding:
    config = EmbeddingConfig(
        model_name=settings.embedding_model,
        base_url=settings.embedding_api_base,
        api_key=settings.embedding_api_key.get_secret_value(),
    )
    return OpenAIEmbedding(
        config,
        timeout=settings.embedding_timeout,
        max_retries=settings.embedding_max_retries,
        max_batch_size=8,
        max_concurrent=2,
    )


def build_knowledge_base(
    settings: KnowledgeSettings,
    milvus_uri: Path,
    kb_id: str,
    *,
    embed_model: OpenAIEmbedding | None = None,
) -> SimpleKnowledgeBase:
    """只用官方 openJiuwen Knowledge 组件构造，无同名本地替身。"""
    collection_name = f"kb_{kb_id}_chunks"
    store_config = VectorStoreConfig(
        store_provider="milvus",
        database_name="default",
        collection_name=collection_name,
        distance_metric="cosine",
    )
    vector_store = MilvusVectorStore(
        store_config,
        milvus_uri=str(milvus_uri),
        vector_field=MilvusFLAT(),
    )
    indexer = MilvusIndexer(
        store_config,
        milvus_uri=str(milvus_uri),
        vector_field=MilvusFLAT(),
    )
    return SimpleKnowledgeBase(
        KnowledgeBaseConfig(
            kb_id=kb_id,
            index_type="vector",
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        ),
        vector_store=vector_store,
        embed_model=embed_model or build_embedding(settings),
        parser=TxtMdParser(),
        chunker=CharChunker(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP),
        index_manager=indexer,
    )


@dataclass(frozen=True)
class RetrievalHit:
    """一条检索结果及其来源映射（docs/03 §5.4：chunk 必须能回到来源）。"""

    text: str
    doc_id: str
    source_id: str
    generation: str
    chunk_id: str
    score: float


class OpenJiuwenKnowledgeGateway:
    """ProfileService 的 Knowledge 端口实现：按 profile 一个 KB，按快照一代文档。

    激活回执校验：写完后用来源文本回查，命中且来源元数据一致才认为写入成功；
    检索在返回前按当前快照 allowlist 过滤，旧快照/已删除内容不会漏出。
    """

    def __init__(
        self,
        *,
        settings: KnowledgeSettings,
        milvus_uri: Path,
        top_k: int = 4,
        embed_model: Any | None = None,
    ) -> None:
        """`embed_model=None` 保持生产行为：按私密配置构造 openJiuwen OpenAIEmbedding。

        研究 harness 允许注入另一份 openJiuwen `Embedding` 实现（例如 fixture 模式），
        但 KB/index/retrieval 仍是同一套官方组件，不自建向量检索替身。
        """

        self._settings = settings
        self._milvus_uri = milvus_uri
        self._top_k = top_k
        self._embedding = embed_model if embed_model is not None else build_embedding(settings)
        self._bases: dict[str, SimpleKnowledgeBase] = {}
        self._logical_calls = 0

    @property
    def embedding_logical_calls(self) -> int:
        return self._logical_calls

    async def verify_dimension(self) -> int:
        import asyncio

        dimension = await asyncio.to_thread(lambda: self._embedding.dimension)
        if dimension != self._settings.embedding_expected_dimension:
            raise RuntimeError(
                "embedding dimension does not match the frozen model contract"
            )
        return dimension

    def _kb(
        self, profile_id: str, embed_model: OpenAIEmbedding | None = None
    ) -> SimpleKnowledgeBase:
        base = self._bases.get(profile_id)
        if base is None:
            base = build_knowledge_base(
                self._settings,
                self._milvus_uri,
                f"zhijue_{profile_id}",
                embed_model=embed_model or self._embedding,
            )
            self._bases[profile_id] = base
        return base

    async def index_snapshot(
        self, *, profile_id: str, generation: str, sources: list[Any]
    ) -> Any:
        from zhijue.application.profiles import ActivationReceipt

        if not sources:
            raise ValueError("没有可激活的来源，拒绝写入空快照")
        kb = self._kb(profile_id)
        documents = [
            Document(
                id_=source.source_id,
                text=source.text,
                metadata={
                    "source_id": source.source_id,
                    "profile_id": profile_id,
                    "generation": generation,
                    "data_mode": "user_confirmed",
                },
            )
            for source in sources
        ]
        document_ids = await kb.add_documents(documents)
        if document_ids != [source.source_id for source in sources]:
            raise RuntimeError("add_documents 返回的 ID 与提交来源不一致")
        self._logical_calls += len(sources)
        # 回执校验：写入后必须能按来源文本回查到自己（不是"调用没报错"就算成功）。
        for source in sources:
            hits = await self._retrieve(
                kb, source.text, top_k=max(self._top_k, len(sources))
            )
            matched = [
                hit for hit in hits if hit.metadata.get("source_id") == source.source_id
            ]
            if not matched:
                raise RuntimeError(f"索引回执校验失败：{source.source_id} 回查不到")
            if not any(
                source.text[:20] in hit.text or hit.text[:20] in source.text
                for hit in matched
            ):
                raise RuntimeError(f"索引回执校验失败：{source.source_id} 内容不匹配")
        return ActivationReceipt(
            generation=generation,
            source_ids=[source.source_id for source in sources],
            document_ids=document_ids,
            embedding_logical_calls=self._logical_calls,
        )

    async def search(
        self,
        *,
        profile_id: str,
        generation: str,
        allowed_source_ids: list[str],
        query: str,
        top_k: int,
    ) -> list[dict[str, object]]:
        kb = self._kb(profile_id)
        results = await self._retrieve(kb, query, top_k=max(top_k, self._top_k))
        allowed = set(allowed_source_ids)
        hits: list[dict[str, object]] = []
        for result in results:
            metadata = result.metadata or {}
            source_id = metadata.get("source_id")
            if source_id not in allowed:
                continue  # 非当前快照允许的来源一律丢弃（旧版本/已删除）
            hits.append(
                {
                    "text": result.text,
                    "doc_id": result.doc_id,
                    "source_id": source_id,
                    "generation": metadata.get("generation"),
                    "chunk_id": metadata.get("chunk_id"),
                    "score": result.score,
                }
            )
        return hits[:top_k]

    async def drop_profile(self, *, profile_id: str, source_ids: list[str]) -> int:
        """删除该档案全部已激活来源（SDK delete_documents，M0-03 已验证生命周期）。

        失败必须抛错让 operation 落 failed 走显式重试，不得当作已清理；
        从未建过 KB 且无来源时是 no-op。重复删除同一 source_id 幂等。
        """
        base = self._bases.pop(profile_id, None)
        if not source_ids:
            if base is not None:
                await base.close()
            return 0
        kb = base if base is not None else self._kb(profile_id)
        try:
            success = await kb.delete_documents(list(source_ids))
            if not success:
                raise RuntimeError("openJiuwen delete_documents failed")
            kb.index_manager.client.flush(f"kb_zhijue_{profile_id}_chunks")
        finally:
            await kb.close()
        return len(source_ids)

    async def _retrieve(
        self, kb: SimpleKnowledgeBase, query: str, *, top_k: int
    ) -> list[Any]:
        results = await kb.retrieve(query, RetrievalConfig(top_k=top_k))
        self._logical_calls += 1
        return list(results)

    async def close(self) -> None:
        for base in self._bases.values():
            await base.close()
        self._bases.clear()
