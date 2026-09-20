"""M4-02 grounded coaching/resume operations over persisted interview evidence."""

from __future__ import annotations

import json
from collections import deque

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_interview_runtime import (
    InMemoryKnowledge,
    ScriptedAnalyzer,
    _config,
    _prepare_active_interview,
)

from zhijue.adapters.db.models import Report, ResumeDraft
from zhijue.api.app import create_app
from zhijue.application.answer_workflow import AnalysisResult


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
        if task == "coach_answers":
            items = []
            for root_id, root_answers in payload["answers_by_root"].items():
                answer_id, answer_text = next(iter(root_answers.items()))
                items.append(
                    {
                        "root_question_id": root_id,
                        "rewritten_answer": answer_text,
                        "segments": [
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
                        ],
                        "used_claim_ids": [],
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


def test_failed_coaching_retries_same_report_and_preserves_original(tmp_path):
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
        failed_report = client.get(
            f"/api/v1/interviews/{interview['id']}/report"
        ).json()["data"]
        assert failed_report["improvements_status"] == "failed"
        assert failed_report["improved_answers"] == []
        assert failed_report["overall_score"] == report_before["overall_score"]

        retried = client.post(
            f"/api/v1/operations/{accepted['operation_id']}/retry",
            json={"expected_revision": failed_report["revision"]},
            headers={"Idempotency-Key": "content-retry-key-0001"},
        ).json()["data"]
        retry_operation = client.get(
            f"/api/v1/operations/{retried['operation_id']}"
        ).json()["data"]
        assert retry_operation["status"] == "succeeded", retry_operation["error"]
        assert retry_operation["parent_operation_id"] == accepted["operation_id"]
        ready_report = client.get(
            f"/api/v1/interviews/{interview['id']}/report"
        ).json()["data"]
        assert ready_report["id"] == report_before["id"]
        assert ready_report["improvements_status"] == "ready"
        assert len(generator.calls) == 2


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
            assert operation["error"]["retryable"] is (attempt < 3)
            if attempt == 3:
                break
            report = client.get(f"/api/v1/interviews/{interview['id']}/report").json()[
                "data"
            ]
            retried = client.post(
                f"/api/v1/operations/{operation_id}/retry",
                json={"expected_revision": report["revision"]},
                headers={"Idempotency-Key": f"content-budget-retry-{attempt}"},
            ).json()["data"]
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
