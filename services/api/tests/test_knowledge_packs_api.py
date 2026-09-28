"""岗位知识包 HTTP 契约测试（api.md §9 / 主文件 Phase 4 验收）。

覆盖：列表/详情真实数据、异步导入 202→Operation、幂等复用与冲突、
外部上传默认 unreviewed、审核后才可选、面试受理时冻结绑定、
legacy 记录不捏造绑定、重试预算。全程离线（fixture 模式，无模型调用）。
"""

from __future__ import annotations

import json
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zhijue.api.app import AppConfig, create_app
from zhijue.application.profiles import ActivationReceipt

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_DIR = REPO_ROOT / "knowledge_packs" / "embedded_software_junior"


class InMemoryKnowledge:
    """confirm→索引需要 Knowledge 端口；fixture 模式下合成回执即可。"""

    async def index_snapshot(self, *, profile_id, generation, sources):
        return ActivationReceipt(
            generation=generation,
            source_ids=[s.source_id for s in sources],
            document_ids=[s.source_id for s in sources],
            embedding_logical_calls=0,
        )

    async def search(self, **kwargs):  # pragma: no cover
        return []

    async def drop_profile(self, **kwargs):  # pragma: no cover
        return len(kwargs.get("source_ids", []))


@pytest.fixture()
def client(tmp_path):
    config = AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'packs.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )
    app = create_app(config, knowledge=InMemoryKnowledge())
    with TestClient(app) as test_client:
        yield test_client


def builtin_files() -> dict[str, bytes]:
    return {
        path.relative_to(BUILTIN_DIR).as_posix(): path.read_bytes()
        for path in sorted(BUILTIN_DIR.rglob("*"))
        if path.is_file()
    }


