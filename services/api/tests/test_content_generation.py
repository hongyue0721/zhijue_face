"""M4-02 grounded coaching/resume operations over persisted interview evidence."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_interview_runtime import (
    InMemoryKnowledge,
    ScriptedAnalyzer,
    _config,
    _prepare_active_interview,
)

from zhijue.adapters.db.models import Operation, ProfileSnapshot, Report, ResumeDraft
from zhijue.api.app import create_app
from zhijue.application.answer_workflow import AnalysisResult, ModelRequestError


class ScriptedContentGenerator:
    """Fixture model boundary; orchestration remains the installed SDK workflow."""

    def __init__(self, *modes: str, max_total_attempts: int = 3) -> None:
        self._modes = deque(modes or ("valid",))
        self.max_total_attempts = max_total_attempts
        self.calls: list[dict[str, object]] = []

    def public_summary(self):
        return {"provider": "fixture", "model": "scripted-content"}

    async def generate(self, *, task, payload) -> AnalysisResult:
        self.calls.append({"task": task, "payload": payload})
        mode = self._modes.popleft() if self._modes else "valid"
        if mode == "invalid":
            return AnalysisResult(content="not-json")
        if mode in {"transient", "permanent"}:
            raise ModelRequestError(
                "controlled model failure",
                retryable=mode == "transient",
                status_code=503 if mode == "transient" else 401,
            )
        if task == "coach_answers":
            items = []
            # valid_with_claim 让第二段引用一条已确认事实，覆盖按段来源的两种类型。
            cited = (
                next(iter(payload["allowed_claims"].items()))
                if mode == "valid_with_claim"
                else None
            )
            for root_id, root_answers in payload["answers_by_root"].items():
                answer_id, answer_text = next(iter(root_answers.items()))
                segments = [
                    {
                        "text": answer_text,
                        "source_refs": [
                            {
                                "type": "answer_quote",
                                "answer_id": answer_id,
                                "exact_quote": answer_text,
                            }
                        ],
                    }
                ]
                if cited is not None:
                    segments.append(
                        {
                            "text": cited[1],
                            "source_refs": [{"type": "claim", "claim_id": cited[0]}],
                        }
                    )
                items.append(
                    {
                        "root_question_id": root_id,
                        "rewritten_answer": "".join(
                            segment["text"] for segment in segments
                        ),
                        "segments": segments,
                        "used_claim_ids": [cited[0]] if cited is not None else [],
                        "changes": ["保持事实不变，整理表达顺序"],
                        "missing_facts": [],
                        "cautions": [],
                    }
                )
            candidate = {
                "schema_version": "1.0.0",
                "report_id": payload["report_id"],
                "items": items,
            }
        else:
            claim_id, claim_text = next(iter(payload["allowed_claims"].items()))
            candidate = {
                "schema_version": "1.0.0",
                "draft_id": payload["draft_id"],
                "sections": [
                    {
                        "section_id": "projects",
                        "title": "项目经历",
                        "items": [
                            {
                                "item_id": "item_fixture",
                                "text": claim_text,
                                "claim_ids": [claim_id],
                                "reason": "直接使用已确认项目事实",
                            }
                        ],
                    }
                ],
                "missing_facts": [],
                "cautions": [],
            }
        return AnalysisResult(
            content=json.dumps(candidate, ensure_ascii=False),
            input_tokens=40,
            output_tokens=20,
            total_tokens=60,
            cost=None,
        )


def _complete_after_one_answer(client: TestClient) -> tuple[dict, dict]:
    view = _prepare_active_interview(client)
    interview_id = view["id"]
    answer = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        json={
            "expected_revision": view["revision"],
            "question_id": view["current_question"]["id"],
            "client_turn_id": "content-turn-0001",
            "answer_text": "我先记录现象，再通过日志定位问题。",
        },
        headers={"Idempotency-Key": "content-answer-key-0001"},
    ).json()["data"]
    operation = client.get(f"/api/v1/operations/{answer['operation_id']}").json()[
        "data"
    ]
    assert operation["status"] == "succeeded", operation["error"]
    view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    ended = client.post(
        f"/api/v1/interviews/{interview_id}/control",
        json={"expected_revision": view["revision"], "action": "end"},
        headers={"Idempotency-Key": "content-end-key-0001"},
    ).json()["data"]
    end_operation = client.get(f"/api/v1/operations/{ended['operation_id']}").json()[
        "data"
    ]
    assert end_operation["status"] == "succeeded", end_operation["error"]
    completed = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
    return completed, report


def test_coaching_and_resume_draft_complete_without_mutating_score(tmp_path):
    generator = ScriptedContentGenerator("valid", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report_before = _complete_after_one_answer(client)
        assert report_before["improvements_status"] == "not_requested"
        accepted = client.post(
            f"/api/v1/interviews/{interview['id']}/report/improvements",
            json={"expected_revision": report_before["revision"]},
            headers={"Idempotency-Key": "content-coach-key-0001"},
        ).json()["data"]
        coach_operation = client.get(
            f"/api/v1/operations/{accepted['operation_id']}"
        ).json()["data"]
        assert coach_operation["status"] == "succeeded", coach_operation["error"]
        report = client.get(f"/api/v1/interviews/{interview['id']}/report").json()[
            "data"
        ]
        assert report["improvements_status"] == "ready"
        assert report["overall_score"] == report_before["overall_score"]
        assert len(report["improved_answers"]) == 1
        assert report["improved_answers"][0]["original_answers"][0]["raw_text"]
        assert report["run_metadata"]["content_generation"]["workflow"] == "openjiuwen"
        coach_events = client.app.state.services.operations.events_after(
            accepted["operation_id"], 0
        )
        assert [event.event_type for event in coach_events] == [
            "operation.started",
            "coaching.ready",
            "operation.completed",
        ]

        replay = client.post(
            f"/api/v1/interviews/{interview['id']}/report/improvements",
            json={"expected_revision": report_before["revision"]},
            headers={"Idempotency-Key": "content-coach-key-0002"},
        ).json()["data"]
        assert replay["operation_id"] == accepted["operation_id"]
        assert len(generator.calls) == 1

        profile = client.get(f"/api/v1/profiles/{interview['profile_id']}").json()[
            "data"
        ]
        resume_accepted = client.post(
            f"/api/v1/profiles/{interview['profile_id']}/resume-drafts",
            json={
                "expected_revision": profile["revision"],
                "profile_snapshot_id": interview["profile_snapshot_id"],
                "interview_id": interview["id"],
            },
            headers={"Idempotency-Key": "content-resume-key-0001"},
        ).json()["data"]
        resume_operation = client.get(
            f"/api/v1/operations/{resume_accepted['operation_id']}"
        ).json()["data"]
        assert resume_operation["status"] == "succeeded", resume_operation["error"]
        draft = client.get(
            f"/api/v1/resume-drafts/{resume_accepted['resource_id']}"
        ).json()["data"]
        assert draft["status"] == "draft"
        assert draft["sections"][0]["items"][0]["claim_ids"]
        assert draft["changes"][0]["before"]
        assert draft["source_claims"][0]["id"] in draft["source_claim_ids"]
        assert "raw_text" not in draft["target_context"]
        assert draft["run_metadata"]["workflow"] == "openjiuwen"
        resume_events = client.app.state.services.operations.events_after(
            resume_accepted["operation_id"], 0
        )
        assert [event.event_type for event in resume_events] == [
            "operation.started",
            "resume_draft.ready",
            "operation.completed",
        ]

        accepted_draft = client.post(
            f"/api/v1/resume-drafts/{draft['id']}/accept",
            json={"expected_revision": draft["revision"]},
        ).json()["data"]
        assert accepted_draft["status"] == "accepted"
        assert len(generator.calls) == 2
        with Session(client.app.state.services.engine) as session:
            assert session.scalar(select(func.count(Report.id))) == 1
            assert session.scalar(select(func.count(ResumeDraft.id))) == 1


def test_report_returns_text_of_claims_cited_by_improvement_segments(tmp_path):
    """前端按段展示出处时，需要被引用的已确认事实原文，而不只是 ID。"""
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=ScriptedContentGenerator("valid_with_claim"),
    )
    with TestClient(app) as client:
        interview, report_before = _complete_after_one_answer(client)
        assert report_before["source_claims"] == []
        accepted = client.post(
            f"/api/v1/interviews/{interview['id']}/report/improvements",
            json={"expected_revision": report_before["revision"]},
            headers={"Idempotency-Key": "content-coach-claim-key-0001"},
        ).json()["data"]
        operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert operation["status"] == "succeeded", operation["error"]
        report = client.get(f"/api/v1/interviews/{interview['id']}/report").json()[
            "data"
        ]
        item = report["improved_answers"][0]
        cited = [
            ref["claim_id"]
            for segment in item["segments"]
            for ref in segment["source_refs"]
            if ref["type"] == "claim"
        ]
        assert cited and item["used_claim_ids"] == cited
        profile = client.get(f"/api/v1/profiles/{interview['profile_id']}").json()[
            "data"
        ]
        confirmed = {
            claim["id"]: claim["text"] for claim in profile["confirmed_claims"]
        }
        assert report["source_claims"] == [
            {"id": cited[0], "text": confirmed[cited[0]]}
        ]


def test_failed_coaching_automatically_corrects_and_preserves_original(tmp_path):
    generator = ScriptedContentGenerator("invalid", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report_before = _complete_after_one_answer(client)
        accepted = client.post(
            f"/api/v1/interviews/{interview['id']}/report/improvements",
            json={"expected_revision": report_before["revision"]},
            headers={"Idempotency-Key": "content-fail-key-0001"},
        ).json()["data"]
        failed_operation = client.get(
            f"/api/v1/operations/{accepted['operation_id']}"
        ).json()["data"]
        assert failed_operation["status"] == "failed"
        assert failed_operation["error"]["code"] == "UPSTREAM_FAILED"
        assert failed_operation["retry_trigger"] is None
        child_id = failed_operation["next_operation_id"]
        assert child_id is not None
        retry_operation = client.get(f"/api/v1/operations/{child_id}").json()["data"]
        assert retry_operation["status"] == "succeeded", retry_operation["error"]
        assert retry_operation["parent_operation_id"] == accepted["operation_id"]
        assert retry_operation["retry_trigger"] == "automatic"
        assert retry_operation["retry_reason"] == "correction"
        assert retry_operation["chain_started_at"] == failed_operation["created_at"]
        assert retry_operation["attempt_limit"] == 3
        assert retry_operation["attempts"] == 2
        assert retry_operation["next_operation_id"] is None
        assert "repair_context" not in generator.calls[0]["payload"]
        correction = generator.calls[1]["payload"]["repair_context"]
        assert correction["previous_output"] == "not-json"
        assert correction["issues"]
        events = client.app.state.services.operations.events_after(child_id, 0)
        assert events[0].event_type == "operation.retry_scheduled"
        assert events[0].payload == {
            "parent_operation_id": accepted["operation_id"],
            "trigger": "automatic",
            "reason": "correction",
        }
        assert events[1].payload == {
            "kind": retry_operation["kind"],
            "resource_id": retry_operation["resource_id"],
        }
        public = json.dumps(
            [failed_operation, retry_operation, [event.payload for event in events]]
        )
        assert "not-json" not in public
        assert "previous_output" not in public
        assert (
            client.get(f"/api/v1/operations/{accepted['operation_id']}").json()["data"]
            == failed_operation
        )
        ready_report = client.get(
            f"/api/v1/interviews/{interview['id']}/report"
        ).json()["data"]
        assert ready_report["id"] == report_before["id"]
        assert ready_report["improvements_status"] == "ready"
        assert ready_report["overall_score"] == report_before["overall_score"]
        assert ready_report["improved_answers"][0]["original_answers"][0]["raw_text"]
        assert len(generator.calls) == 2


def test_failed_generation_preserves_recovery_key_until_success(tmp_path):
    """失败态 active_operation_id 是跨刷新恢复键（api.md §6）：非空且=失败链尾，
    成功落库后才清 null。前端凭它 GET Operation 并走 /retry，不依赖 localStorage。"""
    generator = ScriptedContentGenerator("invalid", "invalid", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted = client.post(
            f"/api/v1/interviews/{interview['id']}/report/improvements",
            json={"expected_revision": report["revision"]},
            headers={"Idempotency-Key": "recover-coach-0001"},
        ).json()["data"]
        first_failed = accepted["operation_id"]

        # The automatic child is already the failed recovery tail.
        failed_report = client.get(
            f"/api/v1/interviews/{interview['id']}/report"
        ).json()["data"]
        assert failed_report["improvements_status"] == "failed"
        original = client.get(f"/api/v1/operations/{first_failed}").json()["data"]
        second_failed = original["next_operation_id"]
        assert second_failed is not None
        assert failed_report["active_operation_id"] == second_failed
        automatic = client.get(f"/api/v1/operations/{second_failed}").json()["data"]
        assert automatic["status"] == "failed"
        assert automatic["retry_trigger"] == "automatic"
        assert automatic["next_operation_id"] is None
        assert automatic["attempts"] == 2
        assert failed_report["overall_score"] == report["overall_score"]
        assert failed_report["improved_answers"] == []
        assert len(generator.calls) == 2
        # 从链尾恢复键重试成功：恢复键清除为 null。
        final = client.post(
            f"/api/v1/operations/{second_failed}/retry",
            json={"expected_revision": failed_report["revision"]},
            headers={"Idempotency-Key": "recover-coach-0003"},
        ).json()["data"]
        manual = client.get(f"/api/v1/operations/{final['operation_id']}").json()[
            "data"
        ]
        assert manual["status"] == "succeeded"
        assert manual["retry_trigger"] == "manual"
        assert manual["attempts"] == 3
        assert "repair_context" not in generator.calls[2]["payload"]
        assert len(generator.calls) == 3
        ready_report = client.get(
            f"/api/v1/interviews/{interview['id']}/report"
        ).json()["data"]
        assert ready_report["improvements_status"] == "ready"
        assert ready_report["active_operation_id"] is None


def test_failed_resume_draft_preserves_recovery_key(tmp_path):
    """简历草稿 generation_failed 时同样保留失败链尾恢复键（api.md §6）。"""
    generator = ScriptedContentGenerator("invalid", max_total_attempts=1)
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, _report = _complete_after_one_answer(client)
        profile = client.get(f"/api/v1/profiles/{interview['profile_id']}").json()[
            "data"
        ]
        accepted = client.post(
            f"/api/v1/profiles/{interview['profile_id']}/resume-drafts",
            json={
                "expected_revision": profile["revision"],
                "profile_snapshot_id": interview["profile_snapshot_id"],
                "interview_id": interview["id"],
            },
            headers={"Idempotency-Key": "recover-resume-0001"},
        ).json()["data"]
        draft = client.get(f"/api/v1/resume-drafts/{accepted['resource_id']}").json()[
            "data"
        ]
        assert draft["status"] == "generation_failed"
        assert draft["active_operation_id"] == accepted["operation_id"]
        # 恢复键可 GET 且确为失败操作，前端据此显式重试。
        op = client.get(f"/api/v1/operations/{draft['active_operation_id']}").json()[
            "data"
        ]
        assert op["status"] == "failed"


def test_content_retry_budget_is_shared_across_parent_operations(tmp_path):
    generator = ScriptedContentGenerator(
        "invalid", "invalid", "invalid", max_total_attempts=3
    )
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted = client.post(
            f"/api/v1/interviews/{interview['id']}/report/improvements",
            json={"expected_revision": report["revision"]},
            headers={"Idempotency-Key": "content-budget-start"},
        ).json()["data"]
        operation_id = accepted["operation_id"]

        for attempt in range(1, 4):
            operation = client.get(f"/api/v1/operations/{operation_id}").json()["data"]
            assert operation["status"] == "failed"
            assert operation["attempts"] == attempt
            assert operation["error"]["retryable"] is (attempt == 2)
            if attempt == 3:
                break
            if attempt == 1:
                operation_id = operation["next_operation_id"]
                assert operation_id is not None
                assert len(generator.calls) == 2
                continue
            report = client.get(f"/api/v1/interviews/{interview['id']}/report").json()[
                "data"
            ]
            retried = client.post(
                f"/api/v1/operations/{operation_id}/retry",
                json={"expected_revision": report["revision"]},
                headers={"Idempotency-Key": f"content-budget-retry-{attempt}"},
            ).json()["data"]
            replay = client.post(
                f"/api/v1/operations/{operation_id}/retry",
                json={"expected_revision": report["revision"]},
                headers={"Idempotency-Key": f"content-budget-retry-{attempt}"},
            )
            assert replay.status_code == 202
            assert replay.json()["data"]["operation_id"] == retried["operation_id"]
            latest = client.get(f"/api/v1/interviews/{interview['id']}/report").json()[
                "data"
            ]
            sibling = client.post(
                f"/api/v1/operations/{operation_id}/retry",
                json={"expected_revision": latest["revision"]},
                headers={"Idempotency-Key": f"content-budget-sibling-{attempt}"},
            )
            assert sibling.status_code == 409
            assert len(generator.calls) == attempt + 1
            operation_id = retried["operation_id"]

        report = client.get(f"/api/v1/interviews/{interview['id']}/report").json()[
            "data"
        ]
        exhausted = client.post(
            f"/api/v1/operations/{operation_id}/retry",
            json={"expected_revision": report["revision"]},
            headers={"Idempotency-Key": "content-budget-exhausted"},
        )
        assert exhausted.status_code == 409
        assert exhausted.json()["error"]["code"] == "INVALID_STATE"
        assert len(generator.calls) == 3


@pytest.mark.parametrize("kind", ["coaching", "resume"])
def test_restart_recovers_content_after_failed_bookkeeping(tmp_path, monkeypatch, kind):
    config = _config(tmp_path)
    app = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=ScriptedContentGenerator("invalid"),
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)

        def bookkeeping_write_failed(operation, exc, error):
            raise RuntimeError("synthetic failure-admission write failure")

        monkeypatch.setattr(
            app.state.services.content, "_finish_failed", bookkeeping_write_failed
        )
        if kind == "coaching":
            accepted = client.post(
                f"/api/v1/interviews/{interview['id']}/report/improvements",
                json={"expected_revision": report["revision"]},
                headers={"Idempotency-Key": "cleanup-failure-coaching"},
            ).json()["data"]
            resource_url = f"/api/v1/interviews/{interview['id']}/report"
            status_field, failed_status = "improvements_status", "failed"
        else:
            profile = client.get(f"/api/v1/profiles/{interview['profile_id']}").json()[
                "data"
            ]
            accepted = client.post(
                f"/api/v1/profiles/{interview['profile_id']}/resume-drafts",
                json={
                    "expected_revision": profile["revision"],
                    "profile_snapshot_id": interview["profile_snapshot_id"],
                    "interview_id": interview["id"],
                },
                headers={"Idempotency-Key": "cleanup-failure-resume"},
            ).json()["data"]
            resource_url = f"/api/v1/resume-drafts/{accepted['resource_id']}"
            status_field, failed_status = "status", "generation_failed"
        assert (
            app.state.services.operations.get(accepted["operation_id"]).status
            == "failed"
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert original["error"]["code"] == "UPSTREAM_FAILED"
        assert original["next_operation_id"] is None
        stuck = client.get(resource_url).json()["data"]
        assert stuck[status_field] == "generating"

    generator = ScriptedContentGenerator("valid")
    restarted = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(restarted) as client:
        recovered = client.get(resource_url).json()["data"]
        assert recovered[status_field] == failed_status
        assert recovered["active_operation_id"] == accepted["operation_id"]
        assert recovered["revision"] == stuck["revision"] + 1
        restarted.state.services.content.recover_interrupted_operations([])
        assert client.get(resource_url).json()["data"] == recovered
        retried = client.post(
            f"/api/v1/operations/{accepted['operation_id']}/retry",
            json={"expected_revision": recovered["revision"]},
            headers={"Idempotency-Key": "cleanup-failure-recovered-retry"},
        )
        assert retried.status_code == 202
        operation = restarted.state.services.operations.get(
            retried.json()["data"]["operation_id"]
        )
        assert operation.status == "succeeded", operation.error
        assert len(generator.calls) == 1


def _accept_content(client, interview, report, kind, *, key="automatic-content-start"):
    if kind == "coaching":
        path = f"/api/v1/interviews/{interview['id']}/report/improvements"
        payload = {"expected_revision": report["revision"]}
        resource_url = f"/api/v1/interviews/{interview['id']}/report"
        field = "improvements_status"
    else:
        profile = client.get(f"/api/v1/profiles/{interview['profile_id']}").json()[
            "data"
        ]
        path = f"/api/v1/profiles/{interview['profile_id']}/resume-drafts"
        payload = {
            "expected_revision": profile["revision"],
            "profile_snapshot_id": interview["profile_snapshot_id"],
            "interview_id": interview["id"],
        }
        resource_url = None
        field = "status"
    response = client.post(path, json=payload, headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.json()
    accepted = response.json()["data"]
    return (
        accepted,
        resource_url or f"/api/v1/resume-drafts/{accepted['resource_id']}",
        field,
        path,
        payload,
    )


@pytest.mark.parametrize("kind", ["coaching", "resume"])
@pytest.mark.parametrize("mode", ["invalid", "transient"])
@pytest.mark.parametrize("limit", [1, 2])
def test_configured_content_budget_caps_automatic_and_manual(
    tmp_path, kind, mode, limit
):
    generator = ScriptedContentGenerator(mode, mode, max_total_attempts=limit)
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted, resource_url, field, path, payload = _accept_content(
            client, interview, report, kind
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert original["status"] == "failed"
        assert original["retry_trigger"] is None
        child_id = original["next_operation_id"]
        assert (child_id is not None) is (limit == 2)
        tail = (
            client.get(f"/api/v1/operations/{child_id}").json()["data"]
            if child_id is not None
            else original
        )
        assert tail["status"] == "failed"
        assert tail["attempts"] == limit
        assert tail["next_operation_id"] is None
        assert tail["error"]["retryable"] is False
        resource = client.get(resource_url).json()["data"]
        assert resource[field] in {"failed", "generation_failed"}
        assert resource["active_operation_id"] == tail["id"]
        denied = client.post(
            f"/api/v1/operations/{tail['id']}/retry",
            json={"expected_revision": resource["revision"]},
            headers={"Idempotency-Key": "automatic-budget-exhausted"},
        )
        assert denied.status_code == 409
        replay = client.post(
            path, json=payload, headers={"Idempotency-Key": "automatic-content-start"}
        )
        assert replay.status_code == 202
        assert replay.json()["data"]["operation_id"] == accepted["operation_id"]
        repeated = client.post(
            path, json=payload, headers={"Idempotency-Key": "automatic-content-new-key"}
        )
        assert repeated.status_code == (409 if kind == "coaching" else 202)
        assert len(generator.calls) == limit
        with Session(app.state.services.engine) as session:
            assert (
                session.scalar(
                    select(func.count(Operation.id)).where(
                        Operation.resource_id == accepted["resource_id"]
                    )
                )
                == limit
            )


@pytest.mark.parametrize("kind", ["coaching", "resume"])
def test_transient_content_failure_automatically_retries_once(tmp_path, kind):
    generator = ScriptedContentGenerator("transient", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted, resource_url, field, _path, _payload = _accept_content(
            client, interview, report, kind
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        child_id = original["next_operation_id"]
        assert original["status"] == "failed"
        child = client.get(f"/api/v1/operations/{child_id}").json()["data"]
        assert child["status"] == "succeeded"
        assert child["attempts"] == 2
        assert child["retry_reason"] == "transient"
        assert child["chain_started_at"] == original["created_at"]
        assert child["attempt_limit"] == 3
        assert child["retry_trigger"] == "automatic"
        event = app.state.services.operations.events_after(child_id, 0)[0]
        assert event.payload["reason"] == "transient"
        assert "repair_context" not in generator.calls[1]["payload"]
        resource = client.get(resource_url).json()["data"]
        assert resource[field] in {"ready", "draft"}
        assert resource["active_operation_id"] is None
        assert len(generator.calls) == 2


@pytest.mark.parametrize("kind", ["coaching", "resume"])
def test_permanent_model_failure_is_not_retryable(tmp_path, kind):
    generator = ScriptedContentGenerator("permanent", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted, resource_url, _field, _path, _payload = _accept_content(
            client, interview, report, kind
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert original["status"] == "failed"
        assert original["error"]["code"] == "UPSTREAM_FAILED"
        assert original["error"]["retryable"] is False
        assert original["next_operation_id"] is None
        resource = client.get(resource_url).json()["data"]
        assert (
            client.post(
                f"/api/v1/operations/{original['id']}/retry",
                json={"expected_revision": resource["revision"]},
                headers={"Idempotency-Key": "permanent-model-manual-denied"},
            ).status_code
            == 409
        )
        assert len(generator.calls) == 1


def test_missing_confirmed_facts_never_calls_or_repairs_model(tmp_path):
    generator = ScriptedContentGenerator("valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        with Session(app.state.services.engine) as session, session.begin():
            snapshot = session.get(ProfileSnapshot, interview["profile_snapshot_id"])
            snapshot.confirmed_claim_ids = []
        accepted, resource_url, _field, _path, _payload = _accept_content(
            client, interview, report, "coaching"
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert original["status"] == "failed"
        assert original["error"]["code"] == "INVALID_STATE"
        assert original["error"]["retryable"] is False
        assert original["next_operation_id"] is None
        assert generator.calls == []
        resource = client.get(resource_url).json()["data"]
        assert resource["improved_answers"] == []
        assert resource["overall_score"] == report["overall_score"]


@pytest.mark.parametrize("kind", ["coaching", "resume"])
def test_restart_interrupts_accepted_automatic_job_without_replaying_context(
    tmp_path, monkeypatch, kind
):
    config = _config(tmp_path)
    generator = ScriptedContentGenerator("invalid")
    app = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        execute = app.state.services.runner._execute

        async def stop_before_automatic(job):
            operation = app.state.services.operations.get(job.operation_id)
            if operation.parent_operation_id is not None:
                return None
            return await execute(job)

        monkeypatch.setattr(
            app.state.services.runner, "_execute", stop_before_automatic
        )
        accepted, resource_url, field, _path, _payload = _accept_content(
            client, interview, report, kind
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        child_id = original["next_operation_id"]
        child = client.get(f"/api/v1/operations/{child_id}").json()["data"]
        assert child["status"] == "queued"
        assert child["retry_trigger"] == "automatic"
        assert len(generator.calls) == 1
        resource = client.get(resource_url).json()["data"]
        assert resource[field] == "generating"
        assert resource["active_operation_id"] == child_id

    restarted_generator = ScriptedContentGenerator("valid")
    restarted = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=restarted_generator,
    )
    with TestClient(restarted) as client:
        child = client.get(f"/api/v1/operations/{child_id}").json()["data"]
        assert child["status"] == "interrupted"
        assert child["error"]["code"] == "PROCESS_RESTARTED"
        assert child["retry_trigger"] == "automatic"
        assert child["retry_reason"] == "correction"
        assert child["attempts"] == 1
        assert child["attempt_limit"] == 3
        assert child["chain_started_at"] == original["created_at"]
        assert child["next_operation_id"] is None
        assert restarted_generator.calls == []
        resource = client.get(resource_url).json()["data"]
        assert resource[field] in {"failed", "generation_failed"}
        assert resource["active_operation_id"] == child_id
        manual = client.post(
            f"/api/v1/operations/{child_id}/retry",
            json={"expected_revision": resource["revision"]},
            headers={"Idempotency-Key": "restart-automatic-manual-recovery"},
        )
        assert manual.status_code == 202
        operation = client.get(
            f"/api/v1/operations/{manual.json()['data']['operation_id']}"
        ).json()["data"]
        assert operation["status"] == "succeeded"
        assert operation["retry_trigger"] == "manual"
        assert operation["retry_reason"] is None
        assert operation["chain_started_at"] == original["created_at"]
        assert operation["attempts"] == 2
        assert operation["attempt_limit"] == 3
        assert len(restarted_generator.calls) == 1
        assert "repair_context" not in restarted_generator.calls[0]["payload"]


def test_content_retry_admission_is_atomic_and_concurrent_requests_do_not_fork(
    tmp_path,
):
    entered = [Event(), Event()]
    release = [Event(), Event()]

    class GatedGenerator(ScriptedContentGenerator):
        async def generate(self, *, task, payload):
            index = len(self.calls)
            if index < 2:
                entered[index].set()
                assert await asyncio.to_thread(release[index].wait, 10)
            return await super().generate(task=task, payload=payload)

    generator = GatedGenerator("transient", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        interview, report = _complete_after_one_answer(client)
        path = f"/api/v1/interviews/{interview['id']}/report/improvements"
        resource_url = f"/api/v1/interviews/{interview['id']}/report"
        payload = {"expected_revision": report["revision"]}
        headers = {"Idempotency-Key": "concurrent-automatic-original"}
        future = pool.submit(client.post, path, json=payload, headers=headers)
        try:
            assert entered[0].wait(10)
            generating = client.get(resource_url).json()["data"]
            parent_id = generating["active_operation_id"]
            replay = client.post(path, json=payload, headers=headers)
            assert replay.status_code == 202
            assert replay.json()["data"]["operation_id"] == parent_id
            denied = client.post(
                f"/api/v1/operations/{parent_id}/retry",
                json={"expected_revision": generating["revision"]},
                headers={"Idempotency-Key": "concurrent-manual-before-failure"},
            )
            assert denied.status_code == 409
            release[0].set()
            assert entered[1].wait(10)
            parent = client.get(f"/api/v1/operations/{parent_id}").json()["data"]
            child_id = parent["next_operation_id"]
            assert parent["status"] == "failed"
            assert child_id is not None
            generating = client.get(resource_url).json()["data"]
            assert generating["improvements_status"] == "generating"
            assert generating["active_operation_id"] == child_id
            assert app.state.services.runner.pending == 1
            replay = client.post(
                path,
                json=payload,
                headers={"Idempotency-Key": "concurrent-automatic-new-key"},
            )
            assert replay.status_code == 202
            assert replay.json()["data"]["operation_id"] == child_id
            denied = client.post(
                f"/api/v1/operations/{parent_id}/retry",
                json={"expected_revision": generating["revision"]},
                headers={"Idempotency-Key": "concurrent-manual-after-failure"},
            )
            assert denied.status_code == 409
        finally:
            release[0].set()
            release[1].set()
        assert future.result(timeout=10).status_code == 202
        assert len(generator.calls) == 2
        assert app.state.services.runner.pending == 0
        with Session(app.state.services.engine) as session:
            assert (
                session.scalar(
                    select(func.count(Operation.id)).where(
                        Operation.resource_id == report["id"]
                    )
                )
                == 2
            )


@pytest.mark.parametrize("failure_count", [1, 2])
def test_resume_correction_and_final_manual_retry_share_one_draft(
    tmp_path, failure_count
):
    generator = ScriptedContentGenerator(*(["invalid"] * failure_count), "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted, resource_url, _field, _path, _payload = _accept_content(
            client, interview, report, "resume"
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        automatic_id = original["next_operation_id"]
        assert automatic_id is not None
        automatic = client.get(f"/api/v1/operations/{automatic_id}").json()["data"]
        assert automatic["attempts"] == 2
        assert (
            generator.calls[1]["payload"]["repair_context"]["previous_output"]
            == "not-json"
        )
        if failure_count == 2:
            assert automatic["status"] == "failed"
            assert automatic["next_operation_id"] is None
            failed = client.get(resource_url).json()["data"]
            assert failed["sections"] == []
            assert failed["active_operation_id"] == automatic_id
            manual = client.post(
                f"/api/v1/operations/{automatic_id}/retry",
                json={"expected_revision": failed["revision"]},
                headers={"Idempotency-Key": "resume-final-manual-attempt"},
            )
            assert manual.status_code == 202
            final = client.get(
                f"/api/v1/operations/{manual.json()['data']['operation_id']}"
            ).json()["data"]
            assert final["status"] == "succeeded"
            assert final["attempts"] == 3
            assert final["retry_trigger"] == "manual"
            assert "repair_context" not in generator.calls[2]["payload"]
        else:
            assert automatic["status"] == "succeeded"
        ready = client.get(resource_url).json()["data"]
        assert ready["id"] == accepted["resource_id"]
        assert ready["status"] == "draft"
        assert ready["active_operation_id"] is None
        assert ready["sections"][0]["items"][0]["claim_ids"]
        assert len(generator.calls) == failure_count + 1
        with Session(app.state.services.engine) as session:
            assert session.scalar(select(func.count(ResumeDraft.id))) == 1


def test_concurrent_manual_retries_after_automatic_failure_share_final_slot(tmp_path):
    generator = ScriptedContentGenerator("invalid", "invalid", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted, resource_url, _field, _path, _payload = _accept_content(
            client, interview, report, "coaching"
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        tail_id = original["next_operation_id"]
        failed = client.get(resource_url).json()["data"]
        revision = {"expected_revision": failed["revision"]}

        def retry(index):
            key = f"race-final-manual-slot-{index}"
            response = client.post(
                f"/api/v1/operations/{tail_id}/retry",
                json=revision,
                headers={"Idempotency-Key": key},
            )
            return key, response

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(retry, range(2)))
        assert sorted(response.status_code for _key, response in responses) == [
            202,
            409,
        ]
        key, winner = next(item for item in responses if item[1].status_code == 202)
        replay = client.post(
            f"/api/v1/operations/{tail_id}/retry",
            json=revision,
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 202
        assert (
            replay.json()["data"]["operation_id"]
            == winner.json()["data"]["operation_id"]
        )
        assert len(generator.calls) == 3
        with Session(app.state.services.engine) as session:
            assert (
                session.scalar(
                    select(func.count(Operation.id)).where(
                        Operation.resource_id == accepted["resource_id"]
                    )
                )
                == 3
            )


@pytest.mark.parametrize("failure_count", [1, 2])
def test_resume_command_replays_original_receipt_before_and_after_successors(
    tmp_path, monkeypatch, failure_count
):
    generator = ScriptedContentGenerator(*(["invalid"] * failure_count), "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        services = app.state.services
        execute = services.runner._execute
        held = []

        async def hold_content(job):
            if job.kind == "resume.compose":
                held.append(job)
                return None
            return await execute(job)

        monkeypatch.setattr(services.runner, "_execute", hold_content)
        accepted, resource_url, _, path, payload = _accept_content(
            client, interview, report, "resume", key="original-resume-receipt"
        )

        def assert_replay():
            calls = len(generator.calls)
            replay = client.post(
                path,
                json=payload,
                headers={"Idempotency-Key": "original-resume-receipt"},
            )
            assert replay.status_code == 202, replay.json()
            receipt = replay.json()["data"]
            assert receipt["operation_id"] == accepted["operation_id"]
            assert receipt["resource_id"] == accepted["resource_id"]
            assert receipt["events_url"] == accepted["events_url"]
            assert len(generator.calls) == calls
            for changed in (
                {"expected_revision": 999},
                {"profile_snapshot_id": "snapshot_missing"},
                {"interview_id": "interview_missing"},
                {"interview_id": None, "jd_text": "不相同的目标岗位"},
            ):
                mismatch = client.post(
                    path,
                    json={**payload, **changed},
                    headers={"Idempotency-Key": "original-resume-receipt"},
                )
                assert mismatch.status_code == 409, mismatch.json()
                assert mismatch.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
            assert len(generator.calls) == calls

        assert_replay()
        assert len(held) == 1
        automatic_job = asyncio.run(execute(held[0]))
        assert automatic_job is not None
        assert_replay()
        asyncio.run(execute(automatic_job))
        assert_replay()
        if failure_count == 2:
            resource = client.get(resource_url).json()["data"]
            retry = client.post(
                f"/api/v1/operations/{automatic_job.operation_id}/retry",
                json={"expected_revision": resource["revision"]},
                headers={"Idempotency-Key": "receipt-manual-successor"},
            )
            assert retry.status_code == 202
            assert_replay()
            asyncio.run(execute(held[-1]))
            assert_replay()
        assert client.get(resource_url).json()["data"]["status"] == "draft"

        def unavailable_target(*args, **kwargs):
            raise AssertionError("Receipt replay must not resolve a target")

        monkeypatch.setattr(services.content, "_resolve_target", unavailable_target)
        monkeypatch.setattr(services.runner, "_pending", services.runner._max_queued)
        assert_replay()
        assert len(generator.calls) == failure_count + 1
        with Session(services.engine) as session:
            assert session.scalar(select(func.count(ResumeDraft.id))) == 1


@pytest.mark.parametrize("kind", ["coaching", "resume"])
@pytest.mark.parametrize("limit", [1, 2, 3])
@pytest.mark.parametrize("exhausted", [False, True])
def test_restart_retry_projection_and_admission_share_current_budget(
    tmp_path, monkeypatch, kind, limit, exhausted
):
    config = _config(tmp_path)
    generator = ScriptedContentGenerator(
        "transient", "transient", max_total_attempts=limit
    )
    app = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        services = app.state.services
        execute = services.runner._execute
        held = []

        async def hold_content(job):
            if job.kind in {"report.coach", "resume.compose"}:
                held.append(job)
                return None
            return await execute(job)

        monkeypatch.setattr(services.runner, "_execute", hold_content)
        accepted, resource_url, field, path, payload = _accept_content(
            client, interview, report, kind, key="restart-budget-original"
        )
        job = held[0]
        begun = limit if exhausted else limit - 1
        for index in range(max(0, begun - 1)):
            successor = asyncio.run(execute(job))
            if successor is None:
                resource = client.get(resource_url).json()["data"]
                response = client.post(
                    f"/api/v1/operations/{job.operation_id}/retry",
                    json={"expected_revision": resource["revision"]},
                    headers={"Idempotency-Key": f"restart-budget-manual-{index}"},
                )
                assert response.status_code == 202, response.json()
                job = held[-1]
            else:
                job = successor
        if begun:
            assert services.operations.start(job.operation_id)
        operation_id = job.operation_id
        before = services.operations.get(operation_id)
        assert before.attempts == begun

    recovery_generator = ScriptedContentGenerator("valid", max_total_attempts=limit)
    restarted = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=recovery_generator,
    )
    with TestClient(restarted) as client:
        services = restarted.state.services
        operation = client.get(f"/api/v1/operations/{operation_id}").json()["data"]
        assert operation["status"] == "interrupted"
        assert operation["attempts"] == begun
        assert operation["attempt_limit"] == limit
        assert (
            operation["chain_started_at"]
            == services.operations.get(accepted["operation_id"]).created_at
        )
        assert operation["error"]["retryable"] is not exhausted
        raw = services.operations.get(operation_id)
        assert raw.error["code"] == "PROCESS_RESTARTED"
        assert raw.error["retryable"] is True
        assert recovery_generator.calls == []
        resource = client.get(resource_url).json()["data"]
        assert resource[field] in {"failed", "generation_failed"}
        if operation_id != accepted["operation_id"]:
            parent = client.get(
                f"/api/v1/operations/{accepted['operation_id']}"
            ).json()["data"]
            assert parent["error"]["retryable"] is False
        receipt_replay = client.post(
            path,
            json=payload,
            headers={"Idempotency-Key": "restart-budget-original"},
        )
        assert receipt_replay.status_code == 202
        assert receipt_replay.json()["data"]["operation_id"] == accepted["operation_id"]
        response = client.post(
            f"/api/v1/operations/{operation_id}/retry",
            json={"expected_revision": resource["revision"]},
            headers={"Idempotency-Key": "restart-budget-recovery"},
        )
        assert response.status_code == (409 if exhausted else 202), response.json()
        assert len(recovery_generator.calls) == (0 if exhausted else 1)
        assert services.operations.get(operation_id).error == raw.error
        if not exhausted:
            tail = client.get(
                f"/api/v1/operations/{response.json()['data']['operation_id']}"
            ).json()["data"]
            assert tail["status"] == "succeeded", tail["error"]
            assert tail["attempts"] == begun + 1
            assert tail["retry_reason"] is None
            assert tail["attempt_limit"] == limit


@pytest.mark.parametrize("kind", ["coaching", "resume"])
@pytest.mark.parametrize("mode", ["invalid", "transient", "permanent"])
def test_current_content_policy_preserves_original_cause_when_budget_is_raised(
    tmp_path, kind, mode
):
    config = _config(tmp_path)
    initial = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=ScriptedContentGenerator(mode, max_total_attempts=1),
    )
    with TestClient(initial) as client:
        interview, report = _complete_after_one_answer(client)
        accepted, resource_url, _, _, _ = _accept_content(
            client, interview, report, kind
        )
        original = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert original["error"]["retryable"] is False
        raw = initial.state.services.operations.get(accepted["operation_id"])
        failure_events = [
            event.payload
            for event in initial.state.services.operations.events_after(raw.id, 0)
            if event.event_type == "operation.failed"
        ]
        assert failure_events == [raw.error]
        assert raw.error["retryable"] is (mode != "permanent")

    generator = ScriptedContentGenerator("valid", max_total_attempts=3)
    restarted = create_app(
        config,
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(restarted) as client:
        services = restarted.state.services
        current = client.get(f"/api/v1/operations/{raw.id}").json()["data"]
        assert current["error"]["retryable"] is (mode != "permanent")
        assert current["attempt_limit"] == 3
        resource = client.get(resource_url).json()["data"]
        if mode != "permanent":
            services.runner._pending = services.runner._max_queued
            assert (
                client.get(f"/api/v1/operations/{raw.id}").json()["data"]["error"][
                    "retryable"
                ]
                is True
            )
            busy = client.post(
                f"/api/v1/operations/{raw.id}/retry",
                json={"expected_revision": resource["revision"]},
                headers={"Idempotency-Key": "raised-budget-capacity"},
            )
            assert busy.status_code == 429
            services.runner._pending = 0
            assert generator.calls == []
        retried = client.post(
            f"/api/v1/operations/{raw.id}/retry",
            json={"expected_revision": resource["revision"]},
            headers={"Idempotency-Key": "raised-budget-manual"},
        )
        assert retried.status_code == (409 if mode == "permanent" else 202)
        assert len(generator.calls) == (0 if mode == "permanent" else 1)
        assert services.operations.get(raw.id).error == raw.error
        assert [
            event.payload
            for event in services.operations.events_after(raw.id, 0)
            if event.event_type == "operation.failed"
        ] == failure_events


@pytest.mark.parametrize("kind", ["coaching", "resume"])
@pytest.mark.parametrize("changed", ["active_owner", "generation_owner", "status"])
def test_content_retry_projection_rejects_stale_resource_ownership(
    tmp_path, kind, changed
):
    generator = ScriptedContentGenerator("invalid", "invalid", "valid")
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
        generator=generator,
    )
    with TestClient(app) as client:
        interview, report = _complete_after_one_answer(client)
        accepted, resource_url, _, _, _ = _accept_content(
            client, interview, report, kind
        )
        services = app.state.services
        original = services.operations.get(accepted["operation_id"])
        tail_id = services.operations.retry_metadata(original)["next_operation_id"]
        before = client.get(f"/api/v1/operations/{tail_id}").json()["data"]
        assert before["error"]["retryable"] is True
        with Session(services.engine) as session, session.begin():
            model = Report if kind == "coaching" else ResumeDraft
            resource = session.get(model, accepted["resource_id"])
            if changed == "active_owner":
                resource.active_operation_id = original.id
            elif changed == "generation_owner":
                resource.active_operation_id = None
                if kind == "coaching":
                    resource.improvements_operation_id = original.id
                else:
                    resource.generation_operation_id = original.id
            elif kind == "coaching":
                resource.improvements_status = "ready"
            else:
                resource.status = "draft"
        resource = client.get(resource_url).json()["data"]
        current = client.get(f"/api/v1/operations/{tail_id}").json()["data"]
        assert current["error"]["retryable"] is False
        denied = client.post(
            f"/api/v1/operations/{tail_id}/retry",
            json={"expected_revision": resource["revision"]},
            headers={"Idempotency-Key": f"stale-content-{changed}"},
        )
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "INVALID_STATE"
        assert client.get(resource_url).json()["data"] == resource
        assert len(generator.calls) == 2
        assert services.operations.get(tail_id).error["retryable"] is True
