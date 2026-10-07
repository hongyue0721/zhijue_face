"""Consumer-visible data-rule trust, frozen labels and non-embedded planning."""

import importlib.util
import json
import zipfile
from dataclasses import replace
from io import BytesIO

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pack_fixtures import REPO_ROOT, approve_test_pack, synthetic_service_pack_files
from sqlalchemy.orm import Session
from test_knowledge_packs_api import (
    confirmed_profile,
    import_pack,
    wait_operation,
)

from zhijue.adapters.db.models import KnowledgePackReview
from zhijue.application.knowledge_packs import InterviewPackBinding, PackDomainError
from zhijue.application.seed_bank import load_seed_bank
from zhijue.domain.competency_profiles import parse_competency_profile
from zhijue.domain.knowledge_packs import parse_competencies
from zhijue.domain.requisition import (
    JDSourceType,
    detect_competency,
    extract_requirements,
    make_snapshot,
)

pytest_plugins = ["test_knowledge_pack_freeze", "test_knowledge_packs_api"]


def upload_role(client, *, version="1.0.0", example=True, mutate=None):
    files = synthetic_service_pack_files(version=version, example=example)
    if mutate:
        mutate(files)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    accepted = import_pack(client, buffer.getvalue(), f"data-role-import-{version}")
    operation = wait_operation(client, accepted["operation_id"])
    assert operation["status"] == "succeeded", operation["error"]
    return operation["result"]["release_id"]


def plan_request(client, profile, release_id, key, **extra):
    return client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile["id"],
            "profile_revision": profile["revision"],
            "pack_release_id": release_id,
            **extra,
        },
        headers={"Idempotency-Key": key},
    )


def test_unregistered_draft_role_owner_approval_plan_question_and_report(client):
    release_id = upload_role(client)
    service = client.app.state.services.knowledge_packs
    before = client.get(f"/api/v1/knowledge-packs/{release_id}").json()["data"]
    assert before["competency_profile_id"] == "test-service-profile"
    assert not before["rules_reviewed"] and not before["selectable"]
    assert not any(c["technical_seed_available"] for c in before["capabilities"])
    profile = confirmed_profile(client, "合成服务候选人", "data-driven")
    blocked = plan_request(client, profile, release_id, "data-rule-unreviewed")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PACK_REVIEW_PENDING"
    approve_test_pack(service, release_id)
    after = client.get(f"/api/v1/knowledge-packs/{release_id}").json()["data"]
    assert after["rules_reviewed"] and after["selectable"]
    assert after["approved_seed_count"] == 6
    assert all(c["technical_seed_available"] for c in after["capabilities"])
    resolved = service.resolve(release_id)
    assert {s.review_status for s in resolved.seed_bank.live_eligible()} == {"draft"}
    planned = plan_request(client, profile, release_id, "data-rule-approved")
    assert planned.status_code == 202, planned.text
    assert (
        wait_operation(client, planned.json()["data"]["operation_id"])["status"]
        == "succeeded"
    )
    interview_id = planned.json()["data"]["resource_id"]
    view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    assert view["jd_source"]["source_type"] == "synthetic_demo_jd"
    assert view["jd_source"]["source_name"] == "SYNTHETIC_DEMO_JD_test-service-role"
    assert view["knowledge_pack"]["profile_digest"] == after["profile_digest"]
    labels = {
        c["competency_id"]: c["label"] for c in view["knowledge_pack"]["capabilities"]
    }
    assert labels == {f"service.skill.{i}": f"服务能力 {i}" for i in range(6)}
    assert all(s["competency"] in labels for s in view["root_plan"]["slots"])
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"expected_revision": view["revision"]},
        headers={"Idempotency-Key": "data-role-start"},
    )
    assert started.status_code == 202
    assert (
        wait_operation(client, started.json()["data"]["operation_id"])["status"]
        == "succeeded"
    )
    active = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    question = active["current_question"]
    assert question["seed_id"].startswith("seed_test_service_")
    assert (
        question["basis"]["competency_label"]
        == labels[question["basis"]["competency_id"]]
    )
    ended = client.post(
        f"/api/v1/interviews/{interview_id}/control",
        json={"expected_revision": active["revision"], "action": "end"},
        headers={"Idempotency-Key": "data-role-end"},
    )
    assert (
        wait_operation(client, ended.json()["data"]["operation_id"])["status"]
        == "succeeded"
    )
    report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
    assert report["knowledge_pack"] == active["knowledge_pack"]
    # An unreviewed default must not disable an approved nondefault role.
    default = service.detail_view(service.list_view()["default_pack_release_id"])
    assert not default["selectable"]
    assert client.get("/api/v1/health/ready").status_code == 200


