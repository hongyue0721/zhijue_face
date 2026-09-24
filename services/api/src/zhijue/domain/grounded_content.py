"""Deterministic fact-boundary validation for generated coaching and resume text.

The model may reorganize wording, but every persisted content fragment must name
its immutable sources. These checks reject structurally invalid references and
high-risk numeric/ownership escalations; they do not claim semantic truth.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_NUMERIC_FACT = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,]\d+)*(?:\s*%)?")
_PLACEHOLDER = re.compile(
    r"(?:\bTBD\b|\bTODO\b|\bXXX\b|待补充|待确认|请填写|<[^>]+>|\{\{[^}]+\}\})",
    re.IGNORECASE,
)
_HIGH_RISK_ASSERTIONS = (
    "主导",
    "负责",
    "牵头",
    "独立",
    "解决",
    "提升",
    "降低",
    "优化",
    "实现",
    "完成",
    "设计",
    "开发",
    "搭建",
    "led",
    "lead",
    "owned",
    "responsible",
    "independently",
    "solely",
    "solved",
    "improved",
    "reduced",
    "optimized",
    "implemented",
    "completed",
    "designed",
    "developed",
    "built",
)
_TECHNICAL_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_+./#-]*")
_CONTACT_DATA = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|www\.|(?<!\d)1[3-9]\d{9}(?!\d))",
    re.IGNORECASE,
)


# 机器可读校验分类（研究/恢复诊断用）。键是下面各 raise 站点使用的固定英文消息，
# 因此消息文本与分类只有一处真源：新增失败分支必须同时登记到这里，
# tests/unit/test_grounded_content.py 会用 AST 扫全部 raise 字面量并断言覆盖率 100%。
# 生产 API 不返回这些 code；异常 message 逐字节保持不变。
VALIDATION_CODES: dict[str, str] = {
    "generated content must be one object": "SCHEMA_INVALID",
    "generated content failed its JSON Schema": "SCHEMA_INVALID",
    "claim extraction referenced an unknown source block": "UNKNOWN_SOURCE",
    "claim extraction quote is not verbatim": "INVALID_SOURCE_QUOTE",
    "claim extraction may not rewrite source text": "CLAIM_REWRITE_FORBIDDEN",
    "claim extraction may not persist contact data": "CONTACT_DATA_REJECTED",
    "claim extraction returned a duplicate candidate": "DUPLICATE_CANDIDATE",
    "generated content introduced an unbound numeric fact": "UNBOUND_NUMERIC_FACT",
    "generated content introduced an unbound high-risk assertion": (
        "UNBOUND_HIGH_RISK_ASSERTION"
    ),
    "generated content introduced an unbound technical token": (
        "UNBOUND_TECHNICAL_TOKEN"
    ),
    "coaching result changed report_id": "REPORT_ID_MISMATCH",
    "duplicate coaching root question": "DUPLICATE_ROOT",
    "coaching referenced an unknown root": "UNKNOWN_ROOT",
    "coaching answer quote is not verbatim": "INVALID_ANSWER_QUOTE",
    "coaching referenced a claim outside the snapshot": "CLAIM_OUTSIDE_SNAPSHOT",
    "coaching segments do not reproduce rewritten_answer": "SEGMENT_MISMATCH",
    "coaching claim summary does not match segment references": "CLAIM_SUMMARY_MISMATCH",
    "coaching result did not cover every answered root": "COVERAGE_MISMATCH",
    "resume result changed draft_id": "DRAFT_ID_MISMATCH",
    "duplicate resume section": "DUPLICATE_SECTION",
    "duplicate resume item": "DUPLICATE_ITEM",
    "resume content contains a placeholder": "PLACEHOLDER_CONTENT",
    "resume referenced a claim outside the snapshot": "CLAIM_OUTSIDE_SNAPSHOT",
}

UNCLASSIFIED_VALIDATION_CODE = "UNCLASSIFIED_GROUNDED_CONTENT_FAILURE"


class GroundedContentValidationError(ValueError):
    """Generated candidate violates a deterministic grounding invariant.

    ``code`` 是按消息文本查表得到的稳定分类；缺失时明确落到
    ``UNCLASSIFIED_GROUNDED_CONTENT_FAILURE``，不猜。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code: str = VALIDATION_CODES.get(message, UNCLASSIFIED_VALIDATION_CODE)


