"""M3 interview runtime: real openJiuwen workflow, durable state, and recovery."""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque

import pytest
from fastapi.testclient import TestClient
from pack_fixtures import TEST_JD, approve_test_pack
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import Answer, Assessment, Interview, Operation, Report
from zhijue.adapters.db.operations import OperationCommand, canon_scope
from zhijue.api.app import AppConfig, create_app
from zhijue.application.answer_workflow import AnalysisResult
from zhijue.application.profiles import ActivationReceipt
from zhijue.domain.errors import InvalidStateError
from zhijue.domain.operations import OperationStatus


class InMemoryKnowledge:
    async def index_snapshot(self, *, profile_id, generation, sources):
        return ActivationReceipt(
            generation=generation,
            source_ids=[source.source_id for source in sources],
            document_ids=[source.source_id for source in sources],
            embedding_logical_calls=len(sources),
        )

    async def search(self, **kwargs):
        return []


class ScriptedAnalyzer:
    """Fixture analyzer; orchestration remains the installed openJiuwen Workflow."""

    def __init__(self, *modes: str, max_total_attempts: int = 3) -> None:
        self._modes = deque(modes or ("adequate",))
        self.calls: list[dict[str, object]] = []
        self.max_total_attempts = max_total_attempts

    async def analyze(self, **inputs) -> AnalysisResult:
        self.calls.append(inputs)
        mode = self._modes.popleft() if self._modes else "adequate"
        if mode == "invalid":
            return AnalysisResult(content="not-json")

        rubric_snapshot = inputs["rubric_snapshot"]
        answer_text = inputs["answer_text"]
        reference_ids = list(rubric_snapshot.get("reference_ids") or ())
        criteria = []
        for index, frozen in enumerate(rubric_snapshot["rubric"]):
            missing = mode == "probe" and index == 0
            technical = frozen["kind"] == "technical"
            criteria.append(
                {
                    "criterion_id": frozen["criterion_id"],
                    "kind": frozen["kind"],
                    "weight": frozen["weight"],
                    "level": 1 if missing else 2,
                    "finding": "missing" if missing else "supported",
                    "answer_quotes": (
                        []
                        if missing
                        else [
                            {
                                "answer_id": inputs["answer_id"],
                                "exact_quote": answer_text,
                            }
                        ]
                    ),
                    "knowledge_refs": (
                        reference_ids if technical and not missing else []
                    ),
                    "explanation": "仅基于本轮回答和冻结评价快照。",
                }
            )
        observation = {
            "schema_version": "1.0.0",
            "id": inputs["observation_id"],
            "answer_id": inputs["answer_id"],
            "question_id": inputs["question_id"],
            "root_question_id": inputs["root_question_id"],
            "relevance": "relevant",
            "knowledge_status": "adequate",
            "criteria": criteria,
            "clarification_needed": False,
            "validation_flags": [],
        }
        return AnalysisResult(
            content=json.dumps(observation, ensure_ascii=False),
            input_tokens=20,
            output_tokens=30,
            total_tokens=50,
            cost=None,
        )


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        run_mode="fixture",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        runtime_dir=tmp_path,
        milvus_uri=tmp_path / "knowledge.db",
    )


def _prepare_active_interview(client: TestClient) -> dict[str, object]:
    approve_test_pack(client.app.state.services.knowledge_packs)
    profile_id = client.post(
        "/api/v1/profiles", json={"display_name": "合成候选人"}
    ).json()["data"]["id"]
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
        headers={"Idempotency-Key": "runtime-confirm-key-0001"},
    ).json()["data"]
    assert (
        client.get(f"/api/v1/operations/{confirm['operation_id']}").json()["data"][
            "status"
        ]
        == "succeeded"
    )
    profile = client.get(f"/api/v1/profiles/{profile_id}").json()["data"]
    planned = client.post(
        "/api/v1/interviews",
        json={
            "profile_id": profile_id,
            "profile_revision": profile["revision"],
            "jd_text": TEST_JD,
        },
        headers={"Idempotency-Key": "runtime-plan-key-000001"},
    ).json()["data"]
    plan_operation = client.get(f"/api/v1/operations/{planned['operation_id']}").json()[
        "data"
    ]
    assert plan_operation["status"] == "succeeded", plan_operation["error"]
    interview_id = planned["resource_id"]
    ready = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"expected_revision": ready["revision"]},
        headers={"Idempotency-Key": "runtime-start-key-00001"},
    ).json()["data"]
    start_operation = client.get(
        f"/api/v1/operations/{started['operation_id']}"
    ).json()["data"]
    assert start_operation["status"] == "succeeded", start_operation["error"]
    replay = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"expected_revision": ready["revision"]},
        headers={"Idempotency-Key": "runtime-start-key-00001"},
    ).json()["data"]
    assert replay["operation_id"] == started["operation_id"]
    active = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    assert active["status"] == "active"
    assert start_operation["result"]["question_count"] == 5
    return active


@pytest.fixture()
def runtime_client(tmp_path):
    analyzer = ScriptedAnalyzer("probe", "adequate")
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        yield client, analyzer