def aux_pack_zip(*, pack_id: str = "demo-aux-pack", version: str = "0.1.0") -> bytes:
    """以内置资产为底造一个合法但“外部”的小包（服务端必须视为未审核）。"""
    files = builtin_files()
    manifest = json.loads(files["manifest.json"])
    seed_path = manifest["seeds"][0]
    manifest["pack_id"] = pack_id
    manifest["version"] = version
    manifest["name"] = "演示辅助包"
    manifest["seeds"] = [seed_path]
    files = {
        path: data
        for path, data in files.items()
        if path in {"manifest.json", "competencies.json", "sources.json", seed_path}
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def zip_from_repack(original: bytes) -> bytes:
    """相同内容换打包方式/顺序 → ZIP 字节不同、内容摘要相同。"""
    with zipfile.ZipFile(BytesIO(original)) as source:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as target:
            for info in reversed(source.infolist()):
                target.writestr(info.filename, source.read(info.filename))
        return buffer.getvalue()


def wait_operation(client, operation_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = client.get(f"/api/v1/operations/{operation_id}").json()["data"]
        if view["status"] in {"succeeded", "failed", "interrupted", "canceled"}:
            return view
        time.sleep(0.05)
    raise AssertionError(f"operation {operation_id} 未在时限内到达终态")


def import_pack(client, zip_bytes: bytes, key: str) -> dict:
    response = client.post(
        "/api/v1/knowledge-packs/import",
        files={"file": ("pack.zip", zip_bytes, "application/zip")},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def confirmed_profile(client, name: str, key_tag: str) -> dict:
    """facts→confirm 的最小可规划档案（与 test_interview_runtime 同路径）。"""
    profile_id = client.post("/api/v1/profiles", json={"display_name": name}).json()[
        "data"
    ]["id"]
    client.post(
        f"/api/v1/profiles/{profile_id}/facts",
        json={
            "expected_revision": 0,
            "items": [
                {
                    "section": "project",
                    "text": "我负责 FreeRTOS Queue、UART DMA 和 CAN 调试。",
                }
            ],
        },
    )
    profile = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    confirm = client.post(
        f"/api/v1/profiles/{profile_id}/confirm",
        json={
            "expected_revision": profile["revision"],
            "decisions": [
                {"claim_id": claim["id"], "action": "accept"}
                for claim in profile["proposed_claims"]
            ],
        },
        headers={"Idempotency-Key": f"packs-confirm-{key_tag}"},
    ).json()["data"]
    view = wait_operation(client, confirm["operation_id"])
    assert view["status"] == "succeeded", view["error"]
    return client.get(f"/api/v1/profiles/{profile_id}").json()["data"]


def test_list_excludes_candidate_data_and_marks_builtin_approved(client):
    body = client.get("/api/v1/knowledge-packs").json()["data"]
    builtin = next(
        i for i in body["items"] if i["pack_id"] == "embedded-software-junior"
    )
    assert builtin["review_status"] == "approved"
    assert builtin["approved_seed_count"] == 6 and builtin["seed_count"] == 6
    assert builtin["selectable"] is True
    assert body["default_pack_release_id"] == builtin["pack_release_id"]
    # 候选人可见面绝不泄露参考答案/评分细则字段。
    text = json.dumps(body, ensure_ascii=False)
    for forbidden in ("reference_points", "rubric_", "scoring_notes", "answer_text"):
        assert forbidden not in text


def test_detail_lists_sources_and_validation_checks(client):
    rid = client.get("/api/v1/knowledge-packs").json()["data"][
        "default_pack_release_id"
    ]
    detail = client.get(f"/api/v1/knowledge-packs/{rid}").json()["data"]
    assert detail["pack_release_id"] == rid
    assert len(detail["sources"]) >= 1
    assert all(
        s.get("url", "").startswith(("https://", "http://")) for s in detail["sources"]
    )
    checks = {c["check"] for c in detail["validation_checks"]}
    assert {"manifest", "seeds_schema", "content_digest"} <= checks
    assert (
        "格式通过、负责人审核与可用于新面试是三个独立状态" in detail["limitations_note"]
    )


def test_import_is_async_unreviewed_and_not_selectable(client):
    accepted = import_pack(client, aux_pack_zip(), "pack-import-0001")
    assert accepted["resource_type"] == "knowledge_pack_import"
    view = wait_operation(client, accepted["operation_id"])
    assert view["status"] == "succeeded", view["error"]
    result = view["result"]
    assert result["reused"] is False
    assert result["review_status"] == "unreviewed"
    assert result["selectable_for_new_interview"] is False
    items = client.get("/api/v1/knowledge-packs").json()["data"]["items"]
    aux = next(i for i in items if i["pack_id"] == "demo-aux-pack")
    assert aux["review_status"] == "unreviewed"
    assert aux["blocked_reasons"][0]["code"] == "PACK_REVIEW_PENDING"
    assert aux["approved_seed_count"] == 0


def test_import_idempotency_reuses_same_key_and_rejects_different_content(client):
    zip_bytes = aux_pack_zip()
    first = import_pack(client, zip_bytes, "pack-import-replay")
    wait_operation(client, first["operation_id"])
    replay = client.post(
        "/api/v1/knowledge-packs/import",
        files={"file": ("pack.zip", zip_bytes, "application/zip")},
        headers={"Idempotency-Key": "pack-import-replay"},
    )
    assert replay.status_code == 202
    assert replay.json()["data"]["operation_id"] == first["operation_id"]
    conflict = client.post(
        "/api/v1/knowledge-packs/import",
        files={
            "file": (
                "pack.zip",
                aux_pack_zip(version="0.9.9"),
                "application/zip",
            )
        },
        headers={"Idempotency-Key": "pack-import-replay"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_same_content_different_zip_reuses_release(client):
    zip_bytes = aux_pack_zip()
    accepted = import_pack(client, zip_bytes, "pack-import-a")
    wait_operation(client, accepted["operation_id"])
    # 重打包（不同 ZIP 字节、相同内容）→ 内容 digest 去重，不产生第二项。
    accepted2 = import_pack(client, zip_from_repack(zip_bytes), "pack-import-b")
    view2 = wait_operation(client, accepted2["operation_id"])
    assert view2["result"]["reused"] is True
    items = client.get("/api/v1/knowledge-packs").json()["data"]["items"]
    assert sum(1 for i in items if i["pack_id"] == "demo-aux-pack") == 1


def test_malformed_zip_fails_without_retryable_success(client):
    accepted = import_pack(client, b"not-a-zip-at-all", "pack-import-bad")
    view = wait_operation(client, accepted["operation_id"])
    assert view["status"] == "failed"
    assert view["error"]["retryable"] is False
    assert view["error"]["code"].startswith("PACK_")


def test_review_then_selectable_and_freeze_on_plan(client):
    accepted = import_pack(client, aux_pack_zip(), "pack-import-review")
    release_id = wait_operation(client, accepted["operation_id"])["result"][
        "release_id"
    ]
    services = client.app.state.services
    digest = services.knowledge_packs.detail_view(release_id)["content_digest"]
    review = services.knowledge_packs.record_review(
        release_id=release_id,
        expected_digest=digest,
        decision="approved",
        reviewer_id="review_api_owner_test",
        reviewer_role="owner",
        note="契约测试：负责人批准该条 Seed 原内容。",
    )
    assert review["decision"] == "approved"
    items = client.get("/api/v1/knowledge-packs").json()["data"]["items"]
    aux = next(i for i in items if i["pack_id"] == "demo-aux-pack")
    assert aux["selectable"] is True and aux["review_status"] == "approved"
    profile = confirmed_profile(client, "合成甲", "review-plan")
    planned = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile["id"],
            "profile_revision": profile["revision"],
            "pack_release_id": release_id,
        },
        headers={"Idempotency-Key": "plan-with-aux-pack"},
    )
    assert planned.status_code == 202, planned.text
    plan = wait_operation(client, planned.json()["data"]["operation_id"])
    assert plan["status"] == "succeeded", plan["error"]
    interview_id = planned.json()["data"]["resource_id"]
    view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    # 冻结绑定随受理落库：视图摘要 = 当时选定的 release + 内容摘要。
    assert view["knowledge_pack"]["binding"] == "frozen"
    assert view["knowledge_pack"]["pack_release_id"] == release_id
    assert view["knowledge_pack"]["content_digest"] == digest
    # 全局默认仍是内置包：本场不受“当前列表默认项”倒推影响。
    default_id = client.get("/api/v1/knowledge-packs").json()["data"][
        "default_pack_release_id"
    ]
    assert default_id != release_id
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"expected_revision": view["revision"]},
        headers={"Idempotency-Key": "start-aux-pack-interview"},
    )
    start_op = wait_operation(client, started.json()["data"]["operation_id"])
    assert start_op["status"] == "succeeded", start_op["error"]


def test_default_plan_freezes_builtin_release(client):
    profile = confirmed_profile(client, "合成丁", "default-plan")
    default_id = client.get("/api/v1/knowledge-packs").json()["data"][
        "default_pack_release_id"
    ]
    planned = client.post(
        "/api/v1/interviews",
        json={"profile_id": profile["id"], "profile_revision": profile["revision"]},
        headers={"Idempotency-Key": "plan-default-pack"},
    )
    plan = wait_operation(client, planned.json()["data"]["operation_id"])
    assert plan["status"] == "succeeded", plan["error"]
    view = client.get(
        f"/api/v1/interviews/{planned.json()['data']['resource_id']}"
    ).json()["data"]
    assert view["knowledge_pack"]["binding"] == "frozen"
    assert view["knowledge_pack"]["pack_release_id"] == default_id


def test_plan_rejects_unreviewed_pack_synchronously(client):
    accepted = import_pack(client, aux_pack_zip(version="0.3.0"), "pack-import-pending")
    release_id = wait_operation(client, accepted["operation_id"])["result"][
        "release_id"
    ]
    profile = client.post("/api/v1/profiles", json={"display_name": "合成乙"}).json()[
        "data"
    ]
    response = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile["id"],
            "profile_revision": profile["revision"],
            "pack_release_id": release_id,
        },
        headers={"Idempotency-Key": "plan-unreviewed-pack"},
    )
    # 包门槛先于档案门槛：未审核包不会消耗后台规划，也不会静默换默认包。
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PACK_REVIEW_PENDING"


