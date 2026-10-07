"""Admission audit snapshots and the historical built-in approval trust boundary."""

from __future__ import annotations

import importlib.util
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pack_fixtures import approve_test_pack
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import Base, KnowledgePackRelease, KnowledgePackReview
from zhijue.application.knowledge_packs import (
    BUILTIN_APPROVED_SEEDS,
    BUILTIN_PACK_STORAGE_ROOT,
    KnowledgePackService,
    PackDomainError,
)
from zhijue.domain.knowledge_packs import canonicalize_file_bytes, seed_content_hash

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def pack_service(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(
        REPO_ROOT / BUILTIN_PACK_STORAGE_ROOT, repo / BUILTIN_PACK_STORAGE_ROOT
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'packs.db'}")
    Base.metadata.create_all(engine)
    service = KnowledgePackService(
        engine,
        runtime_dir=runtime,
        repo_root=repo,
        default_pack_id="embedded-software-junior",
    )
    yield service, engine, repo
    engine.dispose()


def review(service, binding, *, decision, ids=None):
    return service.record_review(
        release_id=binding.release_id,
        expected_digest=binding.content_digest,
        decision=decision,
        reviewer_id="test-owner",
        reviewer_role="owner",
        note="Explicit test-only review decision",
        approved_seed_ids=ids,
        level1_reviewed=True,
        level2_reviewed=True,
        rules_reviewed=True,
    )


def test_admission_scope_survives_revocation_but_new_interviews_do_not(pack_service):
    service, _, _ = pack_service
    release = service.ensure_builtin_release()
    approve_test_pack(service, release.id)
    binding = service.freeze_for_new_plan(release.id)
    original = service.resolve(release.id, binding=binding)
    review(service, binding, decision="rejected")

    frozen = service.resolve(release.id, binding=binding)
    assert frozen.review == original.review
    assert frozen.binding == binding
    assert len(frozen.seed_bank.seeds) == 6
    assert not service.resolve(release.id).seed_bank.seeds
    with pytest.raises(PackDomainError) as error:
        service.freeze_for_new_plan(release.id)
    assert error.value.code == "PACK_REVIEW_REJECTED"


def test_new_admissions_use_changed_scope_while_old_scope_is_stable(pack_service):
    service, _, _ = pack_service
    release = service.ensure_builtin_release()
    approve_test_pack(service, release.id)
    old = service.freeze_for_new_plan(None)
    chosen = next(iter(BUILTIN_APPROVED_SEEDS))
    review(service, old, decision="approved", ids=[chosen])
    new = service.freeze_for_new_plan(None)
    assert (
        old.review_snapshot["review"]["review_id"]
        != new.review_snapshot["review"]["review_id"]
    )
    assert len(service.resolve(release.id, binding=old).seed_bank.seeds) == 6
    assert [
        seed.id for seed in service.resolve(release.id, binding=new).seed_bank.seeds
    ] == [chosen]
    assert old.seed_bank_version != new.seed_bank_version


def test_frozen_scope_still_rejects_corrupted_content(pack_service):
    service, _, repo = pack_service
    release = service.ensure_builtin_release()
    approve_test_pack(service, release.id)
    binding = service.freeze_for_new_plan(release.id)
    path = repo / BUILTIN_PACK_STORAGE_ROOT / "sources.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(PackDomainError) as error:
        service.resolve(release.id, binding=binding)
    assert error.value.code == "PACK_CONTENT_CORRUPTED"
    item = service.list_view()["items"][0]
    assert item["review_status"] == "approved"  # 历史审核不会因存储损坏被伪改。
    assert item["validation_status"] == "failed"
    assert item["selectable"] is False
    assert item["blocked_reasons"][0]["code"] == "PACK_CONTENT_CORRUPTED"
    detail = service.detail_view(release.id)
    assert detail["selectable"] is False
    assert detail["validation_status"] == "failed"
    assert any(
        check["check"] == "storage_integrity" and check["status"] == "failed"
        for check in detail["validation_checks"]
    )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"review_snapshot": None}, "PACK_REVIEW_SNAPSHOT_MISSING"),
        ({"content_digest": "sha256:invalid"}, "PACK_BINDING_MISMATCH"),
        ({"seed_bank_version": "wrong"}, "PACK_BINDING_MISMATCH"),
        ({"review_snapshot": {}}, "PACK_REVIEW_SNAPSHOT_INVALID"),
    ],
)
def test_legacy_and_invalid_bindings_never_borrow_latest_approval(
    pack_service, changes, code
):
    service, _, _ = pack_service
    release = service.ensure_builtin_release()
    approve_test_pack(service, release.id)
    binding = replace(service.freeze_for_new_plan(release.id), **changes)
    with pytest.raises(PackDomainError) as error:
        service.resolve(release.id, binding=binding)
    assert error.value.code == code


def test_historical_baseline_matches_unchanged_reviewed_assets(pack_service):
    service, _, repo = pack_service
    release = service.ensure_builtin_release()
    assert release.approved_seed_count == 0
    assert service.detail_view(release.id)["rules_reviewed"] is False
    with pytest.raises(PackDomainError) as error:
        service.freeze_for_new_plan(release.id)
    assert error.value.code == "PACK_RULES_REVIEW_PENDING"
    for seed_id, (version, digest) in BUILTIN_APPROVED_SEEDS.items():
        path = repo / BUILTIN_PACK_STORAGE_ROOT / "seeds" / f"{seed_id}.json"
        raw = canonicalize_file_bytes(path.read_bytes(), path=path.name)
        assert json.loads(raw)["version"] == version
        assert seed_content_hash(raw) == digest


@pytest.mark.parametrize("field", ["stem", "version"])
def test_same_id_changed_seed_in_fresh_database_cannot_inherit_review(
    pack_service, field
):
    service, engine, repo = pack_service
    seed_id = next(iter(BUILTIN_APPROVED_SEEDS))
    path = repo / BUILTIN_PACK_STORAGE_ROOT / "seeds" / f"{seed_id}.json"
    payload = json.loads(path.read_bytes())
    payload[field] = (
        "0.2.2" if field == "version" else payload[field] + " 请说明验证方法。"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PackDomainError) as error:
        service.ensure_builtin_release()
    assert error.value.code == "PACK_BUILTIN_MIGRATION_INVALID"
    with Session(engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(KnowledgePackReview))
            == 0
        )
        release = session.scalar(sa.select(KnowledgePackRelease))
        assert release.approved_seed_count == 0


def test_snapshot_migration_preserves_legacy_unknown_scope(tmp_path):
    migration_path = (
        REPO_ROOT
        / "services/api/migrations/versions/c91f8b34d602_interview_review_snapshot.py"
    )
    spec = importlib.util.spec_from_file_location(
        "review_snapshot_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE interview (id VARCHAR(128) PRIMARY KEY)")
        )
        connection.execute(sa.text("INSERT INTO interview (id) VALUES ('legacy')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        assert connection.execute(
            sa.text("SELECT id, pack_review_snapshot FROM interview")
        ).one() == ("legacy", None)
    engine.dispose()
