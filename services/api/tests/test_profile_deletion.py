"""M4-DELETE 测试：DELETE /profiles/{id} tombstone→级联清理与 GET /runtime/info。

断言业务可观察契约：删除后档案 404、派生行全部消失、Knowledge 只删确实
写过的来源、失败可显式重试且 deleting 期间拒绝新写入；不测内部实现细节。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_contract import InMemoryKnowledge, create_profile

from zhijue.adapters.db.models import (
    Claim,
    Document,
    Interview,
    Operation,
    Profile,
    ProfileSnapshot,
    Question,
    SourceBlock,
)
from zhijue.api.app import AppConfig, create_app


class FlakyDropKnowledge(InMemoryKnowledge):
    """索引正常、首次删除索引失败一次：验证“索引失败不动数据库 + 显式重试”。"""

    def __init__(self) -> None:
        super().__init__()
        self.drop_failures = 1

    async def drop_profile(self, *, profile_id, source_ids):
        if self.drop_failures:
            self.drop_failures -= 1
            raise RuntimeError("UPSTREAM_FAILED: synthetic knowledge outage")
        return await super().drop_profile(profile_id=profile_id, source_ids=source_ids)


@pytest.fixture()
def deletion_env(tmp_path):
    knowledge = InMemoryKnowledge()
    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'delete.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=knowledge)
    with TestClient(app) as client:
        yield client, app, knowledge


def _revision(client, profile_id):
    return client.get(f"/api/v1/profiles/{profile_id}").json()["data"]["revision"]


def _ready_profile(client, key_prefix="delete"):
    """走完 facts→confirm→activate 的档案，Knowledge 里确实有来源。"""
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": _revision(client, profile_id),
            "items": [
                {"section": "project", "text": "使用 FreeRTOS Queue 传递采样数据"}
            ],
        },
    )
    view = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": view["revision"],
            "decisions": [
                {"claim_id": claim["id"], "action": "accept"}
                for claim in view["proposed_claims"]
            ],
        },
        headers={"Idempotency-Key": f"{key_prefix}-confirm-0001"},
    )
    view = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    client.post(
        f"/api/v1/profiles/{profile_id}/activate",
        json={"expected_revision": view["revision"]},
        headers={"Idempotency-Key": f"{key_prefix}-activate-0001"},
    )
    return profile_id


def _delete(client, profile_id, revision, key):
    return client.delete(
        f"/api/v1/profiles/{profile_id}?expected_revision={revision}",
        headers={"Idempotency-Key": key},
    )


def _operation(client, operation_id):
    return client.get(f"/api/v1/operations/{operation_id}").json()["data"]


def _row_counts(app, profile_id):
    with Session(app.state.services.engine) as session:
        snapshot_ids = list(
            session.scalars(
                select(ProfileSnapshot.id).where(
                    ProfileSnapshot.profile_id == profile_id
                )
            )
        )
        interview_ids = (
            list(
                session.scalars(
                    select(Interview.id).where(
                        Interview.profile_snapshot_id.in_(snapshot_ids)
                    )
                )
            )
            if snapshot_ids
            else []
        )
        return {
            "profile": session.scalar(select(Profile).where(Profile.id == profile_id)),
            "documents": len(
                list(
                    session.scalars(
                        select(Document.id).where(Document.profile_id == profile_id)
                    )
                )
            ),
            "claims": len(
                list(
                    session.scalars(
                        select(Claim.id).where(Claim.profile_id == profile_id)
                    )
                )
            ),
            "blocks": len(
                list(
                    session.scalars(
                        select(SourceBlock.id)
                        .join(Document, Document.id == SourceBlock.document_id)
                        .where(Document.profile_id == profile_id)
                    )
                )
            ),
            "snapshots": len(snapshot_ids),
            "interviews": len(interview_ids),
            "questions": (
                len(
                    list(
                        session.scalars(
                            select(Question.id).where(
                                Question.interview_id.in_(interview_ids)
                            )
                        )
                    )
                )
                if interview_ids
                else 0
            ),
            "operations": len(
                list(
                    session.scalars(
                        select(Operation.id).where(Operation.resource_id == profile_id)
                    )
                )
            ),
        }


def test_delete_removes_profile_documents_sessions_and_knowledge(deletion_env):
    client, app, knowledge = deletion_env
    profile_id = _ready_profile(client)
    plan = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": _revision(client, profile_id),
        },
        headers={"Idempotency-Key": "delete-plan-0001"},
    )
    assert plan.status_code == 202
    plan_op = _operation(client, plan.json()["data"]["operation_id"])
    assert plan_op["status"] == "succeeded"
    interview_id = plan_op["resource_id"]
    interview = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    start = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"expected_revision": interview["revision"]},
        headers={"Idempotency-Key": "delete-start-0001"},
    )
    assert start.status_code == 202
    assert (
        _operation(client, start.json()["data"]["operation_id"])["status"]
        == "succeeded"
    )
    before = _row_counts(app, profile_id)
    assert before["interviews"] == 1 and before["questions"] == 5

    accepted = _delete(
        client, profile_id, _revision(client, profile_id), "delete-key-0001"
    )
    assert accepted.status_code == 202
    operation_id = accepted.json()["data"]["operation_id"]
    settled = _operation(client, operation_id)
    assert settled["status"] == "succeeded"
    assert settled["result"]["knowledge_sources_dropped"] == before["claims"]

    assert client.get(f"/api/v1/profiles/{profile_id}").status_code == 404
    after = _row_counts(app, profile_id)
    assert after["profile"] is None
    assert (
        after["documents"]
        == after["claims"]
        == after["blocks"]
        == after["snapshots"]
        == after["interviews"]
        == after["questions"]
        == 0
    )
    # 只保留 profile.delete 回执本身；confirm/activate/plan/start 一并清理。
    assert after["operations"] == 1
    assert len(knowledge.dropped) == 1
    assert knowledge.dropped[0][0] == profile_id
    assert knowledge.dropped[0][1]  # 确实删过来源，而不是空跳


def test_delete_requires_revision_and_replays_idempotently(deletion_env):
    client, _app, _knowledge = deletion_env
    profile_id = _ready_profile(client)
    revision = _revision(client, profile_id)
    missing_key = client.delete(
        f"/api/v1/profiles/{profile_id}?expected_revision={revision}"
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "INVALID_REQUEST"

    stale = _delete(client, profile_id, revision + 5, "delete-stale-0001")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"

    first = _delete(client, profile_id, revision, "delete-replay-0001")
    replay = _delete(client, profile_id, revision, "delete-replay-0001")
    assert first.status_code == replay.status_code == 202
    assert replay.json()["data"]["operation_id"] == first.json()["data"]["operation_id"]


def test_deleting_blocks_new_writes_until_retry_completes(tmp_path):
    """索引删除失败时档案保持 deleting：拒绝新写入，重试后完成清理。"""
    knowledge = FlakyDropKnowledge()
    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'flaky.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=knowledge)
    with TestClient(app) as client:
        profile_id = _ready_profile(client, key_prefix="flaky")
        revision = _revision(client, profile_id)
        accepted = _delete(client, profile_id, revision, "flaky-delete-0001")
        failed = _operation(client, accepted.json()["data"]["operation_id"])
        assert _row_counts(app, profile_id)["profile"].status == "deleting"
        # 刷新后必须仍能从 ProfileView 拿到恢复入口，否则 deleting 卡死。
        view = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
        assert view["status"] == "deleting"
        assert view["active_operation_id"] == failed["id"]
        assert failed["error"]["code"] == "UPSTREAM_FAILED"
        assert failed["error"]["retryable"] is True
        assert _row_counts(app, profile_id)["profile"].status == "deleting"

        blocked = client.post(
            f"/api/v1/profiles/{profile_id}/facts",
            json={
                "expected_revision": revision,
                "items": [{"section": "other", "text": "x"}],
            },
        )
        assert blocked.status_code >= 400

        retry = client.post(
            f"/api/v1/operations/{failed['id']}/retry",
            json={"expected_revision": revision},
            headers={"Idempotency-Key": "flaky-retry-0001"},
        )
        assert retry.status_code == 202
        child = _operation(client, retry.json()["data"]["operation_id"])
        assert child["status"] == "succeeded"
        assert child["parent_operation_id"] == failed["id"]
        assert client.get(f"/api/v1/profiles/{profile_id}").status_code == 404


def test_runtime_info_exposes_facts_without_secrets(deletion_env):
    client, _app, _knowledge = deletion_env
    response = client.get("/api/v1/runtime/info")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["run_mode"] == "fixture"
    assert body["data_mode"] == "synthetic"
    assert {"python", "openjiuwen", "pymilvus", "seed_bank_version"} <= set(
        body["versions"]
    )
    assert body["feature_flags"] == {
        "ocr_enabled": False,
        "memory_enabled": False,
        "external_web_enabled": False,
        "observer_mode_default": False,
        "remote_public_access_enabled": False,
    }
    assert body["health_summary"] == {
        "database": "sqlite",
        "knowledge": "configured",
        "model": "absent",
    }
    raw = response.text
    assert "sqlite:///" not in raw and "knowledge.db" not in raw
