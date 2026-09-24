#!/usr/bin/env python3
"""R3 live embedding 单次探测：证明真实 embedding 通道能索引与检索，不宣称检索质量。

边界（写进证据文件，防止被误读）：

- 只调用 embedding 接口，不调用对话模型，因此不产生 chat token 费用；
- 计费未知字段保持 `null`，不填 0，也不按"应该免费"假设；
- 命中排序与 recall 只是**结构观测**：样本 1 个 candidate、4 个 case，
  不足以支撑"检索质量好"的结论；
- 产物落在 `research/runtime/`（gitignore），密钥永不落盘。

用法：

    PYTHONPATH=src:../services/api/src python scripts/live_embedding_probe.py \\
        --i-accept-embedding-cost
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(RESEARCH_ROOT / "src"),
    str(RESEARCH_ROOT.parent / "services/api/src"),
]

from zhijue_research.config import load_experiment_config
from zhijue_research.experiment import load_bundles
from zhijue_research.knowledge_provider import build_provider
from zhijue_research.paths import runtime_path

BOUNDARY = (
    "本文件只证明 live embedding 通道可索引、可检索、可回查 source_id；"
    "不构成检索质量、稳定性、成本或模型效果的结论。"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=RESEARCH_ROOT / "config/experiment.yaml"
    )
    parser.add_argument(
        "--candidate", default=None, help="只探测某个 candidate；默认取第一个"
    )
    parser.add_argument(
        "--i-accept-embedding-cost",
        action="store_true",
        help="显式接受本次真实 embedding 调用可能产生的费用",
    )
    parser.add_argument("--top-k", type=int, default=None, help="覆盖配置里的 top_k")
    return parser.parse_args(argv)


async def probe(config_args: argparse.Namespace) -> dict[str, Any]:
    config = load_experiment_config(config_args.config)
    if not config_args.i_accept_embedding_cost:
        raise SystemExit(
            "拒绝执行：live embedding 是外部付费调用，需要 --i-accept-embedding-cost 显式确认。"
        )
    retrieval = config.retrieval
    if config_args.top_k:
        retrieval = replace(retrieval, top_k=config_args.top_k)
    # 只在内存里翻开关：仓库配置保持 embed_mode=fixture / allow_paid_calls=false。
    config = replace(
        config,
        retrieval=replace(retrieval, embed_mode="live"),
        allow_paid_calls=True,
    )

    bundle = next(
        item
        for item in load_bundles(config)
        if config_args.candidate is None
        or item.ground_truth.candidate_id == config_args.candidate
    )
    provider = build_provider(bundle, config)
    started = time.monotonic()
    per_case: list[dict[str, Any]] = []
    try:
        await provider.ready()
        receipt = dict(provider.index_receipt or {})
        for entry in bundle.cases:
            evidence = await provider.retrieve(entry.generator)
            block = provider.trace_block(
                evidence,
                expected_fact_ids=entry.evaluator.expected_evidence_fact_ids,
            )
            per_case.append(
                {
                    "case_id": entry.generator.case_id,
                    "query_hash": block["query_hash"],
                    "expected_fact_ids": list(
                        entry.evaluator.expected_evidence_fact_ids
                    ),
                    "hits": [
                        {
                            "rank": hit["rank"],
                            "source_id": hit["source_id"],
                            "fact_id": hit["fact_id"],
                            "score": hit.get("score"),
                            "text_hash": hit["text_hash"],
                        }
                        for hit in block["hits"]
                    ],
                    "recall_at_k": block.get("recall_at_k"),
                }
            )
    finally:
        await provider.close()

    settings = provider.settings
    return {
        "schema_version": "embedding_probe_1.0.0",
        "performed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "boundary": BOUNDARY,
        "provider": settings.embedding_provider,
        "model": settings.embedding_model,
        "api_base": settings.embedding_api_base,
        "expected_dimension": settings.embedding_expected_dimension,
        # HTTPS 由业务侧 KnowledgeSettings 校验器强制，不存在明文降级开关。
        "api_scheme": "https",
        "kb_backend": provider.backend,
        "candidate_id": bundle.ground_truth.candidate_id,
        "indexed_source_ids": receipt.get("source_ids", []),
        "embedding_logical_calls": receipt.get("embedding_logical_calls"),
        "retrieve_calls": provider.retrieve_calls,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "cost_cny": None,  # 上游未提供计费回传，保持未知而不是 0
        "cases": per_case,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = asyncio.run(probe(args))
    out = runtime_path("embedding-probe", f"live-{int(time.time())}.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"live embedding probe: model={result['model']} dim={result['expected_dimension']} "
        f"indexed={len(result['indexed_source_ids'])} retrieve_calls={result['retrieve_calls']} "
        f"elapsed={result['elapsed_seconds']}s"
    )
    for case in result["cases"]:
        hits = ",".join(f"{h['rank']}:{h['fact_id']}" for h in case["hits"])
        print(f"  {case['case_id']} recall@k={case['recall_at_k']} hits={hits or '-'}")
    print(f"evidence: {out}")
    print("边界：仅证明 live embedding 通道可用，不证明检索质量。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
