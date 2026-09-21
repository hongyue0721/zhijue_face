"""A report must remain understandable before any optional answer rewriting."""

from fastapi.testclient import TestClient
from test_interview_runtime import (
    InMemoryKnowledge,
    ScriptedAnalyzer,
    _config,
    _prepare_active_interview,
)

from zhijue.api.app import create_app


def test_report_recovers_root_and_followup_without_content_generation(tmp_path):
    analyzer = ScriptedAnalyzer("probe", "adequate")
    app = create_app(
        _config(tmp_path), knowledge=InMemoryKnowledge(), analyzer=analyzer
    )
    with TestClient(app) as client:
        interview = _prepare_active_interview(client)
        interview_id = interview["id"]
        original_question = interview["current_question"]
        submitted = []
        for index, text in enumerate(
            ("我负责 UART DMA 接收。", "我用逻辑分析仪检查了帧间间隔，再核对接收缓冲。")
        ):
            question = interview["current_question"]
            response = client.post(
                f"/api/v1/interviews/{interview_id}/answers",
                json={
                    "expected_revision": interview["revision"],
                    "question_id": question["id"],
                    "client_turn_id": f"context-turn-{index}",
                    "answer_text": text,
                },
                headers={"Idempotency-Key": f"context-answer-{index}"},
            )
            assert response.status_code == 202
            operation = client.get(
                f"/api/v1/operations/{response.json()['data']['operation_id']}"
            ).json()["data"]
            assert operation["status"] == "succeeded", operation["error"]
            submitted.append(
                (question["id"], question["kind"], question["wording"], text)
            )
            interview = client.get(f"/api/v1/interviews/{interview_id}").json()["data"]
        assert submitted[1][1] == "probe"
        response = client.post(
            f"/api/v1/interviews/{interview_id}/control",
            json={"expected_revision": interview["revision"], "action": "end"},
            headers={"Idempotency-Key": "context-finish-interview"},
        )
        assert response.status_code == 202
        report = client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
        root = next(
            item
            for item in report["root_assessments"]
            if item["root_question_id"] == original_question["id"]
        )
        assert report["improvements_status"] == "not_requested"
        assert root["question_text"] == original_question["wording"]
        assert [
            (
                answer["question_id"],
                answer["question_kind"],
                answer["question_text"],
                answer["raw_text"],
            )
            for answer in root["answers"]
        ] == submitted
        assert all(
            item["answers"] == []
            for item in report["root_assessments"]
            if item["status"] == "unmeasured"
        )
        assert (
            client.get(f"/api/v1/interviews/{interview_id}/report").json()["data"]
            == report
        )
        assert len(analyzer.calls) == 2
