"""M3 interview runtime: real openJiuwen workflow, durable state, and recovery."""

from __future__ import annotations

import json
import threading
from collections import deque

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import Answer, Operation
from zhijue.adapters.db.operations import OperationCommand, canon_scope
from zhijue.api.app import AppConfig, create_app
from zhijue.application.answer_workflow import AnalysisResult
from zhijue.application.profiles import ActivationReceipt
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

    def __init__(self, *modes: str) -> None:
        self._modes = deque(modes or ("adequate",))
        self.calls: list[dict[str, object]] = []

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
        json={"profile_id": profile_id, "profile_revision": profile["revision"]},
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
        assert view["current_question"]["accepted_answer"] == {
            "id": view["current_question"]["accepted_answer"]["id"],
            "client_turn_id": "turn-retry-0001",
            "raw_text": "这份原始回答必须在失败后保留。",
            "evaluation_status": "failed",
        }

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
        assert view["status"] == "finishing"
        assert view["current_question"] is None
        assert len(view["root_results"]) == 5
        assert len(analyzer.calls) == 5


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
