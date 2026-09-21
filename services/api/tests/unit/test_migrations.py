"""M1-01 迁移测试：upgrade/downgrade 可逆，唯一键/外键在真库生效。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import (
    Answer,
    Assessment,
    Base,
    Document,
    Interview,
    Operation,
    OperationEvent,
    Profile,
    ProfileSnapshot,
    ProfileSnapshotActivation,
    Question,
    Report,
)

API_ROOT = Path(__file__).resolve().parents[2]

# downgrade 后 alembic_version 保留是预期行为（版本追踪表，不是业务表）。
ALEMBIC_MANAGED = {"alembic_version"}


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _migrated_engine(tmp_path: Path, name: str):
    db = tmp_path / name
    command.upgrade(_alembic_config(db), "head")
    return make_engine(f"sqlite:///{db}")


def _insert_rows(session: Session, rows: list[object]) -> None:
    """SQLAlchemy 只按 relationship 排序；手动赋 FK 值时必须按拓扑顺序逐表 flush。"""
    by_table: dict[str, list[object]] = {}
    for row in rows:
        by_table.setdefault(type(row).__table__.name, []).append(row)
    for table in Base.metadata.sorted_tables:
        for row in by_table.get(table.name, []):
            session.add(row)
        if by_table.get(table.name):
            session.flush()


@pytest.fixture()
def base_engine(tmp_path):
    """已迁移的独立测试库 + 最小 Profile 链（不含 interview/question 等下游行）。"""
    engine = _migrated_engine(tmp_path, "base.db")
    with Session(engine) as session:
        _insert_rows(
            session,
            [
                Profile(id="profile_a", display_name="A"),
                ProfileSnapshot(id="snap_a", profile_id="profile_a", revision=0),
            ],
        )
        session.commit()
    return engine


@pytest.fixture()
def interview_engine(base_engine):
    with Session(base_engine) as session:
        _insert_rows(
            session,
            [
                Interview(
                    id="interview_a",
                    profile_snapshot_id="snap_a",
                    seed_bank_version="v1",
                    rubric_version="v1",
                    policy_version="v1",
                    run_mode="live",
                ),
                Question(
                    id="question_a",
                    interview_id="interview_a",
                    root_id="question_a",
                    kind="main",
                    seed_id="seed_1",
                    wording="题干",
                ),
            ],
        )
        session.commit()
    return base_engine


def test_upgrade_downgrade_roundtrip(tmp_path):
    db = tmp_path / "migrate.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    tables = {
        r[0] for r in con.execute("select name from sqlite_master where type='table'")
    }
    con.close()
    assert {"profile", "operation", "operation_event", "answer"} <= tables

    command.downgrade(cfg, "base")
    con = sqlite3.connect(db)
    remaining = {
        r[0] for r in con.execute("select name from sqlite_master where type='table'")
    }
    con.close()
    assert remaining == ALEMBIC_MANAGED, f"downgrade 未清理干净：{remaining}"

    command.upgrade(cfg, "head")  # 可重复执行


def test_migration_schema_matches_models(tmp_path):
    """迁移建出的表必须与 ORM 声明一致，防止两边漂移。"""
    engine = _migrated_engine(tmp_path, "compare.db")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"模型与迁移漂移：{diff}"


def test_one_accepted_answer_per_question(interview_engine):
    """仓储 bug 也不能给同一题落第二条已接受回答（docs/03 §7 唯一键）。"""
    with Session(interview_engine) as session:
        session.add(
            Answer(
                id="answer_1",
                question_id="question_a",
                interview_id="interview_a",
                client_turn_id="turn_1",
                raw_text="第一条",
            )
        )
        session.commit()
    with Session(interview_engine) as session:
        session.add(
            Answer(
                id="answer_2",
                question_id="question_a",
                interview_id="interview_a",
                client_turn_id="turn_2",
                raw_text="第二条",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
    # 第一条已提交且未被覆盖；第二条被数据库拒绝，不留下半成品。
    with Session(interview_engine) as session:
        rows = session.query(Answer).all()
    assert [r.id for r in rows] == ["answer_1"]
    assert rows[0].raw_text == "第一条"


def test_report_and_root_assessment_are_unique_per_interview(interview_engine):
    with Session(interview_engine) as session:
        session.add_all(
            [
                Assessment(
                    id="assessment_1",
                    interview_id="interview_a",
                    root_question_id="question_a",
                    criterion_results=[],
                    score=None,
                    coverage=0.0,
                    status="unmeasured",
                ),
                Report(
                    id="report_1",
                    interview_id="interview_a",
                    completion="incomplete",
                    overall_score=None,
                ),
            ]
        )
        session.commit()

    with Session(interview_engine) as session:
        session.add(
            Assessment(
                id="assessment_2",
                interview_id="interview_a",
                root_question_id="question_a",
                criterion_results=[],
                score=None,
                coverage=0.0,
                status="unmeasured",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    with Session(interview_engine) as session:
        session.add(
            Report(
                id="report_2",
                interview_id="interview_a",
                completion="incomplete",
                overall_score=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_event_seq_unique_per_operation(base_engine):
    with Session(base_engine) as session:
        _insert_rows(
            session,
            [
                Operation(
                    id="operation_a",
                    kind="answer_submit",
                    resource_type="interview",
                    resource_id="interview_a",
                    scope="local|POST|/x",
                    idempotency_key="k1",
                    input_hash="h",
                ),
                OperationEvent(
                    operation_id="operation_a",
                    seq=1,
                    event_type="node.started",
                    payload={"node_id": "a"},
                ),
            ],
        )
        session.commit()
    with Session(base_engine) as session:
        session.add(
            OperationEvent(
                operation_id="operation_a",
                seq=1,
                event_type="node.started",
                payload={"node_id": "b"},
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_foreign_key_rejects_dangling_reference(base_engine):
    """document.profile_id 指向不存在档案时必须被数据库拒绝。"""
    with Session(base_engine) as session:
        session.add(
            Document(
                id="doc_ghost",
                profile_id="profile_missing",
                kind="resume",
                filename_display="b.pdf",
                sha256="h",
                mime="application/pdf",
                size=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_activation_backfill_requires_exact_success_receipt_and_is_reversible(tmp_path):
    db = tmp_path / "activation-backfill.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "b4d7c2e91f30")
    engine = make_engine(f"sqlite:///{db}")
    with Session(engine) as session, session.begin():
        session.add(Profile(id="profile_legacy", display_name="合成旧资料", revision=5))
        session.flush()
        snapshots = [
            ProfileSnapshot(
                id=f"snapshot_{index}",
                profile_id="profile_legacy",
                revision=index,
                confirmed_claim_ids=[] if index == 4 else ["claim_synthetic"],
            )
            for index in range(5)
        ]
        session.add_all(snapshots)
        session.flush()
        # A previous generation's global Document ready is deliberately present;
        # it must not certify the snapshots whose operation result is unproven.
        session.add(
            Document(
                id="document_legacy",
                profile_id="profile_legacy",
                kind="user_input",
                filename_display="合成旧资料",
                sha256="0" * 64,
                mime="text/plain",
                size=1,
                extract_status="parsed",
                index_status="ready",
            )
        )
        for index in range(5):
            session.add(
                Operation(
                    id=f"operation_{index}",
                    kind="profile.confirm",
                    resource_type="profile",
                    resource_id="profile_legacy",
                    scope=f"local|POST|/confirm/{index}",
                    idempotency_key=f"key_{index}",
                    input_hash="0" * 64,
                    status="failed" if index == 2 else "succeeded",
                    result={
                        "profile_snapshot_id": f"snapshot_{index}",
                        "knowledge_generation": "wrong_generation"
                        if index == 1
                        else f"snapshot_{index}",
                        "source_ids": []
                        if index in {3, 4}
                        else [f"snapshot_{index}:claim_synthetic"],
                    },
                )
            )
    command.upgrade(cfg, "head")
    with Session(engine) as session:
        rows = (
            session.query(ProfileSnapshotActivation)
            .order_by(ProfileSnapshotActivation.snapshot_id)
            .all()
        )
        assert [row.status for row in rows] == [
            "ready",
            "pending",
            "pending",
            "pending",
            "pending",
        ]
        assert rows[0].operation_id == "operation_0"
        assert rows[0].receipt == {
            "generation": "snapshot_0",
            "source_ids": ["snapshot_0:claim_synthetic"],
        }
        assert all(row.operation_id is None for row in rows[1:])
    command.downgrade(cfg, "b4d7c2e91f30")
    with Session(engine) as session:
        assert [
            snapshot.id
            for snapshot in session.query(ProfileSnapshot).order_by(ProfileSnapshot.id)
        ] == [f"snapshot_{index}" for index in range(5)]
    command.upgrade(cfg, "head")
    with Session(engine) as session:
        assert session.get(ProfileSnapshotActivation, "snapshot_0").status == "ready"
