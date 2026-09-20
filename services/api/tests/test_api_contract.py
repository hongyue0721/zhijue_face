"""M1-03 HTTP 契约测试：/profiles、/facts、/confirm、/operations、/health。

断言 api.md §1/§2/§4/§7 的可观察契约：统一包封、错误码映射、202 受理语义、
幂等重放返回原操作真实状态、readiness 不猜。业务规则不在这里重复验证。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zhijue.api.app import AppConfig, create_app
from zhijue.application.profiles import ActivationReceipt


class InMemoryKnowledge:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def index_snapshot(self, *, profile_id, generation, sources):
        if self.fail:
            raise RuntimeError("UPSTREAM_FAILED: synthetic knowledge outage")
        self.calls += len(sources)
        return ActivationReceipt(
            generation=generation,
            source_ids=[s.source_id for s in sources],
            document_ids=[s.source_id for s in sources],
            embedding_logical_calls=self.calls,
        )

    async def search(self, *, profile_id, generation, allowed_source_ids, query, top_k):
        return []


@pytest.fixture()
def client(tmp_path):
    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=InMemoryKnowledge())
    with TestClient(app) as test_client:
        yield test_client


def create_profile(client, name="合成甲") -> str:
    response = client.post("/api/v1/profiles", json={"display_name": name})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"data", "meta"} and body["meta"]["request_id"].startswith(
        "req_"
    )
    return body["data"]["id"]


def test_profile_view_shape_follows_contract(client):
    profile_id = create_profile(client)
    body = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    assert set(body) == {
        "id",
        "revision",
        "display_name",
        "synthetic",
        "status",
        "documents",
        "proposed_claims",
        "confirmed_claims",
        "latest_snapshot_id",
    }
    assert body["revision"] == 0 and body["synthetic"] is True
    assert body["latest_snapshot_id"] is None
    assert body["documents"] == []


def test_missing_profile_maps_to_404_resource_not_found(client):
    response = client.get("/api/v1/profiles/profile_ghost")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "RESOURCE_NOT_FOUND"
    assert "profile_ghost" not in error["message"] or "不存在" in error["message"]


def test_facts_creates_proposed_claims_and_bumps_revision(client):
    profile_id = create_profile(client)
    response = client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [
                {"section": "project", "text": "我用 FreeRTOS Queue 传递采样数据"}
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["revision"] == 1
    assert len(data["proposed_claims"]) == 1
    claim = data["proposed_claims"][0]
    assert claim["status"] == "proposed"
    assert claim["source_block_ids"] and claim["source_quotes"]
    assert claim["source_quotes"][0]["origin"] == "user_input"


def test_stale_revision_returns_409_with_current_revision(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [{"section": "other", "text": "第一条"}],
        },
    )
    response = client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [{"section": "other", "text": "第二条"}],
        },
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "REVISION_CONFLICT"
    assert error["details"]["current_revision"] == 1
    assert error["retryable"] is False


def test_schema_validation_failure_is_422_and_does_not_write(client):
    profile_id = create_profile(client)
    response = client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": 0, "items": [{"section": "magic", "text": "x"}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert client.get(f"/api/v1/profiles/{profile_id}").json()["data"]["revision"] == 0


def test_confirm_accepts_202_then_completes_with_snapshot(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [{"section": "project", "text": "负责 UART 错帧排查"}],
        },
    )
    claim_id = client.get(f"/api/v1/profiles/{profile_id}").json()["data"][
        "proposed_claims"
    ][0]["id"]
    response = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": 1,
            "decisions": [{"claim_id": claim_id, "action": "accept"}],
        },
        headers={"Idempotency-Key": "confirm-demo-key-0001"},
    )
    assert response.status_code == 202
    accepted = response.json()["data"]
    assert accepted["status"] in {"queued", "running", "succeeded"}
    assert (
        accepted["resource_type"] == "profile" and accepted["resource_id"] == profile_id
    )
    assert (
        accepted["events_url"]
        == f"/api/v1/operations/{accepted['operation_id']}/events"
    )

    operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
        "data"
    ]
    assert operation["status"] == "succeeded"
    assert operation["result"]["knowledge_generation"]
    assert operation["error"] is None

    profile = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    assert profile["revision"] == 2
    assert profile["latest_snapshot_id"] == operation["result"]["profile_snapshot_id"]
    assert len(profile["confirmed_claims"]) == 1


def test_confirm_requires_idempotency_key(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": 0, "items": [{"section": "other", "text": "x"}]},
    )
    response = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": 1,
            "decisions": [{"claim_id": "claim_x", "action": "accept"}],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_confirm_idempotent_replay_returns_same_operation(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [{"section": "skill", "text": "熟悉 STM32 HAL"}],
        },
    )
    claim_id = client.get(f"/api/v1/profiles/{profile_id}").json()["data"][
        "proposed_claims"
    ][0]["id"]
    body = {
        "expected_revision": 1,
        "decisions": [{"claim_id": claim_id, "action": "accept"}],
    }
    headers = {"Idempotency-Key": "confirm-replay-key-0001"}
    first = client.post(
        f"/api/v1/profiles/{profile_id}/confirm", json=body, headers=headers
    ).json()["data"]
    second = client.post(
        f"/api/v1/profiles/{profile_id}/confirm", json=body, headers=headers
    ).json()["data"]
    assert second["operation_id"] == first["operation_id"]
    # 重放不得再把 revision 推一次（api.md §1：不因网络重试重复执行）。
    assert client.get(f"/api/v1/profiles/{profile_id}").json()["data"]["revision"] == 2


def test_confirm_same_key_different_input_conflicts(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": 0, "items": [{"section": "other", "text": "a"}]},
    )
    claim_id = client.get(f"/api/v1/profiles/{profile_id}").json()["data"][
        "proposed_claims"
    ][0]["id"]
    headers = {"Idempotency-Key": "confirm-conflict-key-01"}
    client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": 1,
            "decisions": [{"claim_id": claim_id, "action": "accept"}],
        },
        headers=headers,
    )
    response = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": 1,
            "decisions": [{"claim_id": claim_id, "action": "reject"}],
        },
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_knowledge_failure_marks_operation_failed_and_index_failed(tmp_path):
    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=InMemoryKnowledge(fail=True))
    with TestClient(app) as client:
        profile_id = create_profile(client)
        client.post(
            f"/api/v1/profiles/{profile_id}/facts",
            json={
                "expected_revision": 0,
                "items": [{"section": "other", "text": "事实"}],
            },
        )
        claim_id = client.get(f"/api/v1/profiles/{profile_id}").json()["data"][
            "proposed_claims"
        ][0]["id"]
        accepted = client.post(
            f"/api/v1/profiles/{profile_id}/confirm",
            json={
                "expected_revision": 1,
                "decisions": [{"claim_id": claim_id, "action": "accept"}],
            },
            headers={"Idempotency-Key": "confirm-fail-key-0001"},
        ).json()["data"]
        operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert operation["status"] == "failed"
        assert operation["error"]["code"] == "UPSTREAM_FAILED"
        assert operation["error"]["retryable"] is True
        # 202 之后失败必须可见：快照与 revision 已写，但索引状态明确是 failed。
        profile = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
        assert profile["revision"] == 2
        assert {doc["index_status"] for doc in profile["documents"]} == {"failed"}


def test_health_live_and_ready_report_mode_without_secrets(client):
    live = client.get("/api/v1/health/live")
    assert live.status_code == 200 and live.json()["data"]["status"] == "ok"
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    details = ready.json()["data"]
    assert details["run_mode"] == "fixture"
    assert "api_key" not in str(details).lower()


def test_live_mode_without_knowledge_is_not_ready(tmp_path):
    config = AppConfig(
        run_mode="live",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=None)
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_NOT_READY"


def test_internal_error_does_not_leak_internals(tmp_path, monkeypatch):
    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=InMemoryKnowledge())
    with TestClient(app, raise_server_exceptions=False) as client:
        profile_id = create_profile(client)

        def boom(*args, **kwargs):
            raise KeyError("/home/secret/path/business.db")

        monkeypatch.setattr(
            "zhijue.application.profiles.ProfileService.list_claims", boom
        )
        response = client.get(f"/api/v1/profiles/{profile_id}")
        assert response.status_code == 500
        error = response.json()["error"]
        assert error["code"] == "INTERNAL_ERROR"
        assert "/home/secret" not in error["message"]
        assert error["retryable"] is False


def test_search_gateway_used_by_service_is_async_only():
    """端口是 async：同步代码误用时必须显式失败，而不是悄悄串行阻塞事件循环。"""
    gateway = InMemoryKnowledge()
    result = gateway.search(
        profile_id="p", generation="g", allowed_source_ids=[], query="q", top_k=1
    )
    assert asyncio.iscoroutine(result)
    asyncio.run(result)


def test_operation_events_stream_replays_and_closes_at_terminal(client):
    """api.md §8：重放持久化事件、id 为 operation 内单调整数、终态后可重取快照。"""
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [{"section": "other", "text": "事件流事实"}],
        },
    )
    claim_id = client.get(f"/api/v1/profiles/{profile_id}").json()["data"][
        "proposed_claims"
    ][0]["id"]
    accepted = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": 1,
            "decisions": [{"claim_id": claim_id, "action": "accept"}],
        },
        headers={"Idempotency-Key": "events-stream-key-001"},
    ).json()["data"]
    operation_id = accepted["operation_id"]

    with client.stream("GET", accepted["events_url"]) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())
    blocks = [b for b in raw.split("\n\n") if b.strip() and not b.startswith(":")]
    parsed = []
    for block in blocks:
        lines = dict(
            line.split(": ", 1) for line in block.strip().splitlines() if ": " in line
        )
        parsed.append(lines)
    assert [int(p["id"]) for p in parsed] == [1, 2]  # 单调，无空洞
    assert [p["event"] for p in parsed] == ["operation.started", "operation.completed"]
    assert json.loads(parsed[-1]["data"])["payload"]["resource_id"] == profile_id

    operation = client.get(f"/api/v1/operations/{operation_id}").json()["data"]
    assert operation["last_event_seq"] == 2


def test_events_cursor_conflict_is_400(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": 0, "items": [{"section": "other", "text": "x"}]},
    )
    claim_id = client.get(f"/api/v1/profiles/{profile_id}").json()["data"][
        "proposed_claims"
    ][0]["id"]
    accepted = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": 1,
            "decisions": [{"claim_id": claim_id, "action": "accept"}],
        },
        headers={"Idempotency-Key": "events-cursor-key-01"},
    ).json()["data"]
    response = client.get(
        accepted["events_url"], params={"after": 1}, headers={"Last-Event-ID": "2"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EVENT_CURSOR"


def test_events_for_unknown_operation_is_404(client):
    response = client.get("/api/v1/operations/operation_ghost/events")
    assert response.status_code == 404


def test_app_bootstraps_missing_runtime_directories(tmp_path):
    """配置指向尚不存在的运行目录时必须自建，而不是启动即崩（M1-03 真机缺陷回归）。"""
    runtime_dir = tmp_path / "nested" / "runtime"
    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{runtime_dir / 'business.db'}",
        runtime_dir=runtime_dir,
        milvus_uri=runtime_dir / "knowledge.db",
    )
    app = create_app(config, knowledge=InMemoryKnowledge())
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
    assert (runtime_dir / "business.db").is_file()


def test_document_upload_accepts_202_and_imports_text(client):
    profile_id = create_profile(client)
    response = client.post(
        f"/api/v1/profiles/{profile_id}/documents",
        data={"kind": "resume", "expected_revision": 0},
        files={
            "file": (
                "resume.txt",
                "项目经历：STM32 UART DMA 接收".encode(),
                "text/plain",
            )
        },
        headers={"Idempotency-Key": "upload-demo-key-00001"},
    )
    assert response.status_code == 202
    accepted = response.json()["data"]
    operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
        "data"
    ]
    assert operation["status"] == "succeeded"
    document_id = operation["result"]["document_id"]
    assert operation["result"]["extract_status"] == "parsed"

    document = client.get(f"/api/v1/documents/{document_id}").json()["data"]
    assert document["kind"] == "resume"
    assert document["filename_display"] == "resume.txt"
    assert len(document["sha256"]) == 64
    assert "/" not in document["filename_display"]

    blocks = client.get(f"/api/v1/documents/{document_id}/blocks").json()["data"]
    assert len(blocks["items"]) == 1
    assert blocks["items"][0]["text"] == "项目经历：STM32 UART DMA 接收"
    assert blocks["items"][0]["origin"] == "text_layer"
    assert blocks["items"][0]["page_number"] is None


def test_document_upload_requires_idempotency_key(client):
    profile_id = create_profile(client)
    response = client.post(
        f"/api/v1/profiles/{profile_id}/documents",
        data={"kind": "resume", "expected_revision": 0},
        files={"file": ("resume.txt", b"text", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_document_upload_scan_only_pdf_reports_requires_text(tmp_path):
    """扫描件（无文字层）走上传链后必须明确 requires_text，不假装解析成功。"""
    from tests.fixtures_pdf import make_pdf

    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=InMemoryKnowledge())
    with TestClient(app) as client:
        profile_id = create_profile(client)
        accepted = client.post(
            f"/api/v1/profiles/{profile_id}/documents",
            data={"kind": "resume", "expected_revision": 0},
            files={"file": ("scan.pdf", make_pdf([""]), "application/pdf")},
            headers={"Idempotency-Key": "upload-scan-key-00001"},
        ).json()["data"]
        operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        document_id = operation["result"]["document_id"]
        document = client.get(f"/api/v1/documents/{document_id}").json()["data"]
        assert document["extract_status"] == "requires_text"
        assert document["warnings"], "必须给出可读提示"
        blocks = client.get(f"/api/v1/documents/{document_id}/blocks").json()["data"]
        assert blocks["items"] == []


def test_unknown_document_is_404(client):
    assert client.get("/api/v1/documents/document_ghost").status_code == 404
    assert client.get("/api/v1/documents/document_ghost/blocks").status_code == 404


# ---- M2-02：JD 与五题计划 ----


def confirm_all(client, profile_id: str, key: str) -> int:
    claims = client.get(f"/api/v1/profiles/{profile_id}").json()["data"][
        "proposed_claims"
    ]
    revision = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]["revision"]
    client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": revision,
            "decisions": [{"claim_id": c["id"], "action": "accept"} for c in claims],
        },
        headers={"Idempotency-Key": key},
    )
    return client.get(f"/api/v1/profiles/{profile_id}").json()["data"]["revision"]


def test_interview_plan_generates_five_slots_with_jd_provenance(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [
                {"section": "project", "text": "我用 FreeRTOS Queue 传递采样数据"},
                {
                    "section": "award",
                    "text": "比赛调试阶段定位并解决高速串口接收时偶发数据错帧问题，最终完成基本功能与部分发挥要求。",
                },
            ],
        },
    )
    revision = confirm_all(client, profile_id, "confirm-plan-key-0001")
    accepted = client.post(
        "/api/v1/interviews",
        json={"profile_id": profile_id, "profile_revision": revision},
        headers={"Idempotency-Key": "interview-plan-key-0001"},
    )
    assert accepted.status_code == 202
    payload = accepted.json()["data"]
    assert payload["resource_type"] == "interview"

    operation = client.get(f"/api/v1/operations/{payload['operation_id']}").json()[
        "data"
    ]
    assert operation["status"] == "succeeded", operation["error"]
    assert operation["result"]["slot_count"] == 5
    assert operation["result"]["interview_id"] == payload["resource_id"]

    view = client.get(f"/api/v1/interviews/{payload['resource_id']}").json()["data"]
    slots = view["root_plan"]["slots"]
    assert len(slots) == 5
    assert len({s["competency"] for s in slots}) >= 3
    assert all(s["seed_id"] is None for s in slots)
    assert all(s["verification_goal"] and s["reason_code"] for s in slots)
    # 未显式提供 JD 时只能使用服务端登记的合成配置，不能冒充真实岗位来源。
    assert view["jd_source"]["content_hash"]
    assert view["jd_source"]["source_type"] == "synthetic_demo_jd"
    assert view["jd_source"]["source_name"] == (
        "SYNTHETIC_DEMO_JD_preset_embedded_junior"
    )
    assert view["jd_source"]["is_synthetic"] is True
    assert view["jd_source"]["derived"] is False
    assert view["jd_source"]["source_url"] is None
    assert view["jd_source"]["upstream_url"] is None
    assert view["jd_requirements"] and all(
        r["source_span"]["quote"] for r in view["jd_requirements"]
    )
    assert view["status"] == "ready"


def test_interview_user_jd_cannot_self_declare_verified_source(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": 0, "items": [{"section": "other", "text": "x"}]},
    )
    revision = confirm_all(client, profile_id, "confirm-plan-user-jd-0001")
    jd_text = (
        "必要项：良好的 C 语言基础；理解 MCU 中断机制；"
        "能够调试 UART 通信；能够说明个人贡献；能够使用 Git。"
    )
    rejected = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": revision,
            "jd_text": jd_text,
            "jd_source_type": "real_jd_derived",
        },
        headers={"Idempotency-Key": "interview-forged-source-0001"},
    )
    assert rejected.status_code == 422

    accepted = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": revision,
            "jd_text": jd_text,
            "jd_source_name": "用户粘贴的目标岗位",
        },
        headers={"Idempotency-Key": "interview-user-source-0001"},
    )
    operation_id = accepted.json()["data"]["operation_id"]
    operation = client.get(f"/api/v1/operations/{operation_id}").json()["data"]
    assert operation["status"] == "succeeded", operation["error"]
    interview_id = operation["result"]["interview_id"]
    view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    assert view["jd_source"]["source_type"] == "user_provided"
    assert view["jd_source"]["source_name"] == "用户粘贴的目标岗位"
    assert view["jd_source"]["is_synthetic"] is False


def test_interview_requires_confirmed_profile(client):
    profile_id = create_profile(client)
    response = client.post(
        "/api/v1/interviews",
        json={"profile_id": profile_id, "profile_revision": 0},
        headers={"Idempotency-Key": "interview-unconfirmed-01"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROFILE_UNCONFIRMED"


def test_interview_rejects_other_role_preset_and_empty_jd(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": 0, "items": [{"section": "other", "text": "x"}]},
    )
    revision = confirm_all(client, profile_id, "confirm-plan-key-0002")
    bad_preset = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": revision,
            "role_preset": "embedded_junior",
        },
        headers={"Idempotency-Key": "interview-ok-0000000001"},
    )
    assert bad_preset.status_code == 202  # 合法 preset 正常受理
    invalid = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": revision,
            "role_preset": "backend_senior",
        },
        headers={"Idempotency-Key": "interview-bad-preset-01"},
    )
    assert invalid.status_code == 422
    empty_jd = client.post(
        "/api/v1/interviews",
        json={"profile_id": profile_id, "profile_revision": revision, "jd_text": "   "},
        headers={"Idempotency-Key": "interview-empty-jd-001"},
    )
    assert empty_jd.status_code == 202  # 受理为异步；失败体现在 operation
    op = client.get(
        f"/api/v1/operations/{empty_jd.json()['data']['operation_id']}"
    ).json()["data"]
    assert op["status"] == "failed"
    assert op["error"]["code"] == "INVALID_REQUEST"


def test_interview_unknown_jd_without_requirements_fails_operation(client):
    profile_id = create_profile(client)
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={"expected_revision": 0, "items": [{"section": "other", "text": "x"}]},
    )
    revision = confirm_all(client, profile_id, "confirm-plan-key-0003")
    accepted = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": revision,
            "jd_text": "我们是一家公司，欢迎加入。",
        },
        headers={"Idempotency-Key": "interview-bare-jd-0001"},
    ).json()["data"]
    op = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()["data"]
    assert op["status"] == "failed"
    assert op["error"]["code"] == "INVALID_REQUEST"


def test_interview_get_unknown_is_404(client):
    assert client.get("/api/v1/interviews/interview_ghost").status_code == 404


def test_openapi_exposes_control_and_report_contracts(client):
    document = client.get("/openapi.json").json()
    control_path = document["paths"]["/api/v1/interviews/{interview_id}/control"]
    report_path = document["paths"]["/api/v1/interviews/{interview_id}/report"]
    control_schema = document["components"]["schemas"]["ControlInterviewRequest"]
    exported = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts" / "openapi.json").read_text(
            encoding="utf-8"
        )
    )

    assert set(control_path) == {"post"}
    assert set(report_path) == {"get"}
    assert control_schema["properties"]["action"]["enum"] == ["skip", "end"]
    assert set(control_schema["required"]) == {"expected_revision", "action"}
    assert exported == document
