"""CLI database selection and non-migrating reads, using temporary SQLite only."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from zhijue.adapters.db.migrations import upgrade_database
from zhijue.api.app import AppConfig

WORKSPACE = Path(__file__).resolve().parents[3]


@pytest.fixture
def cli(monkeypatch, tmp_path):
    for key in (
        "ZHIJUE_DATABASE_URL",
        "ZHIJUE_RUNTIME_DIR",
        "ZHIJUE_MODEL_ENV_FILE",
        "ZHIJUE_EMBEDDING_ENV_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "manage_knowledge_pack", WORKSPACE / "scripts/manage_knowledge_pack.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES (?)", (path.name,))
    return f"sqlite:///{path}"


def selected_database(service):
    try:
        with service._engine.connect() as connection:
            return connection.exec_driver_sql("PRAGMA database_list").one()[2]
    finally:
        service._engine.dispose()


@pytest.mark.parametrize("selection", ["default", "runtime", "env", "argument"])
def test_database_precedence_matches_api(cli, monkeypatch, tmp_path, selection):
    if selection in {"runtime", "env", "argument"}:
        monkeypatch.setenv("ZHIJUE_RUNTIME_DIR", "selected-runtime")
    if selection in {"env", "argument"}:
        monkeypatch.setenv(
            "ZHIJUE_DATABASE_URL", database(tmp_path / "env-database.db")
        )
    explicit = database(tmp_path / "argument.db") if selection == "argument" else None
    config = AppConfig.from_env()
    expected = Path((explicit or config.database_url).removeprefix("sqlite:///"))
    if not expected.exists():
        database(expected)
    service = cli.build_service(explicit, read_only=True)
    assert selected_database(service) == str(expected.resolve())
    assert service._runtime_dir == config.runtime_dir.resolve()


def test_database_file_with_uri_characters_is_selected(cli, tmp_path):
    target = tmp_path / "isolated #% database.db"
    service = cli.build_service(database(target), read_only=True)
    assert selected_database(service) == str(target)


def test_list_connection_cannot_write(cli, tmp_path):
    service = cli.build_service(database(tmp_path / "read-only.db"), read_only=True)
    try:
        with service._engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT value FROM marker").scalar()
            with pytest.raises(OperationalError, match="readonly"):
                connection.exec_driver_sql("INSERT INTO marker VALUES ('forbidden')")
    finally:
        service._engine.dispose()


def test_list_missing_database_neither_creates_nor_migrates(cli, tmp_path):
    with pytest.raises(SystemExit, match="目标数据库不存在"):
        cli.main(["list"])
    assert not (tmp_path / "runtime").exists()


def test_list_old_database_does_not_migrate(cli, monkeypatch, tmp_path, capsys):
    target = tmp_path / "old.db"
    monkeypatch.setenv("ZHIJUE_DATABASE_URL", database(target))
    before = target.read_bytes()
    assert cli.main(["list"]) == 1
    assert "未执行迁移" in capsys.readouterr().err
    assert target.read_bytes() == before
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [("marker",)]


def test_list_uses_explicit_database_instead_of_environment(
    cli, monkeypatch, tmp_path, capsys
):
    selected = tmp_path / "selected.db"
    selected_url = f"sqlite:///{selected}"
    upgrade_database(selected_url)
    # Wrong env target must not be created or migrated as a side effect of list.
    wrong = tmp_path / "wrong.db"
    monkeypatch.setenv("ZHIJUE_DATABASE_URL", f"sqlite:///{wrong}")
    before = selected.read_bytes()
    assert cli.main(["--database-url", selected_url, "list"]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), dict)
    assert not wrong.exists()
    assert selected.read_bytes() == before


def test_unconfirmed_review_does_not_open_or_create_database(cli, tmp_path, capsys):
    assert (
        cli.main(
            [
                "review",
                "--release-id",
                "test-release",
                "--expect-digest",
                "sha256:test",
                "--decision",
                "approved",
                "--reviewer",
                "test-owner",
                "--role",
                "owner",
                "--note",
                "No review was performed; expect refusal.",
            ]
        )
        == 2
    )
    assert "拒绝执行" in capsys.readouterr().err
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("missing", ["level1", "level2", "rules", "owner"])
def test_approved_review_requires_owner_and_explicit_two_levels(
    cli, monkeypatch, capsys, missing
):
    def cannot_open(*args, **kwargs):
        raise AssertionError("Refusal must happen before opening a database")

    monkeypatch.setattr(cli, "build_service", cannot_open)
    argv = [
        "review",
        "--release-id",
        "TEST_ONLY_release",
        "--expect-digest",
        "sha256:test",
        "--decision",
        "approved",
        "--reviewer",
        "TEST_ONLY_owner",
        "--role",
        "self_check" if missing == "owner" else "owner",
        "--note",
        "TEST_ONLY incomplete confirmations",
        "--confirm-content-reviewed",
    ]
    argv += [
        f"--confirm-{level}-reviewed"
        for level in ("level1", "level2", "rules")
        if level != missing
    ]
    assert cli.main(argv) == 2
    assert "拒绝执行" in capsys.readouterr().err


def test_explicit_owner_confirmations_reach_review_service(cli, monkeypatch, capsys):
    class RecordingService:
        def record_review(self, **kwargs):
            assert kwargs["reviewer_role"] == "owner"
            assert all(
                kwargs[name] is True
                for name in ("level1_reviewed", "level2_reviewed", "rules_reviewed")
            )
            return {"TEST_ONLY": True}

    monkeypatch.setattr(
        cli, "build_service", lambda *args, **kwargs: RecordingService()
    )
    assert (
        cli.main(
            [
                "review",
                "--release-id",
                "TEST_ONLY_release",
                "--expect-digest",
                "sha256:test",
                "--decision",
                "approved",
                "--reviewer",
                "TEST_ONLY_owner",
                "--role",
                "owner",
                "--note",
                "TEST_ONLY confirms dispatch, no real approval",
                "--confirm-content-reviewed",
                "--confirm-level1-reviewed",
                "--confirm-level2-reviewed",
                "--confirm-rules-reviewed",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"TEST_ONLY": True}
