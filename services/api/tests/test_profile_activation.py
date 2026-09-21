"""Per-generation acceptance, failure recovery and Knowledge gates (synthetic data)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_api_contract import InMemoryKnowledge, create_profile

from zhijue.adapters.db.models import (
    Document,
    Operation,
    ProfileSnapshot,
    ProfileSnapshotActivation,
    ResumeDraft,
)
from zhijue.adapters.db.operations import OperationCommand, canon_scope
from zhijue.api.app import AppConfig, create_app
from zhijue.domain.operations import OperationStatus


def _config(tmp_path):
    return AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'activation.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )


@pytest.fixture()
def activation_client(tmp_path):
    knowledge = InMemoryKnowledge(fail=True)
    app = create_app(_config(tmp_path), knowledge=knowledge)
    with TestClient(app) as client:
        yield client, knowledge


def _profile(client, profile_id):
    return client.get(f"/api/v1/profiles/{profile_id}").json()["data"]


def _operation(client, accepted):
    return client.get(f"/api/v1/operations/{accepted['operation_id']}").json()["data"]


def _propose(client, profile_id, text="使用 FreeRTOS Queue 传递采样数据"):
    response = client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": _profile(client, profile_id)["revision"],
            "items": [{"section": "project", "text": text}],
        },
    )
    assert response.status_code == 201
    view = response.json()["data"]
    return {
        "expected_revision": view["revision"],
        "decisions": [
            {"claim_id": claim["id"], "action": "accept", "corrected_text": None}
            for claim in view["proposed_claims"]
        ],
    }


def _confirm(client, profile_id, payload, key="activation-confirm-0001"):
    response = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202
    return response.json()["data"]


def _retry(client, operation_id, revision, key):
    return client.post(
        f"/api/v1/operations/{operation_id}/retry",
        json={"expected_revision": revision},
        headers={"Idempotency-Key": key},
    )


def _plan(client, profile_id, key):
    return client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": _profile(client, profile_id)["revision"],
        },
        headers={"Idempotency-Key": key},
    )


def test_failed_confirmation_blocks_plans_then_retry_activates_same_snapshot(
    activation_client,
):
    client, knowledge = activation_client
    profile_id = create_profile(client)
    payload = _propose(client, profile_id)
    accepted = _confirm(client, profile_id, payload)
    failed = _profile(client, profile_id)
    snapshot_id = failed["latest_snapshot_id"]
    assert failed["snapshot_activation"] == {
        "snapshot_id": snapshot_id,
        "status": "failed",
        "operation_id": accepted["operation_id"],
    }
    assert failed["active_operation_id"] is None
    assert _operation(client, accepted)["error"]["retryable"] is True
    blocked = _plan(client, profile_id, "activation-plan-blocked")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "INVALID_STATE"
    # Document-global ready cannot lend its readiness to this failed generation.
    with Session(client.app.state.services.engine) as session, session.begin():
        for document in session.scalars(select(Document)):
            document.index_status = "ready"
    assert _plan(client, profile_id, "activation-plan-still-blocked").status_code == 409
    recovered_accept = client.post(
        f"/api/v1/profiles/{profile_id}/activate",
        json={"expected_revision": failed["revision"]},
        headers={"Idempotency-Key": "activation-cannot-reset-budget"},
    )
    assert recovered_accept.json()["data"]["operation_id"] == accepted["operation_id"]
    assert recovered_accept.json()["data"]["status"] == "failed"
    stale = _retry(
        client,
        accepted["operation_id"],
        failed["revision"] - 1,
        "activation-stale-retry",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    knowledge.fail = False
    response = _retry(
        client, accepted["operation_id"], failed["revision"], "activation-retry-success"
    )
    assert response.status_code == 202
    retried = response.json()["data"]
    operation = _operation(client, retried)
    ready = _profile(client, profile_id)
    assert operation["status"] == "succeeded"
    assert operation["parent_operation_id"] == accepted["operation_id"]
    assert operation["attempts"] == 2
    assert ready["latest_snapshot_id"] == snapshot_id
    assert ready["revision"] == failed["revision"]
    assert ready["confirmed_claims"] == failed["confirmed_claims"]
    assert ready["snapshot_activation"]["status"] == "ready"
    assert ready["snapshot_activation"]["operation_id"] == retried["operation_id"]
    replay = _retry(
        client, accepted["operation_id"], failed["revision"], "activation-retry-success"
    )
    assert replay.json()["data"]["operation_id"] == retried["operation_id"]
    assert replay.json()["data"]["status"] == "succeeded"
    assert knowledge.calls == 1
    with Session(client.app.state.services.engine) as session:
        assert session.scalar(select(func.count()).select_from(ProfileSnapshot)) == 1
    planned = _plan(client, profile_id, "activation-plan-recovered")
    assert planned.status_code == 202
    plan_operation = _operation(client, planned.json()["data"])
    assert plan_operation["status"] == "succeeded"
    interview_id = plan_operation["resource_id"]
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"expected_revision": 0},
        headers={"Idempotency-Key": "activation-start-recovered"},
    )
    assert started.status_code == 202
    assert _operation(client, started.json()["data"])["status"] == "succeeded"


def test_retry_budget_cannot_branch_or_reset_with_new_key(activation_client):
    client, _knowledge = activation_client
    profile_id = create_profile(client)
    first = _confirm(client, profile_id, _propose(client, profile_id))
    revision = _profile(client, profile_id)["revision"]
    second = _retry(client, first["operation_id"], revision, "activation-attempt-two")
    assert second.status_code == 202
    assert (
        _retry(
            client, first["operation_id"], revision, "activation-sibling-attempt"
        ).status_code
        == 409
    )
    second_data = second.json()["data"]
    third = _retry(
        client, second_data["operation_id"], revision, "activation-attempt-three"
    )
    assert third.status_code == 202
    third_data = third.json()["data"]
    assert _operation(client, third_data)["attempts"] == 3
    assert (
        _retry(
            client, third_data["operation_id"], revision, "activation-fourth-attempt"
        ).status_code
        == 409
    )
    same = client.post(
        f"/api/v1/profiles/{profile_id}/activate",
        json={"expected_revision": revision},
        headers={"Idempotency-Key": "activation-fresh-key-after-budget"},
    )
    assert same.json()["data"]["operation_id"] == third_data["operation_id"]
    with Session(client.app.state.services.engine) as session:
        assert session.scalar(select(func.count()).select_from(Operation)) == 3
        assert session.scalar(select(func.count()).select_from(ProfileSnapshot)) == 1


def test_start_checks_bound_generation_not_latest_or_document_status(activation_client):
    client, knowledge = activation_client
    knowledge.fail = False
    profile_id = create_profile(client)
    _confirm(client, profile_id, _propose(client, profile_id))
    old_snapshot = _profile(client, profile_id)["latest_snapshot_id"]
    plans = [
        _operation(
            client,
            _plan(client, profile_id, f"activation-old-plan-{index}").json()["data"],
        )
        for index in range(2)
    ]
    knowledge.fail = True
    failed = _confirm(
        client,
        profile_id,
        _propose(client, profile_id, "负责 UART DMA 错帧排查"),
        "activation-confirm-new-generation",
    )
    latest = _profile(client, profile_id)
    assert latest["latest_snapshot_id"] != old_snapshot
    assert latest["snapshot_activation"]["status"] == "failed"
    # The already-bound old generation is still ready even while shared documents fail.
    start_old = client.post(
        f"/api/v1/interviews/{plans[0]['resource_id']}/start",
        json={"expected_revision": 0},
        headers={"Idempotency-Key": "activation-start-old-ready"},
    )
    assert start_old.status_code == 202
    assert _operation(client, start_old.json()["data"])["status"] == "succeeded"
    knowledge.fail = False
    recovered = _retry(
        client,
        failed["operation_id"],
        latest["revision"],
        "activation-recover-new-generation",
    )
    assert _operation(client, recovered.json()["data"])["status"] == "succeeded"
    with Session(client.app.state.services.engine) as session, session.begin():
        session.get(ProfileSnapshotActivation, old_snapshot).status = "failed"
    # Conversely, a ready latest generation cannot unlock an unready bound snapshot.
    refused = client.post(
        f"/api/v1/interviews/{plans[1]['resource_id']}/start",
        json={"expected_revision": 0},
        headers={"Idempotency-Key": "activation-start-old-failed"},
    )
    assert refused.status_code == 409
    view = client.get(f"/api/v1/interviews/{plans[1]['resource_id']}").json()["data"]
    assert view["revision"] == 0 and view["active_operation_id"] is None


@pytest.mark.parametrize("running", [False, True])
def test_restart_recovers_accepted_snapshot_and_same_key_never_reconfirms(
    tmp_path, running
):
    config = _config(tmp_path)
    app = create_app(config, knowledge=InMemoryKnowledge())
    with TestClient(app) as client:
        profile_id = create_profile(client)
        payload = _propose(client, profile_id)
        key = "activation-lost-process-request"
        command = OperationCommand(
            kind="profile.confirm",
            resource_type="profile",
            resource_id=profile_id,
            scope=canon_scope(
                "local", "POST", f"/api/v1/profiles/{profile_id}/confirm"
            ),
            idempotency_key=key,
            input={"profile_id": profile_id, **payload},
        )
        accepted = app.state.services.profiles.accept_confirmation(
            profile_id,
            expected_revision=payload["expected_revision"],
            decisions=payload["decisions"],
            command=command,
            capacity_available=True,
        )
        before = _profile(client, profile_id)
        assert before["revision"] == 2 and before["confirmed_claims"]
        assert before["active_operation_id"] == accepted.operation.id
        assert before["snapshot_activation"]["status"] == "indexing"
        if running:
            app.state.services.operations.transition(
                accepted.operation.id, OperationStatus.RUNNING
            )
            with Session(app.state.services.engine) as session, session.begin():
                for document in session.scalars(select(Document)):
                    document.index_status = "indexing"
    restarted = create_app(config, knowledge=InMemoryKnowledge())
    with TestClient(restarted) as client:
        after = _profile(client, profile_id)
        assert after["snapshot_activation"]["status"] == "failed"
        assert after["active_operation_id"] is None
        assert all(
            document["index_status"] != "indexing" for document in after["documents"]
        )
        # Request shape must match ConfirmRequest's normalized optional field.
        replay = _confirm(client, profile_id, payload, key)
        assert replay["operation_id"] == accepted.operation.id
        assert replay["status"] == "interrupted"
        retry = _retry(
            client,
            accepted.operation.id,
            after["revision"],
            "activation-retry-restarted",
        )
        assert retry.status_code == 202
        assert _operation(client, retry.json()["data"])["status"] == "succeeded"
        final = _profile(client, profile_id)
        assert final["latest_snapshot_id"] == before["latest_snapshot_id"]
        assert final["confirmed_claims"] == before["confirmed_claims"]
        assert final["revision"] == before["revision"]


def test_confirmation_transaction_rolls_back_snapshot_and_decisions_on_acceptance_failure(
    activation_client, monkeypatch
):
    client, _knowledge = activation_client
    profile_id = create_profile(client)
    payload = _propose(client, profile_id)
    services = client.app.state.services
    repository = services.profiles._repo._operations
    original = repository.accept_in_session

    def fail_after_operation_insert(session, command):
        original(session, command)
        raise RuntimeError("synthetic acceptance commit failure")

    monkeypatch.setattr(repository, "accept_in_session", fail_after_operation_insert)
    command = OperationCommand(
        kind="profile.confirm",
        resource_type="profile",
        resource_id=profile_id,
        scope="local|POST|/confirm",
        idempotency_key="activation-atomic-failure",
        input=payload,
    )
    with pytest.raises(RuntimeError, match="synthetic acceptance"):
        services.profiles.accept_confirmation(
            profile_id,
            expected_revision=payload["expected_revision"],
            decisions=payload["decisions"],
            command=command,
            capacity_available=True,
        )
    profile = _profile(client, profile_id)
    assert profile["revision"] == 1
    assert profile["confirmed_claims"] == []
    assert profile["latest_snapshot_id"] is None
    assert [claim["id"] for claim in profile["proposed_claims"]] == [
        item["claim_id"] for item in payload["decisions"]
    ]
    with Session(services.engine) as session:
        for model in (Operation, ProfileSnapshot, ProfileSnapshotActivation):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_empty_confirmation_cannot_unlock_plan_or_resume(activation_client):
    client, knowledge = activation_client
    knowledge.fail = False
    profile_id = create_profile(client)
    payload = _propose(client, profile_id)
    payload["decisions"][0]["action"] = "reject"
    accepted = _confirm(client, profile_id, payload)
    profile = _profile(client, profile_id)
    assert _operation(client, accepted)["status"] == "failed"
    assert knowledge.calls == 0
    assert _plan(client, profile_id, "activation-empty-plan").status_code == 409
    resumed = client.post(
        f"/api/v1/profiles/{profile_id}/resume-drafts",
        json={
            "expected_revision": profile["revision"],
            "profile_snapshot_id": profile["latest_snapshot_id"],
        },
        headers={"Idempotency-Key": "activation-empty-resume"},
    )
    assert resumed.status_code == 409
    with Session(client.app.state.services.engine) as session:
        assert session.scalar(select(func.count()).select_from(ResumeDraft)) == 0


def test_pending_legacy_snapshot_activation_is_idempotent_and_stale_retry_is_refused(
    activation_client,
):
    client, knowledge = activation_client
    profile_id = create_profile(client)
    payload = _propose(client, profile_id)
    service = client.app.state.services.profiles
    legacy = service.confirm(
        profile_id,
        expected_revision=payload["expected_revision"],
        decisions=payload["decisions"],
    )
    body = {"expected_revision": legacy.revision}
    headers = {"Idempotency-Key": "activation-legacy-pending"}
    first = client.post(
        f"/api/v1/profiles/{profile_id}/activate", json=body, headers=headers
    )
    assert first.status_code == 202
    failed = first.json()["data"]
    assert _operation(client, failed)["status"] == "failed"
    replay = client.post(
        f"/api/v1/profiles/{profile_id}/activate", json=body, headers=headers
    )
    assert replay.json()["data"]["operation_id"] == failed["operation_id"]
    assert replay.json()["data"]["status"] == "failed"
    mismatch = client.post(
        f"/api/v1/profiles/{profile_id}/activate",
        json={"expected_revision": legacy.revision + 1},
        headers=headers,
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    knowledge.fail = False
    _confirm(
        client,
        profile_id,
        _propose(client, profile_id, "用 CAN 状态机完成节点通信"),
        "activation-newer-snapshot",
    )
    latest = _profile(client, profile_id)
    assert latest["latest_snapshot_id"] != legacy.latest_snapshot_id
    assert latest["snapshot_activation"]["status"] == "ready"
    stale = _retry(
        client, failed["operation_id"], latest["revision"], "activation-obsolete-retry"
    )
    assert stale.status_code == 409
    assert (
        _profile(client, profile_id)["snapshot_activation"]
        == latest["snapshot_activation"]
    )


def test_full_queue_rejects_new_confirmation_upload_and_plan_without_orphans(
    activation_client,
):
    client, knowledge = activation_client
    knowledge.fail = False
    profile_id = create_profile(client)
    _confirm(client, profile_id, _propose(client, profile_id))
    before = _profile(client, profile_id)
    next_payload = _propose(client, profile_id, "定位串口 DMA 环形缓冲区边界")
    services = client.app.state.services
    services.runner._pending = services.config.max_queued_operations
    try:
        confirm = client.post(
            f"/api/v1/profiles/{profile_id}/confirm",
            json=next_payload,
            headers={"Idempotency-Key": "activation-capacity-confirm"},
        )
        upload = client.post(
            f"/api/v1/profiles/{profile_id}/documents",
            data={
                "kind": "resume",
                "expected_revision": next_payload["expected_revision"],
            },
            files={"file": ("synthetic.txt", b"synthetic data", "text/plain")},
            headers={"Idempotency-Key": "activation-capacity-upload"},
        )
        plan = _plan(client, profile_id, "activation-capacity-plan")
        for response in (confirm, upload, plan):
            assert response.status_code == 429
            assert response.json()["error"]["code"] == "CAPACITY_LIMITED"
        view = _profile(client, profile_id)
        assert view["revision"] == next_payload["expected_revision"]
        assert view["latest_snapshot_id"] == before["latest_snapshot_id"]
        with Session(services.engine) as session:
            assert session.scalar(select(func.count()).select_from(Operation)) == 1
            assert (
                session.scalar(select(func.count()).select_from(ProfileSnapshot)) == 1
            )
    finally:
        services.runner._pending = 0
    accepted = _confirm(client, profile_id, next_payload, "activation-capacity-confirm")
    assert _operation(client, accepted)["status"] == "succeeded"


def test_document_upstream_failure_keeps_reason_and_requires_reupload(
    activation_client, monkeypatch
):
    from zhijue.domain.errors import UpstreamError

    client, _knowledge = activation_client
    profile_id = create_profile(client)
    services = client.app.state.services

    def unavailable(**_kwargs):
        raise UpstreamError("P-EXTRACT 材料解析超时。", timeout=True)

    monkeypatch.setattr(services.documents, "import_document", unavailable)
    response = client.post(
        f"/api/v1/profiles/{profile_id}/documents",
        data={"kind": "resume", "expected_revision": 0},
        files={"file": ("synthetic.txt", b"synthetic data", "text/plain")},
        headers={"Idempotency-Key": "activation-upload-failed"},
    )
    assert response.status_code == 202
    accepted = response.json()["data"]
    operation = _operation(client, accepted)
    assert operation["status"] == "failed"
    assert operation["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert operation["error"]["retryable"] is False
    assert (
        _retry(
            client, accepted["operation_id"], 0, "activation-upload-no-replay"
        ).status_code
        == 409
    )
    profile = _profile(client, profile_id)
    assert profile["revision"] == 0 and profile["documents"] == []


def test_document_parser_rejection_retains_its_actual_reason_code(activation_client):
    client, _knowledge = activation_client
    profile_id = create_profile(client)
    response = client.post(
        f"/api/v1/profiles/{profile_id}/documents",
        data={"kind": "resume", "expected_revision": 0},
        files={
            "file": ("corrupt.pdf", b"%PDF-1.4\nnot a valid PDF", "application/pdf")
        },
        headers={"Idempotency-Key": "activation-upload-corrupt-pdf"},
    )
    assert response.status_code == 202
    operation = _operation(client, response.json()["data"])
    assert operation["status"] == "failed"
    assert operation["error"]["code"] == "DOCUMENT_UNREADABLE"
    assert operation["error"]["retryable"] is False
    assert _profile(client, profile_id)["documents"] == []
