"""API 启动入口：uvicorn 单进程单 worker（config/demo.yaml runtime.api_workers=1）。

用法（在 services/api 下）：
    .venv/bin/python -m zhijue
本机默认 127.0.0.1:8000，不监听公网（AGENTS §3：公开公网需负责人确认）。
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    from zhijue.api.app import create_default_app

    config = create_default_app()
    host = os.environ.get("ZHIJUE_API_HOST", "127.0.0.1")
    port = int(os.environ.get("ZHIJUE_API_PORT", "8000"))
    uvicorn.run(config, host=host, port=port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
