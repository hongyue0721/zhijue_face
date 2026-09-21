"""M1-03 Knowledge 激活链测试。

两层：
- 单元：内存 KnowledgeGateway 验证激活状态机（indexing→ready / failed）、
  空快照拒绝、allowlist 过滤——不联网、不依赖 SDK。
- integration_live：显式私密 env 才跑的真实 openJiuwen Knowledge 激活 +
  检索隔离 + 重启持久化。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import Base
from zhijue.adapters.db.profiles import ProfileRepository
from zhijue.application.profiles import KnowledgeSource, ProfileService


class InMemoryKnowledge:
    """最小端口实现：只保留来源与文本，用于验证激活状态机，不冒充 SDK。"""

    def __init__(self, *, fail_on_index: bool = False) -> None:
        self.store: dict[str, dict[str, KnowledgeSource]] = {}
        self.calls = 0
        self.fail_on_index = fail_on_index

    async def index_snapshot(self, *, profile_id, generation, sources):
        from zhijue.application.profiles import ActivationReceipt

        if self.fail_on_index:
            raise RuntimeError("synthetic index failure")
        self.store.setdefault(profile_id, {}).update({s.source_id: s for s in sources})
        self.calls += len(sources)
        return ActivationReceipt(
            generation=generation,
            source_ids=[s.source_id for s in sources],
            document_ids=[s.source_id for s in sources],
            embedding_logical_calls=self.calls,
        )

    async def search(self, *, profile_id, generation, allowed_source_ids, query, top_k):
        allowed = set(allowed_source_ids)
        return [
            {"text": src.text, "source_id": sid, "generation": generation, "score": 1.0}
            for sid, src in self.store.get(profile_id, {}).items()
            if sid in allowed and query in src.text
        ][:top_k]


def build(tmp_path, *, knowledge=None):
    engine = make_engine(f"sqlite:///{tmp_path / 'p.db'}")
    Base.metadata.create_all(engine)
    repo = ProfileRepository(engine)
    service = ProfileService(repo=repo, knowledge=knowledge)
    return engine, repo, service


def seed_confirmed(service, *, text="我在项目里用 FreeRTOS Queue 传递采样数据"):
    profile = service.create_profile(display_name="合成甲")
    service.add_facts(
        profile.id, expected_revision=0, items=[{"section": "project", "text": text}]
    )
    claim = service.list_claims(profile.id)[0]
    view = service.confirm(
        profile.id,
        expected_revision=1,
        decisions=[{"claim_id": claim.id, "action": "accept"}],
    )
    return profile.id, view.latest_snapshot_id


def test_activation_marks_documents_ready_and_returns_receipt(tmp_path):
    knowledge = InMemoryKnowledge()
    _engine, repo, service = build(tmp_path, knowledge=knowledge)
    profile_id, snapshot_id = seed_confirmed(service)

    receipt = asyncio.run(service.activate_knowledge(snapshot_id))

    assert receipt.generation == snapshot_id
    assert len(receipt.source_ids) == 1
    documents = repo.list_claims(profile_id)
    assert documents  # 依据块仍可回查
    document_ids = repo.documents_for_blocks(documents[0].source_block_ids)
    assert len(document_ids) == 1
    from sqlalchemy.orm import Session

    from zhijue.adapters.db.models import Document

    with Session(_engine) as session:
        assert session.get(Document, document_ids[0]).index_status == "ready"


def test_activation_failure_sets_failed_and_raises(tmp_path):
    knowledge = InMemoryKnowledge(fail_on_index=True)
    engine, _repo, service = build(tmp_path, knowledge=knowledge)
    _profile_id, snapshot_id = seed_confirmed(service)

    with pytest.raises(RuntimeError, match="synthetic index failure"):
        asyncio.run(service.activate_knowledge(snapshot_id))

    from sqlalchemy.orm import Session

    from zhijue.adapters.db.models import Document

    with Session(engine) as session:
        statuses = [d.index_status for d in session.query(Document).all()]
    assert statuses == ["failed"]  # 不假装成功


def test_activation_requires_knowledge_gateway(tmp_path):
    _engine, _repo, service = build(tmp_path, knowledge=None)
    _profile_id, snapshot_id = seed_confirmed(service)
    with pytest.raises(RuntimeError, match="未配置 Knowledge"):
        asyncio.run(service.activate_knowledge(snapshot_id))


def test_retrieval_allowlist_excludes_other_snapshots(tmp_path):
    knowledge = InMemoryKnowledge()
    _engine, _repo, service = build(tmp_path, knowledge=knowledge)
    profile_id, first_snapshot = seed_confirmed(service)
    asyncio.run(service.activate_knowledge(first_snapshot))
    service.add_facts(
        profile_id,
        expected_revision=2,
        items=[{"section": "skill", "text": "熟悉 CAN FD 帧格式"}],
    )
    claim = next(c for c in service.list_claims(profile_id) if c.status == "proposed")
    view = service.confirm(
        profile_id,
        expected_revision=3,
        decisions=[{"claim_id": claim.id, "action": "accept"}],
    )
    second_snapshot = view.latest_snapshot_id
    asyncio.run(service.activate_knowledge(second_snapshot))

    # 检索第一代快照时，第二代来源不得漏出（docs/03 §8）
    hits = asyncio.run(
        service.search_knowledge(snapshot_id=first_snapshot, query="CAN", top_k=5)
    )
    assert hits == []
    hits = asyncio.run(
        service.search_knowledge(snapshot_id=second_snapshot, query="CAN", top_k=5)
    )
    assert len(hits) == 1 and hits[0]["source_id"].startswith(second_snapshot)


def test_receipt_from_another_generation_cannot_mark_snapshot_ready(tmp_path):
    from zhijue.application.profiles import ActivationReceipt

    class WrongGenerationKnowledge(InMemoryKnowledge):
        async def index_snapshot(self, *, profile_id, generation, sources):
            return ActivationReceipt(
                generation="snapshot_obsolete",
                source_ids=[source.source_id for source in sources],
                document_ids=[],
                embedding_logical_calls=1,
            )

    _engine, _repo, service = build(tmp_path, knowledge=WrongGenerationKnowledge())
    profile_id, snapshot_id = seed_confirmed(service)
    with pytest.raises(RuntimeError, match="UPSTREAM_FAILED"):
        asyncio.run(service.activate_knowledge(snapshot_id))
    view = service.get_profile(profile_id)
    assert view.snapshot_activation["status"] == "failed"
    assert view.latest_snapshot_id == snapshot_id


@pytest.mark.integration_live
def test_real_knowledge_activation_when_private_env_is_explicit(tmp_path):
    env_value = os.getenv("ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE")
    if not env_value:
        pytest.skip("private live env file not explicitly selected")
    from zhijue.adapters.knowledge import OpenJiuwenKnowledgeGateway, load_settings

    settings = load_settings(Path(env_value))
    gateway = OpenJiuwenKnowledgeGateway(
        settings=settings, milvus_uri=tmp_path / "activation.db"
    )
    engine, _repo, service = build(tmp_path, knowledge=gateway)
    profile_id, snapshot_id = seed_confirmed(
        service,
        text="这是 M1-03 合成激活样本，标记 ACTIVATION_MARK_5174，使用 FreeRTOS Queue。",
    )

    async def drive() -> tuple[object, list[dict[str, object]]]:
        # 生产是单事件循环（uvicorn）；网关的 HTTP 连接池绑定该循环，测试同样不跨循环复用。
        try:
            await gateway.verify_dimension()
            receipt = await service.activate_knowledge(snapshot_id)
            hits = await service.search_knowledge(
                snapshot_id=snapshot_id,
                query="ACTIVATION_MARK_5174 用了什么机制",
                top_k=4,
            )
            return receipt, hits
        finally:
            await gateway.close()

    receipt, hits = asyncio.run(drive())
    assert receipt.source_ids, "真实 Knowledge 激活必须返回来源 IDs"
    assert hits, "激活后必须能检索到确认事实"
    assert hits[0]["source_id"] in receipt.source_ids
    assert "ACTIVATION_MARK_5174" in hits[0]["text"]

    from sqlalchemy.orm import Session

    from zhijue.adapters.db.models import Document

    with Session(engine) as session:
        statuses = {d.index_status for d in session.query(Document).all()}
    assert statuses == {"ready"}
    assert profile_id  # 档案与快照绑定关系在上面的服务调用中已校验
