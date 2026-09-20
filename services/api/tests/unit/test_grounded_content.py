"""M4-02 grounded generation boundaries: model output never becomes facts by itself."""

from __future__ import annotations

import pytest

from zhijue.domain.grounded_content import (
    GroundedContentValidationError,
    validate_coaching_candidate,
    validate_resume_candidate,
)


def _coaching_candidate(rewritten_answer: str, *, refs: list[dict[str, str]]):
    return {
        "schema_version": "1.0.0",
        "report_id": "report_demo",
        "items": [
            {
                "root_question_id": "question_root",
                "rewritten_answer": rewritten_answer,
                "segments": [{"text": rewritten_answer, "source_refs": refs}],
                "used_claim_ids": sorted(
                    ref["claim_id"] for ref in refs if ref["type"] == "claim"
                ),
                "changes": ["调整表达顺序"],
                "missing_facts": [],
                "cautions": [],
            }
        ],
    }


def test_coaching_accepts_only_exact_answer_quotes_and_snapshot_claims():
    answer_text = "我使用 FreeRTOS Queue 传递采样数据，并通过日志定位问题。"
    candidate = _coaching_candidate(
        "我使用 Queue 传递采样数据，并结合日志定位问题。",
        refs=[
            {
                "type": "answer_quote",
                "answer_id": "answer_demo",
                "exact_quote": answer_text,
            },
            {"type": "claim", "claim_id": "claim_demo"},
        ],
    )

    result = validate_coaching_candidate(
        candidate,
        report_id="report_demo",
        answers_by_root={"question_root": {"answer_demo": answer_text}},
        allowed_claims={"claim_demo": "使用 FreeRTOS Queue 传递采样数据"},
    )

    assert result["items"][0]["used_claim_ids"] == ["claim_demo"]


def test_coaching_rejects_foreign_claim_or_non_verbatim_quote():
    candidate = _coaching_candidate(
        "我使用 Queue 传递数据。",
        refs=[
            {
                "type": "answer_quote",
                "answer_id": "answer_demo",
                "exact_quote": "这句不在原回答中",
            },
            {"type": "claim", "claim_id": "claim_foreign"},
        ],
    )

    with pytest.raises(GroundedContentValidationError):
        validate_coaching_candidate(
            candidate,
            report_id="report_demo",
            answers_by_root={
                "question_root": {"answer_demo": "我使用 Queue 传递数据。"}
            },
            allowed_claims={"claim_demo": "使用 Queue"},
        )


@pytest.mark.parametrize(
    "rewritten_answer",
    [
        "我将错误率降低了 30%。",
        "我主导了整个系统的实现。",
        "我负责系统调试。",
        "我使用 Kubernetes 完成部署。",
    ],
)
def test_coaching_rejects_new_numeric_or_ownership_claims(rewritten_answer: str):
    source = "我参与了系统调试。"
    candidate = _coaching_candidate(
        rewritten_answer,
        refs=[
            {
                "type": "answer_quote",
                "answer_id": "answer_demo",
                "exact_quote": source,
            }
        ],
    )

    with pytest.raises(GroundedContentValidationError):
        validate_coaching_candidate(
            candidate,
            report_id="report_demo",
            answers_by_root={"question_root": {"answer_demo": source}},
            allowed_claims={},
        )


def test_resume_items_require_snapshot_claims_and_forbid_placeholders():
    candidate = {
        "schema_version": "1.0.0",
        "draft_id": "resume_demo",
        "sections": [
            {
                "section_id": "projects",
                "title": "项目经历",
                "items": [
                    {
                        "item_id": "item_demo",
                        "text": "待补充：主导项目并提升性能 50%。",
                        "claim_ids": [],
                        "reason": "突出项目能力",
                    }
                ],
            }
        ],
        "missing_facts": [],
        "cautions": [],
    }

    with pytest.raises(GroundedContentValidationError):
        validate_resume_candidate(
            candidate,
            draft_id="resume_demo",
            allowed_claims={"claim_demo": "参与 UART 错帧排查"},
        )


def test_resume_accepts_grounded_items_and_derives_claim_union():
    candidate = {
        "schema_version": "1.0.0",
        "draft_id": "resume_demo",
        "sections": [
            {
                "section_id": "projects",
                "title": "项目经历",
                "items": [
                    {
                        "item_id": "item_uart",
                        "text": "参与 UART 错帧排查，并记录定位过程。",
                        "claim_ids": ["claim_uart"],
                        "reason": "使调试经历更清晰",
                    }
                ],
            }
        ],
        "missing_facts": [],
        "cautions": [],
    }

    result = validate_resume_candidate(
        candidate,
        draft_id="resume_demo",
        allowed_claims={"claim_uart": "参与 UART 错帧排查并记录定位过程"},
    )

    assert result["source_claim_ids"] == ["claim_uart"]
