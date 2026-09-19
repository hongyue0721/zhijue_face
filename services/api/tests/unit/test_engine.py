"""M1-01 engine 测试：PRAGMA 配置真实生效（docs/03 §7）。"""

from __future__ import annotations

from zhijue.adapters.db.engine import make_business_db_path, make_engine


def test_engine_enables_foreign_keys_and_busy_timeout(tmp_path):
    db = tmp_path / "pragma.db"
    engine = make_engine(f"sqlite:///{db}", busy_timeout_ms=2500)
    with engine.connect() as conn:
        raw = conn.connection.driver_connection  # sqlite3 原生连接
        assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert raw.execute("PRAGMA busy_timeout").fetchone()[0] == 2500


def test_wal_only_when_requested(tmp_path):
    plain = make_engine(f"sqlite:///{tmp_path / 'plain.db'}")
    with plain.connect() as conn:
        mode = conn.connection.driver_connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()[0]
    assert mode == "delete"

    wal = make_engine(f"sqlite:///{tmp_path / 'wal.db'}", wal=True)
    with wal.connect() as conn:
        mode = conn.connection.driver_connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()[0]
    assert mode == "wal"


def test_business_db_path_creates_runtime_dir(tmp_path):
    runtime = tmp_path / "runtime"
    path = make_business_db_path(runtime)
    assert runtime.is_dir()
    assert path == runtime / "business.db"