def _contracts_root() -> Path:
    here = Path(__file__).resolve()
    return next(
        parent / "contracts"
        for parent in here.parents
        if (parent / "contracts").is_dir()
    )


@lru_cache(maxsize=3)
def _validator(filename: str) -> Draft202012Validator:
    schema_path = _contracts_root() / filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_schema(candidate: Any, filename: str) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise GroundedContentValidationError("generated content must be one object")
    errors = sorted(_validator(filename).iter_errors(candidate), key=str)
    if errors:
        raise GroundedContentValidationError(
            "generated content failed its JSON Schema"
        ) from None
    return candidate


def _contains_assertion(text: str, phrase: str) -> bool:
    if phrase.isascii():
        return re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE) is not None
    return phrase in text


def _reject_unbound_assertions(text: str, source_texts: list[str]) -> None:
    combined_sources = "\n".join(source_texts)
    source_numbers = set(_NUMERIC_FACT.findall(combined_sources))
    introduced_numbers = set(_NUMERIC_FACT.findall(text)) - source_numbers
    if introduced_numbers:
        raise GroundedContentValidationError(
            "generated content introduced an unbound numeric fact"
        )
    for phrase in _HIGH_RISK_ASSERTIONS:
        if _contains_assertion(text, phrase) and not _contains_assertion(
            combined_sources, phrase
        ):
            raise GroundedContentValidationError(
                "generated content introduced an unbound high-risk assertion"
            )
    source_tokens = {
        token.casefold() for token in _TECHNICAL_TOKEN.findall(combined_sources)
    }
    introduced_tokens = {
        token.casefold() for token in _TECHNICAL_TOKEN.findall(text)
    } - source_tokens
    if introduced_tokens:
        raise GroundedContentValidationError(
            "generated content introduced an unbound technical token"
        )


def validate_claim_extraction_candidate(
    candidate: Any, *, source_blocks: dict[str, str]
) -> dict[str, Any]:
    """Accept only verbatim, source-owned spans as proposed Claim candidates."""

    document = _validate_schema(candidate, "claim-extraction-result.schema.json")
    seen_texts: set[str] = set()
    seen_refs: set[tuple[str, str]] = set()
    for claim in document["claims"]:
        block_id = claim["source_block_id"]
        exact_quote = claim["exact_quote"]
        block_text = source_blocks.get(block_id)
        if block_text is None:
            raise GroundedContentValidationError(
                "claim extraction referenced an unknown source block"
            )
        if exact_quote not in block_text:
            raise GroundedContentValidationError(
                "claim extraction quote is not verbatim"
            )
        if claim["text"] != exact_quote:
            raise GroundedContentValidationError(
                "claim extraction may not rewrite source text"
            )
        if _CONTACT_DATA.search(exact_quote) is not None:
            raise GroundedContentValidationError(
                "claim extraction may not persist contact data"
            )
        reference = (block_id, exact_quote)
        if claim["text"] in seen_texts or reference in seen_refs:
            raise GroundedContentValidationError(
                "claim extraction returned a duplicate candidate"
            )
        seen_texts.add(claim["text"])
        seen_refs.add(reference)
    return document