def test_start_and_answers_are_idempotent_and_emit_durable_policy_events(
    runtime_client, capsys, caplog
):
    client, analyzer = runtime_client
    active = _prepare_active_interview(client)
    interview_id = active["id"]
    question_id = active["current_question"]["id"]
    payload = {
        "expected_revision": active["revision"],
        "question_id": question_id,
        "client_turn_id": "turn-runtime-0001",
        "answer_text": "我先记录现象，再逐项核对配置和现场证据。",
    }
    accepted = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        json=payload,
        headers={"Idempotency-Key": "runtime-answer-key-0001"},
    ).json()["data"]
    operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
        "data"
    ]
    assert operation["status"] == "succeeded", operation["error"]
    assert operation["attempt_limit"] == 3
    assert operation["retry_reason"] is None
    assert operation["chain_started_at"] == operation["created_at"]
    assert operation["result"]["action"] == "PROBE"
    assert operation["result"]["usage"] == {
        "input_tokens": 20,
        "output_tokens": 30,
        "total_tokens": 50,
        "cost": None,
    }
    captured_logs = capsys.readouterr()
    assert payload["answer_text"] not in (
        captured_logs.out + captured_logs.err + caplog.text
    )

    replay = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        json=payload,
        headers={"Idempotency-Key": "runtime-answer-key-0001"},
    ).json()["data"]
    assert replay["operation_id"] == accepted["operation_id"]
    same_turn = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        json=payload,
        headers={"Idempotency-Key": "runtime-answer-key-0002"},
    ).json()["data"]
    assert same_turn["operation_id"] == accepted["operation_id"]
    assert len(analyzer.calls) == 1

    changed = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        json={**payload, "answer_text": "更换后的回答"},
        headers={"Idempotency-Key": "runtime-answer-key-0003"},
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
    assert view["current_question"]["kind"] == "probe"
    assert view["root_results"][-1]["action"] == "PROBE"
    assert (
        view["current_question"]["wording"]
        == "请针对刚才未覆盖的关键点补充：说明了目标、做法和基本边界。"
    )
    assert "fallback_expression" not in view["current_question"]["wording"]
    events = client.app.state.services.operations.events_after(
        accepted["operation_id"], 0
    )
    assert [event.event_type for event in events] == [
        "operation.started",
        "policy.decided",
        "question.ready",
        "operation.completed",
    ]

    followup = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        json={
            "expected_revision": view["revision"],
            "question_id": view["current_question"]["id"],
            "client_turn_id": "turn-runtime-0002",
            "answer_text": "我本人完成日志采集和边界条件复核。",
        },
        headers={"Idempotency-Key": "runtime-answer-key-0004"},
    ).json()["data"]
    followup_operation = client.get(
        f"/api/v1/operations/{followup['operation_id']}"
    ).json()["data"]
    assert followup_operation["status"] == "succeeded"
    assert followup_operation["result"]["action"] == "NEXT"
    with Session(client.app.state.services.engine) as session:
        assert session.scalar(select(func.count(Answer.id))) == 2