def test_invalid_pack_release_id_format_rejected(client):
    profile = client.post("/api/v1/profiles", json={"display_name": "合成丙"}).json()[
        "data"
    ]
    response = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile["id"],
            "profile_revision": profile["revision"],
            "pack_release_id": "kpr_not-valid-hex!",
        },
        headers={"Idempotency-Key": "plan-bad-pack-id"},
    )
    assert response.status_code == 422


def test_import_upload_size_limit_enforced(client):
    from dataclasses import replace

    services = client.app.state.services
    services.knowledge_packs._limits = replace(
        services.knowledge_packs.limits, max_upload_bytes=256
    )
    response = client.post(
        "/api/v1/knowledge-packs/import",
        files={"file": ("big.zip", b"x" * 4096, "application/zip")},
        headers={"Idempotency-Key": "pack-import-too-large"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PACK_UPLOAD_TOO_LARGE"


def test_import_retry_is_parent_linked_and_bounded(client):
    accepted = import_pack(client, b"broken-zip-retry", "pack-import-retry")
    view = wait_operation(client, accepted["operation_id"])
    assert view["status"] == "failed"
    retry = client.post(
        f"/api/v1/operations/{view['id']}/retry",
        json={"expected_revision": 0},
        headers={"Idempotency-Key": "pack-import-retry-2"},
    )
    assert retry.status_code == 202, retry.text
    retry_view = wait_operation(client, retry.json()["data"]["operation_id"])
    assert retry_view["parent_operation_id"] == view["id"]
    assert retry_view["status"] == "failed"  # 输入仍是坏 ZIP：不伪装可恢复
    # 格式类错误反复重试也只是再次显式失败；预算耗尽后拒绝。
    third = client.post(
        f"/api/v1/operations/{retry_view['id']}/retry",
        json={"expected_revision": 0},
        headers={"Idempotency-Key": "pack-import-retry-3"},
    )
    assert third.status_code == 202
    third_view = wait_operation(client, third.json()["data"]["operation_id"])
    assert third_view["status"] == "failed"
    fourth = client.post(
        f"/api/v1/operations/{third_view['id']}/retry",
        json={"expected_revision": 0},
        headers={"Idempotency-Key": "pack-import-retry-4"},
    )
    assert fourth.status_code == 409
    assert fourth.json()["error"]["code"] == "RETRY_NOT_ALLOWED"


def test_legacy_interview_view_reports_unresolved_binding(client):
    """旧记录无可证实绑定：读路径显示 legacy_unresolved，不捏造版本。"""
    services = client.app.state.services
    summary = services.knowledge_packs.summary_for_interview(
        pack_release_id=None, pack_content_digest=None, competency_profile_id=None
    )
    assert summary["binding"] == "legacy_unresolved"
    assert summary["pack_release_id"] is None
    assert "重新创建计划" in summary["note"]
