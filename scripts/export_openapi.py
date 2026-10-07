#!/usr/bin/env python3
"""导出 FastAPI OpenAPI 契约到 contracts/openapi.json（api.md §10 文档同步要求）。

契约以运行时代码为唯一真源；测试断言导出文件与实时 document 一致，
所以任何路由/DTO 变更都必须重跑本脚本，防止文档漂移。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api" / "src"))


def main() -> int:
    from tempfile import TemporaryDirectory

    from zhijue.api.app import AppConfig, create_app

    # Contract export never reads private model/embedding env or a user runtime DB.
    with TemporaryDirectory(prefix="zhijue-openapi-") as temporary:
        runtime = Path(temporary)
        app = create_app(AppConfig(
            run_mode="fixture",
            database_url=f"sqlite:///{runtime / 'contract.db'}",
            runtime_dir=runtime,
            milvus_uri=runtime / "knowledge.db",
        ))
        try:
            document = app.openapi()
        finally:
            app.state.services.engine.dispose()
    target = ROOT / "contracts" / "openapi.json"
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"exported {len(document['paths'])} paths -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