def test_stale_answer_revision_does_not_create_operation_or_answer(runtime_client):
    client, _ = runtime_client
    active = _prepare_active_interview(client)
    response = client.post(
        f"/api/v1/interviews/{active['id']}/answers",
        json={
            "expected_revision": active["revision"] - 1,
            "question_id": active["current_question"]["id"],
            "client_turn_id": "turn-stale-0001",
            "answer_text": "这是过期页面提交。",
        },
        headers={"Idempotency-Key": "runtime-stale-key-0001"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVISION_CONFLICT"
    with Session(client.app.state.services.engine) as session:
        assert session.scalar(select(func.count(Answer.id))) == 0


def test_concurrent_identical_answer_acceptance_is_one_atomic_write(runtime_client):
    client, _ = runtime_client
    active = _prepare_active_interview(client)
    interview_id = active["id"]
    question_id = active["current_question"]["id"]
    answer_text = "并发副本必须只受理一次。"
    client_turn_id = "turn-concurrent-0001"
    command = OperationCommand(
        kind="interview.answer",
        resource_type="interview",
        resource_id=interview_id,
        scope=canon_scope(
            "local", "POST", f"/api/v1/interviews/{interview_id}/answers"
        ),
        idempotency_key="runtime-concurrent-key-0001",
        input={
            "expected_revision": active["revision"],
            "question_id": question_id,
            "client_turn_id": client_turn_id,
            "answer_text": answer_text,
        },
    )
    start = threading.Barrier(2)
    accepted = []
    errors: list[BaseException] = []

    def submit() -> None:
        try:
            start.wait()
            accepted.append(
                client.app.state.services.interviews.accept_answer(
                    interview_id,
                    expected_revision=active["revision"],
                    question_id=question_id,
                    client_turn_id=client_turn_id,
                    answer_text=answer_text,
                    command=command,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - collected for assertion.
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert sorted(result.created for result in accepted) == [False, True]
    assert len({result.operation.id for result in accepted}) == 1
    assert len({result.answer_id for result in accepted}) == 1
    with Session(client.app.state.services.engine) as session:
        answer_count = session.scalar(select(func.count(Answer.id)))
        operation_count = session.scalar(
            select(func.count(Operation.id)).where(Operation.kind == "interview.answer")
        )
    assert answer_count == 1
    assert operation_count == 1


def test_failed_analysis_preserves_answer_and_retry_reuses_it(tmp_path):
    analyzer = ScriptedAnalyzer("invalid", "adequate")
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        active = _prepare_active_interview(client)
        interview_id = active["id"]
        original = client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            json={
                "expected_revision": active["revision"],
                "question_id": active["current_question"]["id"],
                "client_turn_id": "turn-retry-0001",
                "answer_text": "这份原始回答必须在失败后保留。",
            },
            headers={"Idempotency-Key": "runtime-fail-key-00001"},
        ).json()["data"]
        failed = client.get(f"/api/v1/operations/{original['operation_id']}").json()[
            "data"
        ]
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "UPSTREAM_FAILED"
        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        accepted_answer = view["current_question"]["accepted_answer"]
        assert accepted_answer == {
            "id": accepted_answer["id"],
            "client_turn_id": "turn-retry-0001",
            "raw_text": "这份原始回答必须在失败后保留。",
            "evaluation_status": "failed",
            # 失败链尾即首次受理操作（尚无 retry）：跨刷新恢复键（api.md §6）。
            "retry_operation_id": original["operation_id"],
        }

        # Simulate a failure recorded while a one-attempt deployment policy was
        # active.  After the owner raises the bounded budget, GET and POST must
        # use the current policy so the saved answer is recoverable.
        with Session(client.app.state.services.engine) as session, session.begin():
            failed_operation = session.get(Operation, original["operation_id"])
            failed_operation.error = {**failed_operation.error, "retryable": False}
        refreshed = client.get(f"/api/v1/operations/{original['operation_id']}").json()[
            "data"
        ]
        assert refreshed["error"]["retryable"] is True

        retried = client.post(
            f"/api/v1/operations/{original['operation_id']}/retry",
            json={"expected_revision": view["revision"]},
            headers={"Idempotency-Key": "runtime-retry-key-0001"},
        ).json()["data"]
        retry_operation = client.get(
            f"/api/v1/operations/{retried['operation_id']}"
        ).json()["data"]
        assert retry_operation["status"] == "succeeded", retry_operation["error"]
        assert retry_operation["parent_operation_id"] == original["operation_id"]
        assert (
            retry_operation["result"]["answer_id"]
            == view["current_question"]["accepted_answer"]["id"]
        )
        with Session(client.app.state.services.engine) as session:
            assert session.scalar(select(func.count(Answer.id))) == 1


def test_five_adequate_answers_end_without_inventing_extra_questions(tmp_path):
    analyzer = ScriptedAnalyzer(*(["adequate"] * 5))
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        interview_id = view["id"]
        actions = []
        for turn_index in range(5):
            accepted = client.post(
                f"/api/v1/interviews/{interview_id}/answers",
                json={
                    "expected_revision": view["revision"],
                    "question_id": view["current_question"]["id"],
                    "client_turn_id": f"turn-complete-{turn_index:04d}",
                    "answer_text": "我说明自己的做法、观察证据和不确定边界。",
                },
                headers={"Idempotency-Key": f"runtime-complete-key-{turn_index:04d}"},
            ).json()["data"]
            operation = client.get(
                f"/api/v1/operations/{accepted['operation_id']}"
            ).json()["data"]
            assert operation["status"] == "succeeded", operation["error"]
            actions.append(operation["result"]["action"])
            view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]

        assert actions == ["NEXT", "NEXT", "NEXT", "NEXT", "END"]
        assert view["status"] == "completed"
        assert view["current_question"] is None
        assert view["report_id"] is not None
        assert len(view["root_results"]) == 5
        assert len(analyzer.calls) == 5

        report_response = client.get(f"/api/v1/interviews/{interview_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()["data"]
        assert set(report) == {
            "id",
            "revision",
            "interview_id",
            "completion",
            "overall_score",
            "coverage",
            "root_assessments",
            "improvements_status",
            "active_operation_id",
            "improved_answers",
            "source_claims",
            "limitations",
            "run_metadata",
            "knowledge_pack",
        }
        assert report["source_claims"] == []
        assert report["completion"] == "complete"
        assert report["overall_score"] == 67
        assert report["coverage"] == {
            "planned_root_count": 5,
            "asked_root_count": 5,
            "answered_root_count": 5,
            "scored_root_count": 5,
            "insufficient_root_count": 0,
            "disputed_root_count": 0,
            "skipped_root_count": 0,
            "unmeasured_root_count": 0,
            "skipped_question_count": 0,
            "overall_eligible": True,
        }
        assert len(report["root_assessments"]) == 5
        assert report["improved_answers"] == []
        assert report["run_metadata"]["scoring_version"] == "1.0.0"
        with Session(client.app.state.services.engine) as session:
            assert session.scalar(select(func.count(Assessment.id))) == 5
            assert session.scalar(select(func.count(Report.id))) == 1


def test_report_is_not_readable_before_finish(tmp_path):
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer(),
    )
    with TestClient(app) as client:
        active = _prepare_active_interview(client)
        response = client.get(f"/api/v1/interviews/{active['id']}/report")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPORT_NOT_READY"


def test_explicit_end_is_idempotent_and_keeps_unmeasured_roots_null(tmp_path):
    analyzer = ScriptedAnalyzer("adequate")
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        interview_id = view["id"]
        answer = client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            json={
                "expected_revision": view["revision"],
                "question_id": view["current_question"]["id"],
                "client_turn_id": "turn-end-0001",
                "answer_text": "我说明一项可核对的处理过程。",
            },
            headers={"Idempotency-Key": "runtime-end-answer-0001"},
        ).json()["data"]
        assert (
            client.get(f"/api/v1/operations/{answer['operation_id']}").json()["data"][
                "status"
            ]
            == "succeeded"
        )
        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        revision_before_end = view["revision"]

        accepted = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": revision_before_end, "action": "end"},
            headers={"Idempotency-Key": "runtime-end-control-0001"},
        ).json()["data"]
        operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert operation["status"] == "succeeded"
        assert operation["result"]["action"] == "END"
        replay = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": revision_before_end, "action": "end"},
            headers={"Idempotency-Key": "runtime-end-control-0002"},
        ).json()["data"]
        assert replay["operation_id"] == accepted["operation_id"]

        completed = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
        report_again = client.get(f"/api/v1/interviews/{interview_id}/report").json()[
            "data"
        ]

        assert completed["status"] == "completed"
        assert completed["current_question"] is None
        assert completed["stop_requested"] is True
        assert report_again == report
        assert report["completion"] == "incomplete"
        assert report["overall_score"] is None
        assert report["coverage"]["asked_root_count"] == 2
        assert report["coverage"]["answered_root_count"] == 1
        assert report["coverage"]["scored_root_count"] == 1
        assert report["coverage"]["unmeasured_root_count"] == 4
        assert all(
            item["score"] is None
            for item in report["root_assessments"]
            if item["status"] == "unmeasured"
        )
        assert len(analyzer.calls) == 1
        events = client.app.state.services.operations.events_after(
            accepted["operation_id"], 0
        )
        assert [event.event_type for event in events] == [
            "operation.started",
            "policy.decided",
            "report.ready",
            "operation.completed",
        ]
        with Session(client.app.state.services.engine) as session:
            assert session.scalar(select(func.count(Report.id))) == 1