@pytest.mark.parametrize(
    "missing", ["level1_reviewed", "level2_reviewed", "rules_reviewed"]
)
def test_owner_approval_requires_each_explicit_confirmation(client, missing):
    release_id = upload_role(client)
    service = client.app.state.services.knowledge_packs
    detail = service.detail_view(release_id)
    confirmations = {
        "level1_reviewed": True,
        "level2_reviewed": True,
        "rules_reviewed": True,
    }
    confirmations[missing] = False
    with pytest.raises(PackDomainError) as error:
        service.record_review(
            release_id=release_id,
            expected_digest=detail["content_digest"],
            decision="approved",
            reviewer_id="TEST_ONLY_owner",
            reviewer_role="owner",
            note="TEST_ONLY missing confirmation",
            **confirmations,
        )
    assert error.value.code == "PACK_REVIEW_CONFIRMATION_REQUIRED"
    assert service.detail_view(release_id)["review_status"] == "unreviewed"


def test_nonowner_cannot_record_pack_review(client):
    release_id = upload_role(client)
    service = client.app.state.services.knowledge_packs
    with pytest.raises(PackDomainError) as error:
        service.record_review(
            release_id=release_id,
            expected_digest=service.detail_view(release_id)["content_digest"],
            decision="approved",
            reviewer_id="TEST_ONLY_not_owner",
            reviewer_role="self_check",
            note="TEST_ONLY forbidden role",
            level1_reviewed=True,
            level2_reviewed=True,
            rules_reviewed=True,
        )
    assert error.value.code == "PACK_REVIEW_OWNER_REQUIRED"


def test_new_rule_bytes_need_new_review_and_old_summary_stays_frozen(client):
    service = client.app.state.services.knowledge_packs
    old_id = upload_role(client)
    approve_test_pack(service, old_id)
    old_binding = service.freeze_for_new_plan(old_id)
    old_summary = service.summary_for_interview(
        pack_release_id=old_id,
        pack_content_digest=old_binding.content_digest,
        competency_profile_id=old_binding.competency_profile_id,
    )

    def alter_rules(files):
        profile = json.loads(files["competencies.json"])
        profile["capabilities"][0]["label"] = "修改后的服务能力"
        files["competencies.json"] = json.dumps(profile, ensure_ascii=False).encode()

    new_id = upload_role(client, version="1.0.1", mutate=alter_rules)
    new_detail = service.detail_view(new_id)
    assert new_detail["profile_digest"] != old_summary["profile_digest"]
    assert not new_detail["rules_reviewed"]
    with pytest.raises(PackDomainError):
        service.freeze_for_new_plan(new_id)
    # Even copying a complete old review cannot authorize another content digest.
    with Session(client.app.state.services.engine) as session, session.begin():
        original = session.scalar(
            sa.select(KnowledgePackReview).where(
                KnowledgePackReview.release_id == old_id
            )
        )
        session.add(
            KnowledgePackReview(
                id="TEST_ONLY_copied_review",
                release_id=new_id,
                content_digest=original.content_digest,
                decision=original.decision,
                reviewer_id=original.reviewer_id,
                reviewer_role=original.reviewer_role,
                approved_seed_scope=original.approved_seed_scope,
                competency_profile_id=original.competency_profile_id,
                profile_version=original.profile_version,
                profile_digest=original.profile_digest,
                level1_reviewed=True,
                level2_reviewed=True,
                rules_reviewed=True,
            )
        )
    assert not service.detail_view(new_id)["rules_reviewed"]
    # Matching the new pack digest still cannot reuse the old rule-byte digest.
    with Session(client.app.state.services.engine) as session, session.begin():
        copied = session.get(KnowledgePackReview, "TEST_ONLY_copied_review")
        copied.content_digest = new_detail["content_digest"]
    assert service.detail_view(new_id)["review_status"] == "approved"
    assert not service.detail_view(new_id)["rules_reviewed"]
    with pytest.raises(PackDomainError) as error:
        service.freeze_for_new_plan(new_id)
    assert error.value.code == "PACK_RULES_REVIEW_PENDING"
    assert (
        len(service.resolve(old_id, binding=old_binding).seed_bank.live_eligible()) == 6
    )
    assert (
        service.summary_for_interview(
            pack_release_id=old_id,
            pack_content_digest=old_binding.content_digest,
            competency_profile_id=old_binding.competency_profile_id,
        )
        == old_summary
    )


