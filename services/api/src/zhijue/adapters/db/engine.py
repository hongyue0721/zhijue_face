"""SQLite 引擎工厂：启用外键、busy_timeout；默认测试与业务分离。

docs/03 §7：连接启用 foreign_keys，配置 busy_timeout；WAL 在业务运行时目录
启用并与备份策略一起测试，fixture 内存库保持默认 journal。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def make_engine(url: str, *, busy_timeout_ms: int = 5000, wal: bool = False) -> Engine:
    if url.startswith("sqlite"):
        # check_same_thread=False 允许 FastAPI 同步依赖跨线程使用同一池；
        # 写路径仍由应用层事务边界串行化（docs/02 §7）。
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:  # pragma: no cover - M0/M1 只有 SQLite
        engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _configure(dbapi_conn, _record):  # SQLAlchemy 事件签名固定
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        if wal:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def make_business_db_path(runtime_dir: Path) -> Path:
    """业务库固定放 runtime/，测试用 tmp_path 或内存库，绝不共用文件。"""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir / "business.db"
