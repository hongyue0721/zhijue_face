"""把配置、数据集、检索与模型客户端装配成一次可复现运行。

装配顺序即防污染顺序：先冻结 prompt/配置指纹 → 建 KB → 每 case 检索一次 →
四臂共用同一证据对象 → 每 cell 一次生成 → 落 trace。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zhijue_research.config import (
    ExperimentConfig,
    ExperimentConfigError,
    load_experiment_config,
)
from zhijue_research.dataset.loader import load_dataset, load_split_manifest
from zhijue_research.dataset.models import CandidateBundle
from zhijue_research.evidence import EvidenceItem, EvidenceSet, claim_ref_for
from zhijue_research.knowledge_provider import KnowledgeProvider, build_provider
from zhijue_research.model_clients import (
    ModelClient,
    ScriptedModelClient,
    TransportModelClient,
)
from zhijue_research.paths import RESEARCH_ROOT, require_private_model_env
from zhijue_research.prompts import PromptRegistry
from zhijue_research.runner import CellResult, ExperimentRunner
from zhijue_research.scripted import responder


class AssemblyError(RuntimeError):
    """装配阶段的不一致（缺 prompt、live 未授权、数据与配置不匹配）。"""


@dataclass(slots=True)
class ExperimentPlan:
    config: ExperimentConfig
    prompts: PromptRegistry
    client: ModelClient
    bundles: tuple[CandidateBundle, ...]
    providers: list[KnowledgeProvider] = field(default_factory=list)
    runners: list[ExperimentRunner] = field(default_factory=[])

    async def run(self) -> list[CellResult]:
        results: list[CellResult] = []
        for runner in self.runners:
            results.extend(await runner.run())
        return results

    async def close(self) -> None:
        for provider in self.providers:
            await provider.close()
        self.providers.clear()


def load_config(
    path: Path | None = None, *, split: str | None = None
) -> ExperimentConfig:
    return load_experiment_config(
        path or (RESEARCH_ROOT / "config/experiment.yaml"), split=split
    )


def load_bundles(config: ExperimentConfig) -> tuple[CandidateBundle, ...]:
    manifest = load_split_manifest(RESEARCH_ROOT / "splits", config.split)
    return load_dataset(
        RESEARCH_ROOT / "data/candidates",
        dataset_version=config.dataset_version,
        split=config.split,
        split_manifest=manifest,
    )


def build_prompt_registry(config: ExperimentConfig) -> PromptRegistry:
    return PromptRegistry(
        RESEARCH_ROOT / "config/prompts",
        {
            method: dict(config.prompt_hashes.get(method, {}))
            for method in config.methods
        },
    )


def build_live_client(
    config: ExperimentConfig, model_env_file: Path | None
) -> ModelClient:
    """真实调用：必须显式授权，且复用 R1 抽出的同一个 transport。"""

    if not config.allow_paid_calls:
        raise ExperimentConfigError(
            "allow_paid_calls=false：拒绝调用付费模型。确认预算与范围后在配置里显式打开。"
        )
    from zhijue.adapters.chat_transport import OpenAICompatibleChatTransport
    from zhijue.adapters.model import load_model_settings

    settings = load_model_settings(require_private_model_env(model_env_file, config))
    if settings.model_name != config.model.model:
        raise AssemblyError(
            f"私密配置模型 {settings.model_name} 与实验配置 {config.model.model} 不一致"
        )
    return TransportModelClient(
        transport=OpenAICompatibleChatTransport(settings), model=config.model
    )


def build_scripted_client(
    config: ExperimentConfig,
    *,
    override: Mapping[str, str] | None = None,
    drift_methods: Sequence[str] = (),
) -> ScriptedModelClient:
    del config
    return ScriptedModelClient(
        responder=responder(override=override, drift_methods=tuple(drift_methods))
    )


def build_plan(
    config: ExperimentConfig,
    *,
    bundles: Sequence[CandidateBundle],
    client: ModelClient,
    prompts: PromptRegistry | None = None,
    scripted_evidence: EvidenceSet | None = None,
    provider_factory=None,
    provider_settings: Any | None = None,
) -> ExperimentPlan:
    """装配 runner。

    `scripted_evidence` 只用于零网络 harness 自检（明确记 `embed_mode=fixture` 的
    离线证据），正式运行必须走 `provider_factory` 下的真实 Knowledge。
    """

    registry = prompts or build_prompt_registry(config)
    providers: list[KnowledgeProvider] = []
    runners: list[ExperimentRunner] = []
    for bundle in bundles:
        provider = _build_retrieval(
            config,
            bundle,
            scripted_evidence=scripted_evidence,
            provider_factory=provider_factory,
            provider_settings=provider_settings,
        )
        providers.append(provider)
        runners.append(
            ExperimentRunner(
                config=config,
                prompts=registry,
                client=client,
                retrieval=provider,
                bundle=bundle,
                provider_name=_provider_name(config, client),
                model_name=_model_name(config, client),
                model_fingerprint=config.model.fingerprint(),
            )
        )
    return ExperimentPlan(
        config=config,
        prompts=registry,
        client=client,
        bundles=tuple(bundles),
        providers=providers,
        runners=runners,
    )


def _build_retrieval(
    config: ExperimentConfig,
    bundle: CandidateBundle,
    *,
    scripted_evidence: EvidenceSet | None,
    provider_factory,
    provider_settings: Any | None,
):
    if scripted_evidence is not None:
        return _ScriptedEvidenceProvider(
            bundle=bundle, config=config, evidence=scripted_evidence
        )
    if provider_factory is not None:
        return provider_factory(bundle, config)
    if provider_settings is None:
        raise AssemblyError("需要 provider_settings 或 scripted_evidence 才能装配检索")
    return build_provider(bundle, config)


def _provider_name(config: ExperimentConfig, client: ModelClient) -> str:
    return (
        "fixture-local"
        if getattr(client, "driver_kind", "") == "scripted"
        else config.model.provider
    )


def _model_name(config: ExperimentConfig, client: ModelClient) -> str:
    return (
        "scripted-fixture"
        if getattr(client, "driver_kind", "") == "scripted"
        else config.model.model
    )


@dataclass(slots=True)
class _ScriptedEvidenceProvider:
    """零网络证据供给：证据直接来自该 candidate 的 confirmed 事实。

    顺序固定为 fact_id 升序，因此 M2 与 M3 一定拿到同一个 EvidenceSet（I4）。
    """

    bundle: CandidateBundle
    config: ExperimentConfig
    evidence: EvidenceSet
    retrieve_calls: int = field(default=0, init=False)

    async def ready(self) -> None:
        self.evidence.require_candidate()

    async def retrieve(self, case):
        del case
        self.retrieve_calls += 1
        return self.evidence

    def trace_block(
        self, evidence: EvidenceSet, *, expected_fact_ids: Sequence[str] = ()
    ) -> dict:
        from zhijue_research.io_utils import sha256_text
        from zhijue_research.retrieval import QUERY_TEMPLATE_VERSION

        rows = [
            {
                "rank": item.rank,
                "source_id": item.source_id,
                "fact_id": item.fact_id,
                "claim_ref": claim_ref_for(item.source_id),
                "generation": item.generation,
                "chunk_id": item.chunk_id,
                "score": item.score,
                "text_hash": sha256_text(item.text),
            }
            for item in evidence.items
        ]
        expected = [str(item) for item in expected_fact_ids]
        retrieved = {str(row["fact_id"]) for row in rows}
        return {
            "config": {
                "query_template_version": QUERY_TEMPLATE_VERSION,
                "embed_mode": "fixture",
                "kb_backend": "scripted-inmemory-fixture-no-network",
            },
            "query": evidence.query,
            "query_hash": sha256_text(evidence.query),
            "top_k": evidence.top_k,
            "hits": rows,
            "expected_evidence_fact_ids": expected or None,
            "recall_at_k": (
                None if not expected else len(retrieved & set(expected)) / len(expected)
            ),
        }

    async def close(self) -> None:
        return None


def scripted_evidence_for(
    bundle: CandidateBundle,
    *,
    query: str = "scripted://fixture",
    top_k: int | None = None,
) -> EvidenceSet:
    """按 fact_id 升序构造离线证据集；score=None 表示 provider 没给分数，不填 0。"""

    facts = sorted(bundle.ground_truth.confirmed_facts(), key=lambda fact: fact.fact_id)
    candidate_id = bundle.ground_truth.candidate_id
    items = tuple(
        EvidenceItem(
            source_id=fact.source_id_for(candidate_id=candidate_id),
            text=fact.value,
            fact_id=fact.fact_id,
            rank=rank,
            score=None,
            generation=f"gen_{bundle.ground_truth.raw.get('dataset_version', 'fixture')}",
            chunk_id=None,
        )
        for rank, fact in enumerate(facts, start=1)
    )
    return EvidenceSet(
        candidate_id=candidate_id,
        query=query,
        top_k=top_k or len(items),
        items=items,
    )


__all__ = [
    "AssemblyError",
    "ExperimentPlan",
    "build_live_client",
    "build_plan",
    "build_prompt_registry",
    "build_scripted_client",
    "load_bundles",
    "load_config",
    "scripted_evidence_for",
]