def test_seed_only_legacy_schema1_can_continue_but_not_authorize_new_plans(
    pack_service,
):
    service, engine, repo = pack_service
    release = service.ensure_builtin_release()
    with Session(engine) as session:
        legacy_review = service.effective_review(session, release)
    bank = load_seed_bank(repo / release.storage_root / "seeds", live_only=True)
    binding = InterviewPackBinding(
        release_id=release.id,
        pack_id=release.pack_id,
        version=release.version,
        content_digest=release.content_digest,
        competency_profile_id=release.competency_profile_id,
        seed_bank_version=bank.version_fingerprint(),
        review_snapshot={
            "schema_version": 1,
            "review": legacy_review,
            "live_allowed_review_status": "approved",
        },
    )
    assert (
        len(service.resolve(release.id, binding=binding).seed_bank.live_eligible()) == 6
    )
    with pytest.raises(PackDomainError) as error:
        service.freeze_for_new_plan(release.id)
    assert error.value.code == "PACK_RULES_REVIEW_PENDING"
    invalid = replace(
        binding, review_snapshot={**binding.review_snapshot, "schema_version": 2}
    )
    with pytest.raises(PackDomainError) as error:
        service.resolve(release.id, binding=invalid)
    assert error.value.code == "PACK_REVIEW_SNAPSHOT_INVALID"


def test_selected_pack_without_example_requires_jd(client):
    release_id = upload_role(client, example=False)
    approve_test_pack(client.app.state.services.knowledge_packs, release_id)
    profile = confirmed_profile(client, "合成无示例候选人", "no-example")
    blocked = plan_request(client, profile, release_id, "no-example-missing-jd")
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "JD_REQUIRED"
    explicit = plan_request(
        client,
        profile,
        release_id,
        "no-example-explicit-jd",
        jd_text="必要项：skill0；skill1；skill2；skill3；skill4",
    )
    assert explicit.status_code == 202


def test_unreadable_historical_pack_returns_no_guessed_labels(pack_service):
    service, _, repo = pack_service
    release = service.ensure_builtin_release()
    (repo / release.storage_root / "competencies.json").unlink()
    summary = service.summary_for_interview(
        pack_release_id=release.id,
        pack_content_digest=release.content_digest,
        competency_profile_id=release.competency_profile_id,
    )
    assert summary["binding"] == "frozen_unavailable"
    assert summary["capabilities"] == []
    assert summary["profile_version"] is None and summary["profile_digest"] is None


def test_jd_first_match_and_direct_context_rules_are_distinct():
    profile = parse_competency_profile(
        parse_competencies(synthetic_service_pack_files())
    )
    assert detect_competency("skill1 skill0", profile=profile) == "service.skill.0"
    assert detect_competency("UART FreeRTOS", profile=profile) is None
    assert profile.direct_evidence_rules != profile.related_context_rules