def test_skipping_followup_keeps_main_observation_but_marks_session_incomplete(
    tmp_path,
):
    analyzer = ScriptedAnalyzer("probe")
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        interview_id = view["id"]
        root_id = view["current_question"]["root_id"]
        answer = client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            json={
                "expected_revision": view["revision"],
                "question_id": view["current_question"]["id"],
                "client_turn_id": "turn-skip-probe-0001",
                "answer_text": "我先给出当前能确认的部分。",
            },
            headers={"Idempotency-Key": "runtime-skip-answer-0001"},
        ).json()["data"]
        assert (
            client.get(f"/api/v1/operations/{answer['operation_id']}").json()["data"][
                "result"
            ]["action"]
            == "PROBE"
        )
        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        assert view["current_question"]["kind"] == "probe"
        skipped = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": view["revision"], "action": "skip"},
            headers={"Idempotency-Key": "runtime-skip-control-0001"},
        ).json()["data"]
        skip_operation = client.get(
            f"/api/v1/operations/{skipped['operation_id']}"
        ).json()["data"]
        assert skip_operation["result"]["action"] == "NEXT"
        assert len(analyzer.calls) == 1

        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        ended = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": view["revision"], "action": "end"},
            headers={"Idempotency-Key": "runtime-skip-end-0001"},
        ).json()["data"]
        assert (
            client.get(f"/api/v1/operations/{ended['operation_id']}").json()["data"][
                "status"
            ]
            == "succeeded"
        )
        report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
        first_root = next(
            item
            for item in report["root_assessments"]
            if item["root_question_id"] == root_id
        )
        assert first_root["status"] == "scored"
        assert first_root["score"] is not None
        assert report["completion"] == "incomplete"
        assert report["overall_score"] is None
        assert report["coverage"]["skipped_root_count"] == 0
        assert report["coverage"]["skipped_question_count"] == 1


def test_end_accepted_during_answer_waits_then_reports_saved_observation(tmp_path):
    analyzer = ScriptedAnalyzer("adequate")
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        active = _prepare_active_interview(client)
        services = client.app.state.services
        interview_id = active["id"]
        answer_command = OperationCommand(
            kind="interview.answer",
            resource_type="interview",
            resource_id=interview_id,
            scope=canon_scope(
                "local", "POST", f"/api/v1/interviews/{interview_id}/answers"
            ),
            idempotency_key="runtime-concurrent-end-answer",
            input={
                "expected_revision": active["revision"],
                "question_id": active["current_question"]["id"],
                "client_turn_id": "turn-concurrent-end-0001",
                "answer_text": "回答已受理后请求结束。",
            },
        )
        accepted_answer = services.interviews.accept_answer(
            interview_id,
            expected_revision=active["revision"],
            question_id=active["current_question"]["id"],
            client_turn_id="turn-concurrent-end-0001",
            answer_text="回答已受理后请求结束。",
            command=answer_command,
        )
        services.operations.transition(
            accepted_answer.operation.id, OperationStatus.RUNNING
        )
        pending = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        end_command = OperationCommand(
            kind="interview.control.end",
            resource_type="interview",
            resource_id=interview_id,
            scope=canon_scope(
                "local", "POST", f"/api/v1/interviews/{interview_id}/control"
            ),
            idempotency_key="runtime-concurrent-end-control",
            input={"expected_revision": pending["revision"], "action": "end"},
        )
        accepted_end = services.interviews.accept_control(
            interview_id,
            expected_revision=pending["revision"],
            action="end",
            command=end_command,
        )
        stopping = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        assert stopping["status"] == "finishing"
        assert stopping["stop_requested"] is True
        assert stopping["current_question"] is None
        assert stopping["active_operation_id"] == accepted_answer.operation.id

        answer_result = asyncio.run(
            services.interviews.process_answer(
                operation_id=accepted_answer.operation.id
            )
        )
        assert answer_result["action"] == "NEXT"
        assert answer_result["report_id"] is None
        assert (
            client.get(f"/api/v1/interviews/{interview_id}").json()["data"]["report_id"]
            is None
        )
        services.operations.transition(
            accepted_end.operation.id, OperationStatus.RUNNING
        )
        end_result = services.interviews.process_control(
            operation_id=accepted_end.operation.id
        )
        report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]

        assert end_result["report_id"] == report["id"]
        assert report["coverage"]["answered_root_count"] == 1
        assert report["coverage"]["scored_root_count"] == 1
        assert len(analyzer.calls) == 1