def validate_coaching_candidate(
    candidate: Any,
    *,
    report_id: str,
    answers_by_root: dict[str, dict[str, str]],
    allowed_claims: dict[str, str],
) -> dict[str, Any]:
    """Validate and normalize one answer-rewrite candidate.

    Exact quotes must belong to an answer under the same root. Claim references
    are limited to the immutable ProfileSnapshot supplied by the application.
    """

    document = _validate_schema(candidate, "coaching-result.schema.json")
    if document["report_id"] != report_id:
        raise GroundedContentValidationError("coaching result changed report_id")

    items_by_root: dict[str, dict[str, Any]] = {}
    for item in document["items"]:
        root_id = item["root_question_id"]
        if root_id in items_by_root:
            raise GroundedContentValidationError("duplicate coaching root question")
        root_answers = answers_by_root.get(root_id)
        if root_answers is None:
            raise GroundedContentValidationError("coaching referenced an unknown root")

        claim_ids: set[str] = set()
        segment_texts: list[str] = []
        for segment in item["segments"]:
            segment_sources: list[str] = []
            segment_texts.append(segment["text"])
            for source_ref in segment["source_refs"]:
                if source_ref["type"] == "answer_quote":
                    answer_text = root_answers.get(source_ref["answer_id"])
                    if (
                        answer_text is None
                        or source_ref["exact_quote"] not in answer_text
                    ):
                        raise GroundedContentValidationError(
                            "coaching answer quote is not verbatim"
                        )
                    segment_sources.append(source_ref["exact_quote"])
                else:
                    claim_id = source_ref["claim_id"]
                    claim_text = allowed_claims.get(claim_id)
                    if claim_text is None:
                        raise GroundedContentValidationError(
                            "coaching referenced a claim outside the snapshot"
                        )
                    claim_ids.add(claim_id)
                    segment_sources.append(claim_text)
            _reject_unbound_assertions(segment["text"], segment_sources)

        if "".join(segment_texts) != item["rewritten_answer"]:
            raise GroundedContentValidationError(
                "coaching segments do not reproduce rewritten_answer"
            )
        if set(item["used_claim_ids"]) != claim_ids:
            raise GroundedContentValidationError(
                "coaching claim summary does not match segment references"
            )
        normalized_item = dict(item)
        normalized_item["used_claim_ids"] = sorted(claim_ids)
        items_by_root[root_id] = normalized_item

    if set(items_by_root) != set(answers_by_root):
        raise GroundedContentValidationError(
            "coaching result did not cover every answered root"
        )
    return {
        "schema_version": "1.0.0",
        "report_id": report_id,
        "items": [items_by_root[root_id] for root_id in answers_by_root],
    }


def validate_resume_candidate(
    candidate: Any,
    *,
    draft_id: str,
    allowed_claims: dict[str, str],
) -> dict[str, Any]:
    """Validate resume sections against one immutable confirmed-claim set."""

    document = _validate_schema(candidate, "resume-draft-result.schema.json")
    if document["draft_id"] != draft_id:
        raise GroundedContentValidationError("resume result changed draft_id")

    section_ids: set[str] = set()
    item_ids: set[str] = set()
    source_claim_ids: set[str] = set()
    normalized_sections: list[dict[str, Any]] = []
    for section in document["sections"]:
        section_id = section["section_id"]
        if section_id in section_ids:
            raise GroundedContentValidationError("duplicate resume section")
        section_ids.add(section_id)
        normalized_items: list[dict[str, Any]] = []
        for item in section["items"]:
            if item["item_id"] in item_ids:
                raise GroundedContentValidationError("duplicate resume item")
            item_ids.add(item["item_id"])
            if _PLACEHOLDER.search(item["text"]):
                raise GroundedContentValidationError(
                    "resume content contains a placeholder"
                )
            source_texts: list[str] = []
            for claim_id in item["claim_ids"]:
                claim_text = allowed_claims.get(claim_id)
                if claim_text is None:
                    raise GroundedContentValidationError(
                        "resume referenced a claim outside the snapshot"
                    )
                source_claim_ids.add(claim_id)
                source_texts.append(claim_text)
            _reject_unbound_assertions(item["text"], source_texts)
            normalized_items.append(dict(item))
        normalized_sections.append({**section, "items": normalized_items})

    return {
        "schema_version": "1.0.0",
        "draft_id": draft_id,
        "sections": normalized_sections,
        "source_claim_ids": sorted(source_claim_ids),
        "missing_facts": list(document["missing_facts"]),
        "cautions": list(document["cautions"]),
    }
