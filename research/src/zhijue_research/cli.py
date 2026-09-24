"""研究 CLI：`run` 产出 trace JSONL，`verify-dataset` 只校验数据，`report` 出离线指标。

安全默认：`--model-driver scripted` + `--evidence scripted` = 完全离线零费用。
真实模型必须同时满足 `allow_paid_calls: true` 与显式私密 env 文件；
真实 Knowledge 检索必须显式 `--evidence knowledge`。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[2]
for entry in (RESEARCH_ROOT / "src", RESEARCH_ROOT.parent / "services" / "api" / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from zhijue_research.config import ExperimentConfig, ExperimentConfigError
from zhijue_research.dataset.loader import (
    DatasetError,
    load_split_manifest,
)
from zhijue_research.dataset.models import CandidateBundle
from zhijue_research.experiment import (
    AssemblyError,
    build_live_client,
    build_plan,
    build_prompt_registry,
    build_scripted_client,
    load_bundles,
    load_config,
    scripted_evidence_for,
)
from zhijue_research.knowledge_provider import build_provider
from zhijue_research.paths import runtime_path
from zhijue_research.runner import LeakageError
from zhijue_research.trace import TraceWriter, read_traces

EVIDENCE_MODES = ("scripted", "knowledge")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zhijue_research", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑 split × methods，产出 trace JSONL")
    run.add_argument(
        "--config", type=Path, default=RESEARCH_ROOT / "config/experiment.yaml"
    )
    run.add_argument("--split", default=None, help="覆盖配置里的 split")
    run.add_argument(
        "--methods", nargs="*", default=None, help="只跑配置已登记的方法子集"
    )
    run.add_argument("--model-driver", choices=("scripted", "live"), default="scripted")
    run.add_argument(
        "--evidence",
        choices=EVIDENCE_MODES,
        default="scripted",
        help="scripted=零网络离线证据；knowledge=真实 openJiuwen KB 检索",
    )
    run.add_argument("--model-env-file", type=Path, default=None)
    run.add_argument(
        "--drift-method",
        action="append",
        default=[],
        help="scripted 臂：指定方法故意产出捏造内容（可重复）",
    )
    run.add_argument("--tag", default="manual")
    run.set_defaults(handler=cmd_run)

    verify = sub.add_parser("verify-dataset", help="只校验数据集与 split，零模型调用")
    verify.add_argument(
        "--config", type=Path, default=RESEARCH_ROOT / "config/experiment.yaml"
    )
    verify.add_argument("--split", default=None)
    verify.set_defaults(handler=cmd_verify_dataset)

    report = sub.add_parser(
        "report", help="对 trace 做离线 join + 确定性 evaluator + 指标"
    )
    report.add_argument("--trace", type=Path, required=True)
    report.add_argument(
        "--config", type=Path, default=RESEARCH_ROOT / "config/experiment.yaml"
    )
    report.add_argument("--split", default=None)
    report.add_argument("--out", type=Path, default=None)
    report.set_defaults(handler=cmd_report)
    return parser


def cmd_verify_dataset(args: argparse.Namespace) -> int:
    config = load_config(args.config, split=args.split)
    manifest = load_split_manifest(RESEARCH_ROOT / "splits", config.split)
    bundles = load_bundles(config)
    listed = {str(item) for item in manifest["case_ids"]}
    found = {
        f"{b.ground_truth.candidate_id}/{c.case_id}" for b in bundles for c in b.cases
    }
    if not listed <= found:
        raise DatasetError(f"split 清单里的 case 不存在：{sorted(listed - found)}")
    for bundle in bundles:
        _assert_views_disjoint(bundle)
    print(
        f"dataset ok: candidates={len(bundles)} cases={len(listed)} split={config.split} "
        f"embed_mode={config.retrieval.embed_mode} config_fingerprint={config.fingerprint[:12]}"
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config, split=args.split)
    if args.methods:
        config = _replace_methods(config, args.methods)
    bundles = load_bundles(config)
    prompts = build_prompt_registry(config)

    client = (
        build_live_client(config, args.model_env_file)
        if args.model_driver == "live"
        else build_scripted_client(config, drift_methods=tuple(args.drift_method))
    )
    provider_factory = (
        (lambda bundle, cfg: build_provider(bundle, cfg))
        if args.evidence == "knowledge"
        else None
    )
    out_path = runtime_path("traces", f"{config.split}_{args.tag}.jsonl")
    if out_path.exists():
        raise FileExistsError(f"trace 已存在，拒绝覆盖：{out_path}（换 --tag）")

    async def go() -> int:
        written = 0
        with TraceWriter(out_path) as writer:
            for bundle in bundles:
                evidence = (
                    None
                    if args.evidence == "knowledge"
                    else scripted_evidence_for(bundle)
                )
                plan = build_plan(
                    config,
                    bundles=[bundle],
                    client=client,
                    prompts=prompts,
                    scripted_evidence=evidence,
                    provider_factory=provider_factory,
                )
                try:
                    for result in await plan.run():
                        writer.emit(result.record)
                        written += 1
                        _print_cell(result.record)
                finally:
                    await plan.close()
        print(
            f"\ntrace: {out_path} ({written} cells, model_driver={args.model_driver}, "
            f"evidence={args.evidence})"
        )
        return written

    cells = asyncio.run(go())
    if args.model_driver == "scripted":
        print("注意：scripted 驱动，全部结果属于 fixture，禁止当作真实模型表现。")
    return 0 if cells else 1


def cmd_report(args: argparse.Namespace) -> int:
    from zhijue_research.analysis import join_evaluator_labels, score_traces

    config = load_config(args.config, split=args.split)
    records = read_traces(args.trace)
    bundles = {b.ground_truth.candidate_id: b for b in load_bundles(config)}
    enriched = join_evaluator_labels(records, bundles)
    scored = score_traces(enriched)
    payload = {
        "trace_file": str(args.trace),
        "config_fingerprint": config.fingerprint,
        "evaluator_version": config.evaluator_version,
        "taxonomy_version": scored["taxonomy_version"],
        "dataset_version": config.dataset_version,
        "split": config.split,
        "n_records": len(scored["records"]),
        "metrics": scored["metrics"],
        "by_method": scored["by_method"],
        "records": scored["records"],
    }
    out = args.out or runtime_path("analysis", f"{args.trace.stem}_report.json")
    if out.exists():
        out.unlink()
    from zhijue_research.io_utils import write_json_exclusive

    write_json_exclusive(out, payload)
    print(
        json.dumps(
            {"metrics": scored["metrics"], "by_method": scored["by_method"]},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    print(f"report: {out}")
    return 0


def _print_cell(record: dict[str, Any]) -> None:
    validation = record["validation"]
    print(
        f"  {record['case_id']:<12} {record['method_id']:<18} "
        f"accepted={validation['accepted']!s:<5} attempts={record['attempts']} "
        f"reasons={','.join(validation['reasons']) or '-'} "
        f"recall={_fmt(record['retrieval'])}"
    )


def _fmt(retrieval: dict[str, Any] | None) -> str:
    if retrieval is None:
        return "n/a"
    value = retrieval.get("recall_at_k")
    return "null" if value is None else f"{value:.2f}"


def _replace_methods(
    config: ExperimentConfig, methods: Sequence[str]
) -> ExperimentConfig:
    from dataclasses import replace

    unknown = sorted(set(methods) - set(config.prompt_versions))
    if unknown:
        raise ExperimentConfigError(f"未登记 prompt 版本的方法：{unknown}")
    return replace(config, methods=tuple(methods))


def _assert_views_disjoint(bundle: CandidateBundle) -> None:
    """自检：生成侧视图里绝不出现该候选人的 trap 文本（结构投影真的生效了）。"""

    import json

    serialized = json.dumps(
        [
            json.loads(json.dumps(_case_jsonable(case.generator), ensure_ascii=False))
            for case in bundle.cases
        ],
        ensure_ascii=False,
    )
    for trap in bundle.ground_truth.trap_claims:
        value = str(trap.get("value", ""))
        if len(value) >= 8 and value in serialized:
            raise LeakageError(
                f"LEAKAGE_BLOCKED：case {bundle.ground_truth.candidate_id} 生成侧含 trap 文本"
            )


def _case_jsonable(view: Any) -> dict[str, Any]:
    return {
        "case_id": view.case_id,
        "candidate_id": view.candidate_id,
        "split": view.split,
        "question_wording": view.question_wording,
        "competency_tags": list(view.competency_tags),
        "turns": [list(turn) for turn in view.turns],
        "retrieval_query_template": view.retrieval_query_template,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (
        ExperimentConfigError,
        DatasetError,
        AssemblyError,
        LeakageError,
        FileExistsError,
    ) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