def test_skipping_main_root_persists_skipped_null_assessment(tmp_path):
    analyzer = ScriptedAnalyzer()
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        interview_id = view["id"]
        skipped_root_id = view["current_question"]["root_id"]
        accepted = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": view["revision"], "action": "skip"},
            headers={"Idempotency-Key": "runtime-main-skip-0001"},
        ).json()["data"]
        operation = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert operation["status"] == "succeeded"
        assert operation["result"]["action"] == "NEXT"
        assert analyzer.calls == []

        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        ended = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": view["revision"], "action": "end"},
            headers={"Idempotency-Key": "runtime-main-skip-end-0001"},
        ).json()["data"]
        assert (
            client.get(f"/api/v1/operations/{ended['operation_id']}").json()["data"][
                "status"
            ]
            == "succeeded"
        )
        report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
        skipped = next(
            item
            for item in report["root_assessments"]
            if item["root_question_id"] == skipped_root_id
        )

        assert skipped["status"] == "skipped"
        assert skipped["score"] is None
        assert report["coverage"]["skipped_root_count"] == 1
        assert report["coverage"]["skipped_question_count"] == 1
        assert report["completion"] == "incomplete"
        assert report["overall_score"] is None
        assert analyzer.calls == []


def test_report_failure_retry_does_not_reanalyze_or_duplicate_scores(
    tmp_path, monkeypatch
):
    analyzer = ScriptedAnalyzer(*(["adequate"] * 5))
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        interview_id = view["id"]
        for turn_index in range(4):
            accepted = client.post(
                f"/api/v1/interviews/{interview_id}/answers",
                json={
                    "expected_revision": view["revision"],
                    "question_id": view["current_question"]["id"],
                    "client_turn_id": f"turn-report-retry-{turn_index:04d}",
                    "answer_text": "先完成前四根题的受控回答。",
                },
                headers={"Idempotency-Key": f"runtime-report-retry-{turn_index:04d}"},
            ).json()["data"]
            assert (
                client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
                    "data"
                ]["status"]
                == "succeeded"
            )
            view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]

        original_create = client.app.state.services.reports.create_in_session

        def fail_report_once(*args, **kwargs):
            raise RuntimeError("synthetic report persistence failure")

        monkeypatch.setattr(
            client.app.state.services.reports,
            "create_in_session",
            fail_report_once,
        )
        accepted = client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            json={
                "expected_revision": view["revision"],
                "question_id": view["current_question"]["id"],
                "client_turn_id": "turn-report-retry-final",
                "answer_text": "第五根题回答已保存且分析成功。",
            },
            headers={"Idempotency-Key": "runtime-report-retry-final"},
        ).json()["data"]
        failed = client.get(f"/api/v1/operations/{accepted['operation_id']}").json()[
            "data"
        ]
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "INTERNAL_ERROR"
        assert len(analyzer.calls) == 5
        failed_view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        assert failed_view["status"] == "finish_failed"
        assert failed_view["report_id"] is None

        monkeypatch.setattr(
            client.app.state.services.reports,
            "create_in_session",
            original_create,
        )
        retried = client.post(
            f"/api/v1/operations/{accepted['operation_id']}/retry",
            json={"expected_revision": failed_view["revision"]},
            headers={"Idempotency-Key": "runtime-report-retry-command"},
        ).json()["data"]
        retry_operation = client.get(
            f"/api/v1/operations/{retried['operation_id']}"
        ).json()["data"]
        report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]

        assert retry_operation["status"] == "succeeded"
        assert retry_operation["parent_operation_id"] == accepted["operation_id"]
        assert retry_operation["result"]["report_id"] == report["id"]
        assert len(analyzer.calls) == 5
        assert len(report["root_assessments"]) == 5
        with Session(client.app.state.services.engine) as session:
            assert session.scalar(select(func.count(Assessment.id))) == 5
            assert session.scalar(select(func.count(Report.id))) == 1


def test_restart_marks_running_answer_interrupted_and_releases_interview(tmp_path):
    config = _config(tmp_path)
    app = create_app(config, knowledge=InMemoryKnowledge(), analyzer=ScriptedAnalyzer())
    with TestClient(app) as client:
        active = _prepare_active_interview(client)
        services = client.app.state.services
        command = OperationCommand(
            kind="interview.answer",
            resource_type="interview",
            resource_id=active["id"],
            scope=canon_scope(
                "local", "POST", f"/api/v1/interviews/{active['id']}/answers"
            ),
            idempotency_key="runtime-interrupt-key-01",
            input={
                "expected_revision": active["revision"],
                "question_id": active["current_question"]["id"],
                "client_turn_id": "turn-interrupt-0001",
                "answer_text": "进程重启前已受理的回答。",
            },
        )
        accepted = services.interviews.accept_answer(
            active["id"],
            expected_revision=active["revision"],
            question_id=active["current_question"]["id"],
            client_turn_id="turn-interrupt-0001",
            answer_text="进程重启前已受理的回答。",
            command=command,
        )
        services.operations.transition(accepted.operation.id, OperationStatus.RUNNING)
        operation_id = accepted.operation.id

    restarted = create_app(
        config, knowledge=InMemoryKnowledge(), analyzer=ScriptedAnalyzer()
    )
    with TestClient(restarted) as client:
        operation = client.get(f"/api/v1/operations/{operation_id}").json()["data"]
        assert operation["status"] == "interrupted"
        assert operation["error"]["code"] == "PROCESS_RESTARTED"
        view = client.get(f"/api/v1/interviews/{active['id']}").json()["data"]
        assert (
            view["current_question"]["accepted_answer"]["evaluation_status"] == "failed"
        )
        with Session(client.app.state.services.engine) as session:
            persisted = session.get(Operation, operation_id)
            assert persisted.last_event_seq == 1


