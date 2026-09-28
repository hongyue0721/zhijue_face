#!/usr/bin/env python3
"""负责人岗位包审核入口（本地 CLI，不做 Web 审核后台）。

主文件 4.5：该入口只用于**负责人完成技术核对之后**登记结果。
执行 Agent 不得自行调用它给新内容批准。

必须同时给出：release ID、期望内容摘要、负责人标识、审核备注，并显式确认
已完成内容核对（--confirm-content-reviewed）。期望摘要与当前重算摘要不一致
时拒绝登记；批准范围逐条绑定 Seed 内容 hash。

用法（必须使用项目锁定 venv）：
    services/api/.venv/bin/python scripts/manage_knowledge_pack.py list
    services/api/.venv/bin/python scripts/manage_knowledge_pack.py review \
        --release-id kpr_xxx --expect-digest sha256:xxx \
        --decision approved --reviewer hongyue --role owner \
        --note "已对照 S24/S26/S28/S29/S30 完成 Level 2 核对" \
        --confirm-content-reviewed

数据库只取显式 ZHIJUE_DATABASE_URL（默认 runtime/business.db），
不提供“顺手迁移真实库”的隐式路径。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api" / "src"))

from zhijue.adapters.db.engine import make_engine  # noqa: E402
from zhijue.adapters.db.migrations import upgrade_database  # noqa: E402
from zhijue.application.knowledge_packs import KnowledgePackService  # noqa: E402
from zhijue.domain.knowledge_packs import PackLimits  # noqa: E402


def build_service(database_url: str) -> KnowledgePackService:
    # 岗位包内容存储与业务库同属一个实例的 runtime 目录：显式
    # ZHIJUE_RUNTIME_DIR 优先，SQLite 否则取库文件父目录；不猜第三处。
    env_runtime = os.environ.get("ZHIJUE_RUNTIME_DIR")
    if env_runtime:
        runtime_dir = Path(env_runtime).resolve()
    elif database_url.startswith("sqlite:///"):
        runtime_dir = Path(database_url.removeprefix("sqlite:///")).resolve().parent
    else:
        raise SystemExit(
            "非 SQLite 数据库必须显式设置 ZHIJUE_RUNTIME_DIR（岗位包内容存储位置）。"
        )
    import yaml

    demo = yaml.safe_load((ROOT / "config" / "demo.yaml").read_text(encoding="utf-8"))
    pack_section = demo.get("knowledge_packs") or {}
    if "default_pack_id" not in pack_section:
        raise SystemExit("config/demo.yaml 缺少 knowledge_packs.default_pack_id")
    limits = PackLimits(
        **{k: int(v) for k, v in (pack_section.get("limits") or {}).items()}
    )
    upgrade_database(database_url)
    engine = make_engine(database_url, wal=True)
    return KnowledgePackService(
        engine,
        runtime_dir=runtime_dir,
        repo_root=ROOT,
        limits=limits,
        default_pack_id=str(pack_section["default_pack_id"]),
        live_allowed_review_status=str(
            (demo.get("seed_bank") or {}).get("live_allowed_review_status", "approved")
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default="sqlite:///./services/api/runtime/business.db",
        help="目标业务库（SQLite URL）；审核登记不会触碰其他库。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出 release 与有效审核状态")

    review = sub.add_parser("review", help="负责人登记审核结论")
    review.add_argument("--release-id", required=True)
    review.add_argument("--expect-digest", required=True)
    review.add_argument("--decision", required=True, choices=["approved", "rejected"])
    review.add_argument("--reviewer", required=True, help="负责人标识（人名/记录 ID）")
    review.add_argument(
        "--role", required=True, help="审核角色，如 owner；不伪造专家身份"
    )
    review.add_argument("--note", required=True, help="审核依据与范围说明")
    review.add_argument(
        "--seed",
        action="append",
        default=None,
        help="批准范围内逐条 Seed ID；缺省为全部（仍逐条绑定内容 hash）",
    )
    review.add_argument(
        "--confirm-content-reviewed",
        action="store_true",
        help="确认已完成技术核对；未提供则拒绝执行",
    )

    args = parser.parse_args(argv)
    service = build_service(args.database_url)

    if args.command == "list":
        view = service.list_view()
        print(json.dumps(view, ensure_ascii=False, indent=2))
        return 0

    if not args.confirm_content_reviewed:
        print(
            "拒绝执行：必须先由负责人完成技术核对并使用 --confirm-content-reviewed。"
            "（格式通过 ≠ 审核通过；本入口只为登记已做出的结论。）",
            file=sys.stderr,
        )
        return 2
    result = service.record_review(
        release_id=args.release_id,
        expected_digest=args.expect_digest,
        decision=args.decision,
        reviewer_id=args.reviewer,
        reviewer_role=args.role,
        note=args.note,
        approved_seed_ids=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