def test_rule_review_migration_retains_legacy_nulls(tmp_path):
    migration_path = (
        REPO_ROOT
        / "services/api/migrations/versions/d63b8a24f710_competency_rules_review.py"
    )
    spec = importlib.util.spec_from_file_location(
        "rules_review_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE knowledge_pack_review (id TEXT PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO knowledge_pack_review VALUES ('old-seed-only')"
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        row = connection.execute(
            sa.text(
                "SELECT competency_profile_id, profile_version, profile_digest, level1_reviewed, level2_reviewed, rules_reviewed FROM knowledge_pack_review"
            )
        ).one()
        assert tuple(row) == (None,) * 6
    engine.dispose()


def test_import_rejects_seed_competency_outside_selected_profile(client):
    files = synthetic_service_pack_files()
    manifest = json.loads(files["manifest.json"])
    seed_path = manifest["seeds"][0]
    seed = json.loads(files[seed_path])
    seed["competency_id"] = "undeclared.skill"
    files[seed_path] = json.dumps(seed, ensure_ascii=False).encode()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    accepted = import_pack(client, buffer.getvalue(), "data-role-dangling-seed")
    failed = wait_operation(client, accepted["operation_id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "PACK_SEED_COMPETENCY_INVALID"
    assert not any(
        item["pack_id"] == "test-service-role"
        for item in client.get("/api/v1/knowledge-packs").json()["data"]["items"]
    )


def test_import_rejects_example_jd_without_recognizable_requirements(client):
    """未填 JD 时示例会直接用于出题，抽不出要求的示例必须在导入时就拒绝。"""
    files = synthetic_service_pack_files()
    files["examples/jd.txt"] = (
        "SYNTHETIC_DEMO_JD\n岗位练习要求（未用显式分区标题）：解释 skill0；解释 skill1"
    ).encode()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    accepted = import_pack(client, buffer.getvalue(), "data-role-unusable-example")
    failed = wait_operation(client, accepted["operation_id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "PACK_EXAMPLE_JD_INVALID"
    assert not any(
        item["pack_id"] == "test-service-role"
        for item in client.get("/api/v1/knowledge-packs").json()["data"]["items"]
    )


def _build_shipped_pack_zip(pack_dir, out_dir):
    spec = importlib.util.spec_from_file_location(
        "build_knowledge_pack", REPO_ROOT / "scripts/build_knowledge_pack.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder.build(pack_dir, out_dir).read_bytes()


def test_shipped_python_pack_imports_and_example_jd_covers_every_capability(
    client, tmp_path
):
    pack_dir = REPO_ROOT / "knowledge_packs/python_backend_junior"
    zip_bytes = _build_shipped_pack_zip(pack_dir, tmp_path)
    assert zip_bytes == _build_shipped_pack_zip(pack_dir, tmp_path / "again")

    accepted = import_pack(client, zip_bytes, "shipped-python-pack")
    operation = wait_operation(client, accepted["operation_id"])
    assert operation["status"] == "succeeded", operation["error"]
    result = operation["result"]
    assert result["review_status"] == "unreviewed"
    assert result["selectable_for_new_interview"] is False
    detail = client.get(f"/api/v1/knowledge-packs/{result['release_id']}").json()[
        "data"
    ]
    assert any(
        check["check"] == "example_jd" and check["status"] == "passed"
        for check in detail["validation_checks"]
    )

    profile = parse_competency_profile(
        parse_competencies(
            {"competencies.json": (pack_dir / "competencies.json").read_bytes()}
        )
    )
    snapshot = make_snapshot(
        snapshot_id="shipped-example",
        profile_id="shipped-example",
        raw_text=(pack_dir / "examples/jd.txt").read_text(encoding="utf-8"),
        source_type=JDSourceType.SYNTHETIC_DEMO_JD,
        source_name="SYNTHETIC_DEMO_JD_python-backend-junior",
    )
    extracted = {
        requirement.competency_id
        for requirement in extract_requirements(snapshot, profile=profile)
    }
    assert extracted == profile.competency_ids
