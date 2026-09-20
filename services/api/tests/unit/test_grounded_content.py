"""M4-02 grounded generation boundaries: model output never becomes facts by itself."""

from __future__ import annotations

import asyncio
import json

import pytest

from zhijue.application.answer_workflow import AnalysisResult
from zhijue.application.content_workflow import run_grounded_content_workflow
from zhijue.domain.grounded_content import (
    GroundedContentValidationError,
    validate_claim_extraction_candidate,
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


def test_claim_extraction_accepts_only_verbatim_source_spans():
    source_blocks = {
        "block_project": "项目经历\n使用 STM32 HAL 和 DMA 完成串口接收。",
        "block_skill": "专业技能\n熟悉 FreeRTOS Queue。",
    }
    candidate = {
        "schema_version": "1.0.0",
        "claims": [
            {
                "text": "使用 STM32 HAL 和 DMA 完成串口接收。",
                "source_block_id": "block_project",
                "exact_quote": "使用 STM32 HAL 和 DMA 完成串口接收。",
                "section": "project",
            },
            {
                "text": "熟悉 FreeRTOS Queue。",
                "source_block_id": "block_skill",
                "exact_quote": "熟悉 FreeRTOS Queue。",
                "section": "skill",
            },
        ],
    }

    assert (
        validate_claim_extraction_candidate(candidate, source_blocks=source_blocks)
        == candidate
    )


@pytest.mark.parametrize(
    "claim",
    [
        {
            "text": "主导 STM32 项目。",
            "source_block_id": "block_project",
            "exact_quote": "使用 STM32 HAL。",
            "section": "project",
        },
        {
            "text": "使用 STM32 HAL。",
            "source_block_id": "block_foreign",
            "exact_quote": "使用 STM32 HAL。",
            "section": "project",
        },
        {
            "text": "使用 STM32 HAL。",
            "source_block_id": "block_project",
            "exact_quote": "不存在的原文",
            "section": "project",
        },
    ],
)
def test_claim_extraction_rejects_rewording_foreign_blocks_and_fake_quotes(claim):
    with pytest.raises(GroundedContentValidationError):
        validate_claim_extraction_candidate(
            {"schema_version": "1.0.0", "claims": [claim]},
            source_blocks={"block_project": "使用 STM32 HAL。"},
        )


@pytest.mark.parametrize("contact", ["demo@example.com", "13800138000"])
def test_claim_extraction_rejects_contact_data(contact):
    with pytest.raises(GroundedContentValidationError, match="contact data"):
        validate_claim_extraction_candidate(
            {
                "schema_version": "1.0.0",
                "claims": [
                    {
                        "text": contact,
                        "source_block_id": "block_basic",
                        "exact_quote": contact,
                        "section": "basic",
                    }
                ],
            },
            source_blocks={"block_basic": contact},
        )


def test_claim_extraction_runs_through_real_openjiuwen_workflow():
    class Extractor:
        async def generate(self, *, task, payload):
            assert task == "extract_claims"
            return AnalysisResult(
                content=json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "claims": [
                            {
                                "text": "使用 STM32 DMA。",
                                "source_block_id": "block_demo",
                                "exact_quote": "使用 STM32 DMA。",
                                "section": "project",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
            )

    result = asyncio.run(
        run_grounded_content_workflow(
            generator=Extractor(),
            task="extract_claims",
            payload={
                "document_kind": "resume",
                "source_blocks": [
                    {
                        "id": "block_demo",
                        "page_number": 1,
                        "text": "使用 STM32 DMA。",
                    }
                ],
            },
        )
    )

    assert result["candidate"]["claims"][0]["exact_quote"] == "使用 STM32 DMA。"
    assert result["usage"]["total_tokens"] == 15


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