def test_restart_releases_stale_terminal_interview_operation(tmp_path):
    """终态 Operation 的遗留指针不能让 ready/active 面试永久报 OPERATION_IN_PROGRESS。"""
    config = _config(tmp_path)
    app = create_app(config, knowledge=InMemoryKnowledge(), analyzer=ScriptedAnalyzer())
    with TestClient(app) as client:
        active = _prepare_active_interview(client)
        with Session(client.app.state.services.engine) as session, session.begin():
            operation = Operation(
                id="operation_stale_terminal",
                kind="interview.control.skip",
                resource_type="interview",
                resource_id=active["id"],
                scope="local|POST|/stale-terminal",
                idempotency_key="stale-terminal-key",
                input_hash="0" * 64,
                status=OperationStatus.FAILED,
                error={
                    "code": "INTERNAL_ERROR",
                    "message": "合成失败",
                    "retryable": True,
                },
            )
            session.add(operation)
            interview = session.get(Interview, active["id"])
            interview.active_operation_id = operation.id

    restarted = create_app(
        config, knowledge=InMemoryKnowledge(), analyzer=ScriptedAnalyzer()
    )
    with TestClient(restarted) as client:
        view = client.get(f"/api/v1/interviews/{active['id']}").json()["data"]
        assert view["active_operation_id"] is None
        assert view["status"] == "active"


def test_old_failed_answer_cannot_rewind_after_skip_or_reopen_completed(tmp_path):
    analyzer = ScriptedAnalyzer("invalid", "adequate")
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        interview_id = view["id"]
        failed = client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            json={
                "expected_revision": view["revision"],
                "question_id": view["current_question"]["id"],
                "client_turn_id": "obsolete-first-turn",
                "answer_text": "保留第一题失败回答。",
            },
            headers={"Idempotency-Key": "obsolete-first-answer"},
        ).json()["data"]
        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": view["revision"], "action": "skip"},
            headers={"Idempotency-Key": "obsolete-first-skip"},
        )
        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            json={
                "expected_revision": view["revision"],
                "question_id": view["current_question"]["id"],
                "client_turn_id": "current-second-turn",
                "answer_text": "第二题已回答成功。",
            },
            headers={"Idempotency-Key": "current-second-answer"},
        )
        view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        for completed in (False, True):
            response = client.post(
                f"/api/v1/operations/{failed['operation_id']}/retry",
                json={"expected_revision": view["revision"]},
                headers={"Idempotency-Key": f"obsolete-retry-{completed}"},
            )
            assert response.status_code == 409
            assert (
                client.get(f"/api/v1/interviews/{interview_id}").json()["data"] == view
            )
            assert len(analyzer.calls) == 2
            if not completed:
                client.post(
                    f"/api/v1/interviews/{interview_id}/control",
                    json={"expected_revision": view["revision"], "action": "end"},
                    headers={"Idempotency-Key": "obsolete-end-interview"},
                )
                view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
                assert view["status"] == "completed"


def test_late_answer_result_cannot_commit_after_cursor_moves(runtime_client):
    client, _ = runtime_client
    active = _prepare_active_interview(client)
    services = client.app.state.services
    payload = {
        "expected_revision": active["revision"],
        "question_id": active["current_question"]["id"],
        "client_turn_id": "late-commit-turn",
        "answer_text": "模型调用期间当前轮次发生变化。",
    }
    accepted = services.interviews.accept_answer(
        active["id"],
        **payload,
        command=OperationCommand(
            kind="interview.answer",
            resource_type="interview",
            resource_id=active["id"],
            scope=canon_scope(
                "local", "POST", f"/api/v1/interviews/{active['id']}/answers"
            ),
            idempotency_key="late-commit-answer",
            input=payload,
        ),
    )
    services.operations.transition(accepted.operation.id, OperationStatus.RUNNING)
    context = services.interviews._load_answer_context(accepted.operation.id)
    # Keep the old operation pointer: checking only ownership is insufficient.
    with Session(services.engine) as session, session.begin():
        interview = session.get(Interview, active["id"])
        interview.current_question_id = context.remaining_root_ids[0]
        interview.revision += 1
    with pytest.raises(InvalidStateError):
        services.interviews._commit_answer_result(
            operation_id=accepted.operation.id,
            context=context,
            observation={},
            decision={},
            usage={},
        )
    with Session(services.engine) as session:
        answer = session.get(Answer, accepted.answer_id)
        interview = session.get(Interview, active["id"])
        assert answer.evaluation_status == "processing"
        assert interview.current_question_id == context.remaining_root_ids[0]


