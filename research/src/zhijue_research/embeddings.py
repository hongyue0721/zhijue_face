"""embedding 选择：live 用现有 openJiuwen OpenAIEmbedding，fixture 用确定性哈希向量。

研究 harness 允许注入 openJiuwen `Embedding` 实现，但 KB / chunker / Milvus Lite
vector store / retriever 仍然是业务同一套官方组件——不自建向量检索替身。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from openjiuwen.core.foundation.store.base_embedding import Embedding


class FixtureHashEmbedding(Embedding):
    """确定性 token-hash 向量：只用于结构验证，**不具备语义**。

    用它得到的任何检索结果都只能证明"索引/来源映射/事件记录可用"，
    不能用于 Retrieval Failure 归因，也不能作为论文证据。
    """

    def __init__(
        self, *, dimension: int = 256, model_name: str = "fixture-hash-embedding-1.0.0"
    ):
        if dimension < 32:
            raise ValueError("fixture embedding 维度至少 32")
        self._dimension = dimension
        self.model_name = model_name
        self.embed_calls = 0

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_query(self, text: str, **kwargs: Any) -> list[float]:
        self.embed_calls += 1
        return self._vector(text)

    async def embed_documents(
        self,
        texts: list[str],
        batch_size: int | None = None,
        **kwargs: Any,
    ) -> list[list[float]]:
        del batch_size
        self.embed_calls += len(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        """字符 3-gram hash 命中维度桶并 L2 归一化：同文本恒等，可复现。"""

        buckets = [0.0] * self._dimension
        normalized = text.lower()
        for start in range(max(len(normalized) - 2, 0)):
            gram = normalized[start : start + 3]
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            buckets[int.from_bytes(digest[:8], "big") % self._dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0.0:
            buckets[0] = 1.0
            return buckets
        return [value / norm for value in buckets]


def load_live_embedding(env_file):  # pragma: no cover - 需要私密配置
    """复用业务构造：同一 `KnowledgeSettings` 校验（HTTPS、/v1、0600）。"""

    from zhijue.adapters.knowledge import build_embedding, load_settings

    return build_embedding(load_settings(env_file))
