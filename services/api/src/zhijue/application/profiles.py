"""ProfileService：手填事实 → proposed Claim → 用户确认 → 不可变快照 → Knowledge 激活。

职责边界（AGENTS §2/§10）：这里只落"用户叙述的确认"与索引激活，
不判断能力、不自动给 Claim 提级为"已验证事实"；
自动提议 Claim（P-EXTRACT）属模型接线，M2+ 才接入。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from zhijue.adapters.db.operations import OperationCommand
from zhijue.adapters.db.profiles import (
    AcceptedProfileOperation,
    ProfileRepository,
    ProfileView,
    RevisionConflict,
)
from zhijue.domain.claims import ClaimStatus
from zhijue.domain.errors import InvalidStateError

FACT_SECTIONS = ("basic", "education", "project", "skill", "award", "other")

MAX_FACTS_PER_REQUEST = 50
MAX_CHARS_PER_FACT = 2_000
MAX_FACT_CHARS_PER_REQUEST = 30_000


@dataclass(frozen=True)
class ClaimView:
    id: str
    text: str
    status: ClaimStatus
    source_block_ids: list[str]
    source_quotes: list[dict[str, str]]
    supersedes_id: str | None


@dataclass(frozen=True)
class SnapshotView:
    id: str
    profile_id: str
    revision: int
    confirmed_claim_ids: list[str]
    display_fields: dict[str, list[str]]
    created_at: str


@dataclass(frozen=True)
class KnowledgeSource:
    """一条待激活的来源文本；source_id 是检索 allowlist 的唯一键。"""

    source_id: str
    text: str


@dataclass(frozen=True)
class ActivationReceipt:
    generation: str
    source_ids: list[str]
    document_ids: list[str]
    embedding_logical_calls: int


class KnowledgeGateway(Protocol):
    """Knowledge 端口：真实实现是 openJiuwen SimpleKnowledgeBase，测试用内存实现。"""

    async def index_snapshot(
        self, *, profile_id: str, generation: str, sources: list[KnowledgeSource]
    ) -> ActivationReceipt: ...

    async def search(
        self,
        *,
        profile_id: str,
        generation: str,
        allowed_source_ids: list[str],
        query: str,
        top_k: int,
    ) -> list[dict[str, object]]: ...

    async def drop_profile(self, *, profile_id: str, source_ids: list[str]) -> int: ...


class ProfileService:
    def __init__(
        self, *, repo: ProfileRepository, knowledge: KnowledgeGateway | None = None
    ) -> None:
        self._repo = repo
        self._knowledge = knowledge

    # ---------- 档案与事实 ----------

    def create_profile(
        self, *, display_name: str, synthetic: bool = True
    ) -> ProfileView:
        if not display_name.strip():
            raise ValueError("display_name 不能为空")
        return self._repo.create(display_name=display_name.strip(), synthetic=synthetic)

    def get_profile(self, profile_id: str) -> ProfileView:
        view = self._repo.get_view(profile_id)
        if view is None:
            raise ValueError(f"RESOURCE_NOT_FOUND: profile {profile_id}")
        return view

    def add_facts(
        self, profile_id: str, *, expected_revision: int, items: list[dict[str, str]]
    ) -> ProfileView:
        """校验全部发生在写入之前（api.md §4）：不合法请求不推进 revision。"""
        if not items:
            raise ValueError("items 不能为空")
        if len(items) > MAX_FACTS_PER_REQUEST:
            raise ValueError(f"一次最多 {MAX_FACTS_PER_REQUEST} 条手填事实")
        total = 0
        pairs: list[tuple[str, str]] = []
        for item in items:
            section = item.get("section", "")
            text = (item.get("text") or "").strip()
            if section not in FACT_SECTIONS:
                raise ValueError(f"section 非法：{section!r}")
            if not text:
                raise ValueError("text 不能为空")
            if len(text) > MAX_CHARS_PER_FACT:
                raise ValueError(f"单条事实最多 {MAX_CHARS_PER_FACT} 字符")
            total += len(text)
            pairs.append((section, text))
        if total > MAX_FACT_CHARS_PER_REQUEST:
            raise ValueError(f"单次合计最多 {MAX_FACT_CHARS_PER_REQUEST} 字符")
        return self._repo.add_facts(
            profile_id=profile_id, expected_revision=expected_revision, items=pairs
        )

    # ---------- 确认 ----------

    def list_claims(self, profile_id: str) -> list[ClaimView]:
        return [
            ClaimView(
                id=claim.id,
                text=claim.text,
                status=ClaimStatus(claim.status),
                source_block_ids=list(claim.source_block_ids or []),
                source_quotes=list(claim.source_quotes or []),
                supersedes_id=claim.supersedes_id,
            )
            for claim in self._repo.list_claims(profile_id)
        ]

    def confirm(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        decisions: list[dict[str, str]],
    ) -> ProfileView:
        if not decisions:
            raise ValueError("decisions 不能为空")
        view, _snapshot = self._repo.confirm(
            profile_id=profile_id,
            expected_revision=expected_revision,
            decisions=decisions,
        )
        return view

    def accept_confirmation(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        decisions: list[dict[str, str]],
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        return self._repo.accept_confirmation(
            profile_id,
            expected_revision=expected_revision,
            decisions=decisions,
            command=command,
            capacity_available=capacity_available,
        )

    def accept_activation(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        return self._repo.accept_activation(
            profile_id,
            expected_revision=expected_revision,
            command=command,
            capacity_available=capacity_available,
        )

    def accept_retry(
        self,
        operation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_input: dict[str, Any],
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        return self._repo.accept_retry(
            operation_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_input=request_input,
            capacity_available=capacity_available,
        )

    def accept_deletion(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        command: OperationCommand,
        capacity_available: bool,
    ) -> AcceptedProfileOperation:
        return self._repo.accept_deletion(
            profile_id,
            expected_revision=expected_revision,
            command=command,
            capacity_available=capacity_available,
        )

    async def process_deletion(self, profile_id: str) -> dict[str, Any]:
        """后台清理：先删 Knowledge 索引，再级联删业务行。

        索引删除失败时不动数据库（档案保持 deleting），operation 落 failed
        可显式重试；两步都成功才物理删除档案行，不留“看起来删了但索引还在”
        的不一致状态。
        """
        source_ids = self._repo.knowledge_source_ids(profile_id)
        dropped = 0
        if source_ids and self._knowledge is not None:
            dropped = await self._knowledge.drop_profile(
                profile_id=profile_id, source_ids=source_ids
            )
        purged = self._repo.purge_profile(profile_id)
        return {
            "profile_id": profile_id,
            "knowledge_sources_dropped": dropped,
            "purged": purged,
        }

    async def process_activation(self, operation_id: str) -> dict[str, object]:
        """The accepted immutable snapshot is the entire recoverable input."""
        snapshot = self._repo.snapshot_for_operation(operation_id)
        receipt = await self.activate_knowledge(snapshot.id, operation_id=operation_id)
        return {
            "resource_revision": self.get_profile(snapshot.profile_id).revision,
            "profile_snapshot_id": snapshot.id,
            "knowledge_generation": receipt.generation,
            "source_ids": receipt.source_ids,
        }

    def recover_interrupted_operations(self) -> None:
        self._repo.recover_interrupted_operations()

    def get_snapshot(self, snapshot_id: str) -> SnapshotView:
        snapshot = self._repo.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"RESOURCE_NOT_FOUND: snapshot {snapshot_id}")
        return SnapshotView(
            id=snapshot.id,
            profile_id=snapshot.profile_id,
            revision=snapshot.revision,
            confirmed_claim_ids=list(snapshot.confirmed_claim_ids or []),
            display_fields=dict(snapshot.display_fields or {}),
            created_at=snapshot.created_at,
        )

    # ---------- Knowledge 激活 ----------

    async def activate_knowledge(
        self, snapshot_id: str, *, operation_id: str | None = None
    ) -> ActivationReceipt:
        """Only the exact generation's complete receipt can make it ready."""
        document_ids: list[str] = []
        try:
            self._repo.set_activation_status(
                snapshot_id, "indexing", operation_id=operation_id
            )
            snapshot = self._repo.get_snapshot(snapshot_id)
            if not snapshot.confirmed_claim_ids:
                raise InvalidStateError("资料快照没有已确认事实，请先补充并确认。")
            claims = {
                claim.id: claim for claim in self._repo.list_claims(snapshot.profile_id)
            }
            sources: list[KnowledgeSource] = []
            for claim_id in snapshot.confirmed_claim_ids:
                claim = claims.get(claim_id)
                if claim is None or claim.status != "confirmed":
                    raise InvalidStateError(f"快照引用的 Claim 不可用：{claim_id}")
                sources.append(
                    KnowledgeSource(
                        source_id=f"{snapshot.id}:{claim.id}", text=self._render(claim)
                    )
                )
                document_ids.extend(self._documents_of(claim))
            self._set_index_status(document_ids, "indexing")
            if self._knowledge is None:
                raise RuntimeError("SERVICE_NOT_READY: 未配置 Knowledge 网关，不能激活")
            receipt = await self._knowledge.index_snapshot(
                profile_id=snapshot.profile_id, generation=snapshot.id, sources=sources
            )
            expected_sources = {source.source_id for source in sources}
            if (
                receipt.generation != snapshot.id
                or len(receipt.source_ids) != len(expected_sources)
                or set(receipt.source_ids) != expected_sources
            ):
                raise RuntimeError("UPSTREAM_FAILED: Knowledge 回执与资料快照不一致")
            result = ActivationReceipt(
                generation=receipt.generation,
                source_ids=receipt.source_ids,
                document_ids=sorted(set(document_ids)),
                embedding_logical_calls=receipt.embedding_logical_calls,
            )
            self._set_index_status(document_ids, "ready")
            self._repo.set_activation_status(
                snapshot_id, "ready", operation_id=operation_id, receipt=asdict(result)
            )
            return result
        except Exception:
            self._set_index_status(document_ids, "failed")
            self._repo.set_activation_status(
                snapshot_id, "failed", operation_id=operation_id
            )
            raise

    def snapshot_source_ids(self, snapshot_id: str) -> list[str]:
        """当前快照允许检索的 source ids（检索前过滤旧版本/已删除内容的依据）。"""
        snapshot = self._repo.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"RESOURCE_NOT_FOUND: snapshot {snapshot_id}")
        return [
            f"{snapshot.id}:{claim_id}" for claim_id in snapshot.confirmed_claim_ids
        ]

    async def search_knowledge(
        self, *, snapshot_id: str, query: str, top_k: int
    ) -> list[dict[str, object]]:
        if self._knowledge is None:
            raise RuntimeError("未配置 Knowledge 网关，不能检索")
        snapshot = self._repo.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"RESOURCE_NOT_FOUND: snapshot {snapshot_id}")
        return await self._knowledge.search(
            profile_id=snapshot.profile_id,
            generation=snapshot.id,
            allowed_source_ids=self.snapshot_source_ids(snapshot_id),
            query=query,
            top_k=top_k,
        )

    # ---------- 内部 ----------

    @staticmethod
    def _render(claim) -> str:
        return claim.text

    def _documents_of(self, claim) -> list[str]:
        return self._repo.documents_for_blocks(list(claim.source_block_ids or []))

    def _set_index_status(self, document_ids: list[str], status: str) -> None:
        self._repo.set_index_status(document_ids, status)


__all__ = [
    "FACT_SECTIONS",
    "ActivationReceipt",
    "ClaimView",
    "KnowledgeGateway",
    "KnowledgeSource",
    "ProfileService",
    "ProfileView",
    "RevisionConflict",
    "SnapshotView",
]