@pytest.mark.parametrize(
    "changed",
    [
        {"jd_text": "不同的岗位要求：设计实时中断处理。"},
        {"pack_release_id": "kpr_0123456789abcdef"},
        {"profile_revision": 999},
        {"memory_enabled": True},
        {"observer_mode": True},
    ],
)
def test_plan_replay_compares_explicit_input_without_resolving_defaults(
    runtime_client, monkeypatch, changed
):
    client, _ = runtime_client
    active = _prepare_active_interview(client)
    profile = client.get(f"/api/v1/profiles/{active['profile_id']}").json()["data"]
    payload = {
        "profile_id": profile["id"],
        "profile_revision": profile["revision"],
        "jd_text": TEST_JD,
    }

    def unavailable_default(*args, **kwargs):
        raise AssertionError("A replay must not resolve the changed default pack")

    monkeypatch.setattr(
        client.app.state.services.knowledge_packs,
        "freeze_for_new_plan",
        unavailable_default,
    )
    replay = client.post(
        "/api/v1/interviews",
        json=payload,
        headers={"Idempotency-Key": "runtime-plan-key-000001"},
    )
    assert replay.status_code == 202
    assert replay.json()["data"]["resource_id"] == active["id"]
    conflict = client.post(
        "/api/v1/interviews",
        json={**payload, **changed},
        headers={"Idempotency-Key": "runtime-plan-key-000001"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_admitted_plan_and_questions_keep_review_snapshot_after_revocation(
    tmp_path, monkeypatch
):
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("adequate"),
    )
    with TestClient(app) as client:
        services = client.app.state.services
        create_plan = services.interviews.create_plan

        def revoke_after_admission(**kwargs):
            binding = kwargs["binding"]
            services.knowledge_packs.record_review(
                release_id=binding.release_id,
                expected_digest=binding.content_digest,
                decision="rejected",
                reviewer_id="runtime-test-owner",
                reviewer_role="owner",
                note="回归测试：受理后撤销，只影响新计划。",
            )
            return create_plan(**kwargs)

        monkeypatch.setattr(services.interviews, "create_plan", revoke_after_admission)
        active = _prepare_active_interview(client)
        accepted = client.post(
            f"/api/v1/interviews/{active['id']}/answers",
            json={
                "expected_revision": active["revision"],
                "question_id": active["current_question"]["id"],
                "client_turn_id": "frozen-review-turn",
                "answer_text": "继续使用本场受理时批准的评价依据。",
            },
            headers={"Idempotency-Key": "frozen-review-answer"},
        ).json()["data"]
        operation = services.operations.get(accepted["operation_id"])
        assert operation.status == "succeeded"
        profile = client.get(f"/api/v1/profiles/{active['profile_id']}").json()["data"]
        rejected = client.post(
            "/api/v1/interviews",
            json={"profile_id": profile["id"], "profile_revision": profile["revision"]},
            headers={"Idempotency-Key": "new-plan-after-review-revocation"},
        )
        assert rejected.status_code == 409
        with Session(services.engine) as session:
            interview = session.get(Interview, active["id"])
            assert interview.pack_review_snapshot["review"]["decision"] == "approved"


def test_failed_skip_cannot_retry_after_another_skip_advances(tmp_path, monkeypatch):
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=ScriptedAnalyzer()
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        services = app.state.services
        process_control = services.interviews.process_control

        def fail_control(**kwargs):
            raise RuntimeError("synthetic failed skip")

        monkeypatch.setattr(services.interviews, "process_control", fail_control)
        failed = client.post(
            f"/api/v1/interviews/{view['id']}/control",
            json={"expected_revision": view["revision"], "action": "skip"},
            headers={"Idempotency-Key": "obsolete-failed-skip"},
        ).json()["data"]
        monkeypatch.setattr(services.interviews, "process_control", process_control)
        view = client.get(f"/api/v1/interviews/{view['id']}").json()["data"]
        client.post(
            f"/api/v1/interviews/{view['id']}/control",
            json={"expected_revision": view["revision"], "action": "skip"},
            headers={"Idempotency-Key": "replacement-successful-skip"},
        )
        view = client.get(f"/api/v1/interviews/{view['id']}").json()["data"]
        response = client.post(
            f"/api/v1/operations/{failed['operation_id']}/retry",
            json={"expected_revision": view["revision"]},
            headers={"Idempotency-Key": "obsolete-failed-skip-retry"},
        )
        assert response.status_code == 409
        assert client.get(f"/api/v1/interviews/{view['id']}").json()["data"] == view


def test_concurrent_retry_and_skip_cannot_both_claim_current_turn(tmp_path):
    app = create_app(
        _config(tmp_path),
        knowledge=InMemoryKnowledge(),
        analyzer=ScriptedAnalyzer("invalid"),
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        failed = client.post(
            f"/api/v1/interviews/{view['id']}/answers",
            json={
                "expected_revision": view["revision"],
                "question_id": view["current_question"]["id"],
                "client_turn_id": "race-retry-skip-turn",
                "answer_text": "重试和跳过竞争同一轮次。",
            },
            headers={"Idempotency-Key": "race-retry-skip-answer"},
        ).json()["data"]
        view = client.get(f"/api/v1/interviews/{view['id']}").json()["data"]
        services = app.state.services
        barrier = threading.Barrier(2)
        accepted, errors = [], []

        def submit(action):
            barrier.wait()
            try:
                if action == "retry":
                    result = services.interviews.accept_retry(
                        failed["operation_id"],
                        expected_revision=view["revision"],
                        idempotency_key="race-current-retry",
                        request_input={"expected_revision": view["revision"]},
                    )
                else:
                    payload = {"expected_revision": view["revision"], "action": "skip"}
                    result = services.interviews.accept_control(
                        view["id"],
                        **payload,
                        command=OperationCommand(
                            kind="interview.control.skip",
                            resource_type="interview",
                            resource_id=view["id"],
                            scope=canon_scope(
                                "local",
                                "POST",
                                f"/api/v1/interviews/{view['id']}/control",
                            ),
                            idempotency_key="race-current-skip",
                            input=payload,
                        ),
                    )
                accepted.append(result)
            except Exception as exc:  # noqa: BLE001 - assert the losing domain error.
                errors.append(exc)

        threads = [
            threading.Thread(target=submit, args=(action,))
            for action in ("retry", "skip")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(accepted) == len(errors) == 1
        assert getattr(errors[0], "code", None) in {
            "REVISION_CONFLICT",
            "OPERATION_IN_PROGRESS",
        }
        latest = client.get(f"/api/v1/interviews/{view['id']}").json()["data"]
        assert latest["active_operation_id"] == accepted[0].operation.id
        assert latest["current_question"]["id"] == view["current_question"]["id"]


@pytest.mark.parametrize("final_action", ["skip", "answer"])
def test_already_admitted_end_succeeds_after_final_turn_without_duplicate_report(
    tmp_path, monkeypatch, final_action
):
    analyzer = ScriptedAnalyzer(*(["adequate"] * 5))
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        view = _prepare_active_interview(client)
        interview_id = view["id"]
        services = app.state.services
        for index in range(4):
            response = client.post(
                f"/api/v1/interviews/{interview_id}/answers",
                json={
                    "expected_revision": view["revision"],
                    "question_id": view["current_question"]["id"],
                    "client_turn_id": f"final-end-prepare-{index}",
                    "answer_text": "记录证据并说明自己的做法。",
                },
                headers={"Idempotency-Key": f"final-end-prepare-{index}"},
            )
            assert response.status_code == 202
            operation = services.operations.get(response.json()["data"]["operation_id"])
            assert operation.status == "succeeded", operation.error
            view = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]

        execute = services.runner._execute
        held = []

        async def hold_execution(job):
            held.append(job)

        monkeypatch.setattr(services.runner, "_execute", hold_execution)
        if final_action == "skip":
            final_payload = {"expected_revision": view["revision"], "action": "skip"}
            final_path = f"/api/v1/interviews/{interview_id}/control"
        else:
            final_payload = {
                "expected_revision": view["revision"],
                "question_id": view["current_question"]["id"],
                "client_turn_id": "final-end-last-answer",
                "answer_text": "最后一题保留原回答并形成评价。",
            }
            final_path = f"/api/v1/interviews/{interview_id}/answers"
        final_response = client.post(
            final_path,
            json=final_payload,
            headers={"Idempotency-Key": "final-end-final-turn"},
        )
        assert final_response.status_code == 202
        pending = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        end_payload = {"expected_revision": pending["revision"], "action": "end"}
        end_response = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json=end_payload,
            headers={"Idempotency-Key": "final-end-queued-end"},
        )
        assert end_response.status_code == 202, end_response.json()
        assert len(held) == 2
        assert held[0].operation_id == final_response.json()["data"]["operation_id"]
        assert held[1].operation_id == end_response.json()["data"]["operation_id"]
        assert services.operations.get(held[1].operation_id).status == "queued"
        assert asyncio.run(execute(held[0])) is None
        final_operation = services.operations.get(held[0].operation_id)
        assert final_operation.status == "succeeded", final_operation.error
        assert final_operation.result["action"] == "END"
        completed_before_end = None
        report_before_end = None
        if final_action == "skip":
            completed_before_end = client.get(
                f"/api/v1/interviews/{interview_id}"
            ).json()["data"]
            assert completed_before_end["status"] == "completed"
            report_before_end = client.get(
                f"/api/v1/interviews/{interview_id}/report"
            ).json()["data"]
            assert final_operation.result["report_id"] == report_before_end["id"]

        assert asyncio.run(execute(held[1])) is None
        end_operation = services.operations.get(held[1].operation_id)
        assert end_operation.status == "succeeded", end_operation.error
        report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
        completed = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        assert (
            end_operation.result["report_id"] == report["id"] == completed["report_id"]
        )
        assert end_operation.result["action"] == "END"
        assert completed["status"] == "completed"
        assert completed["active_operation_id"] is None
        if completed_before_end is not None:
            assert completed == completed_before_end
            assert report == report_before_end
        assert len(analyzer.calls) == (4 if final_action == "skip" else 5)
        with Session(services.engine) as session:
            assert session.scalar(select(func.count(Report.id))) == 1
            assert session.scalar(select(func.count(Assessment.id))) == 5
        report_events = [
            event
            for event in services.operations.events_after(end_operation.id, 0)
            if event.event_type == "report.ready"
        ]
        assert len(report_events) == 1
        assert report_events[0].payload["report_id"] == report["id"]

        replay = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json=end_payload,
            headers={"Idempotency-Key": "final-end-queued-end"},
        )
        assert replay.status_code == 202
        assert replay.json()["data"]["operation_id"] == end_operation.id
        mismatch = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": completed["revision"], "action": "end"},
            headers={"Idempotency-Key": "final-end-queued-end"},
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        fresh_end = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": completed["revision"], "action": "end"},
            headers={"Idempotency-Key": "final-end-after-completion"},
        )
        assert fresh_end.status_code == 409
        assert fresh_end.json()["error"]["code"] == "INVALID_STATE"
        assert (
            client.get(f"/api/v1/interviews/{interview_id}").json()["data"] == completed
        )
        assert (
            client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
            == report
        )
        assert len(held) == 2


def test_stale_next_execution_cannot_advance_or_reopen_interview(runtime_client):
    client, analyzer = runtime_client
    view = _prepare_active_interview(client)
    services = client.app.state.services
    interview_id = view["id"]
    skipped = client.post(
        f"/api/v1/interviews/{interview_id}/control",
        json={"expected_revision": view["revision"], "action": "skip"},
        headers={"Idempotency-Key": "stale-next-original"},
    ).json()["data"]
    operation = services.operations.get(skipped["operation_id"])
    assert operation.status == "succeeded"
    assert operation.result["action"] == "NEXT"
    for is_completed in (False, True):
        current = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        with pytest.raises(InvalidStateError):
            services.interviews.process_control(operation_id=operation.id)
        assert (
            client.get(f"/api/v1/interviews/{interview_id}").json()["data"] == current
        )
        if not is_completed:
            ended = client.post(
                f"/api/v1/interviews/{interview_id}/control",
                json={"expected_revision": current["revision"], "action": "end"},
                headers={"Idempotency-Key": "stale-next-completion"},
            )
            assert ended.status_code == 202
    assert analyzer.calls == []
