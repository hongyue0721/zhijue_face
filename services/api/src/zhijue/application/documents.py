"""Document import: extract text, select verbatim claims, then commit atomically.

P-EXTRACT is untrusted: live mode runs it through the real openJiuwen Workflow,
then deterministic validation proves every proposed Claim is an exact source
span. Knowledge activation remains a separate user-confirmation responsibility.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from zhijue.adapters.db.documents import (
    BlockPage,
    DocumentRepository,
    DocumentWriteResult,
    ProposedClaimWrite,
    SourceBlockWrite,
)
from zhijue.adapters.db.models import Document
from zhijue.adapters.pdf import extract_pdf_pages, extract_text_pages, sniff_kind
from zhijue.application.answer_workflow import (
    ModelRequestError,
    ModelRequestTimeoutError,
)
from zhijue.application.content_workflow import (
    ContentGenerator,
    ContentWorkflowError,
    run_grounded_content_workflow,
)
from zhijue.domain.errors import (
    DocumentRejected,
    ServiceUnavailableError,
    UpstreamError,
)
from zhijue.domain.extraction import ExtractionLimits, decide_status
from zhijue.domain.ids import new_id

_ALLOWED_KINDS = {"resume", "project"}
_MIME_BY_KIND = {
    "pdf": {
        "resume": "application/pdf",
        "project": "application/pdf",
    },
    "text": {
        "resume": "text/plain; charset=utf-8",
        "project": "text/plain; charset=utf-8",
    },
}

_SECTION_HEADINGS = {
    "基本信息": "basic",
    "个人信息": "basic",
    "教育经历": "education",
    "教育背景": "education",
    "项目经历": "project",
    "项目经验": "project",
    "实习经历": "project",
    "工作经历": "project",
    "专业技能": "skill",
    "技能": "skill",
    "技能清单": "skill",
    "荣誉奖项": "award",
    "获奖经历": "award",
    "奖项": "award",
    "自我评价": "other",
    "其他": "other",
}
_CONTACT_DATA = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|www\.|(?<!\d)1[3-9]\d{9}(?!\d))",
    re.IGNORECASE,
)
_NULL_USAGE = {
    "input_tokens": None,
    "output_tokens": None,
    "total_tokens": None,
    "cost": None,
}

_MAX_PROPOSED_CLAIMS = 50
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；.!?;])")


def _split_block_text(text: str, limit: int) -> list[str]:
    """把一个块切成 ≤limit 字符的连续段。

    切分无损：段按序拼接可还原原文，因此模型从段内选的 exact_quote
    仍是入库块文本的逐字子串，逐字来源不变量不被分块破坏。只有单句
    超过预算时才硬切。
    """
    if len(text) <= limit:
        return [text] if text.strip() else []
    segments: list[str] = []
    current = ""
    for piece in _SENTENCE_BOUNDARY.split(text):
        while len(piece) > limit:
            if current:
                segments.append(current)
                current = ""
            segments.append(piece[:limit])
            piece = piece[limit:]
        if not piece:
            continue
        if len(current) + len(piece) <= limit:
            current += piece
        else:
            segments.append(current)
            current = piece
    if current:
        segments.append(current)
    return segments


def _build_extract_batches(
    blocks: list[SourceBlockWrite], limit: int
) -> list[list[dict[str, Any]]]:
    """按源顺序把连续段打包成每次模型调用的批次。"""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for block in blocks:
        for segment in _split_block_text(block.text, limit):
            if current and current_chars + len(segment) > limit:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(
                {
                    "id": block.id,
                    "page_number": block.page_number,
                    "text": segment,
                }
            )
            current_chars += len(segment)
    if current:
        batches.append(current)
    return batches


def _merge_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    """只有每次调用都报告了某 usage 字段才求和；任一未知则该字段保持 null。"""
    merged: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "cost"):
        values = [usage.get(key) for usage in usages]
        known = bool(values) and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in values
        )
        merged[key] = sum(values) if known else None
    return merged


@dataclass(frozen=True)
class DocumentImportResult:
    document: Document
    resource_revision: int
    proposed_claim_count: int
    extraction_metadata: dict[str, Any]


class DocumentService:
    def __init__(
        self,
        *,
        engine: Engine,
        repo: DocumentRepository,
        limits: ExtractionLimits,
        generator: ContentGenerator | None = None,
        run_mode: str = "fixture",
        generator_metadata: dict[str, Any] | None = None,
        extractors: Mapping[str, Callable[..., list[Any]]] | None = None,
    ) -> None:
        self._engine = engine
        self._repo = repo
        self._generator = generator
        self._run_mode = run_mode
        self._generator_metadata = dict(generator_metadata or {})
        self.limits = limits
        self._extractors: Mapping[str, Callable[..., list[Any]]] = extractors or {
            "pdf": extract_pdf_pages,
            "text": extract_text_pages,
        }

    def session(self) -> Session:
        return Session(self._engine)

    def import_document(
        self,
        *,
        profile_id: str,
        expected_revision: int,
        data: bytes,
        filename: str,
        kind: str,
    ) -> DocumentImportResult:
        if kind not in _ALLOWED_KINDS:
            raise DocumentRejected(
                "INVALID_REQUEST", f"kind 必须是 resume/project：{kind!r}"
            )
        if len(data) > self.limits.max_bytes:
            raise DocumentRejected(
                "FILE_TOO_LARGE",
                f"文件 {len(data)} 字节，超过上限 {self.limits.max_bytes}。",
                retry_hint="reduce_document",
            )
        self._repo.require_revision(profile_id, expected_revision)
        if self._repo.count_for_profile(profile_id) >= self.limits.max_documents:
            raise DocumentRejected(
                "DOCUMENT_LIMIT",
                f"每个档案最多 {self.limits.max_documents} 份材料。",
                retry_hint="delete_first",
            )

        sniffed = sniff_kind(data)
        pages = self._extractors[sniffed](data, limits=self.limits)
        status, warnings = decide_status(pages)
        blocks = [
            SourceBlockWrite(
                id=new_id("block"),
                page_number=page.page_number,
                block_index=0,
                text=page.text,
                origin="text_layer",
            )
            for page in pages
            if page.text.strip()
        ]
        claims, extraction_metadata = self._extract_claims(kind=kind, blocks=blocks)
        if status == "parsed" and not claims:
            warnings.append(
                "没有识别到可确认的候选事实；请查看解析文本并手工补充经历。"
            )
        page_count = (
            max(
                (page.page_number or 0 for page in pages),
                default=0,
            )
            or None
        )
        stored = self._repo.save(
            profile_id=profile_id,
            expected_revision=expected_revision,
            kind=kind,
            filename_display=filename,
            data=data,
            mime=_MIME_BY_KIND[sniffed][kind],
            extract_status=status,
            warnings=warnings,
            page_count=page_count,
            blocks=blocks,
            claims=claims,
        )
        return self._result(stored, extraction_metadata)

    def _extract_claims(
        self, *, kind: str, blocks: list[SourceBlockWrite]
    ) -> tuple[list[ProposedClaimWrite], dict[str, Any]]:
        if not blocks:
            return [], self._metadata(
                workflow="not_run", usage=_NULL_USAGE, model_calls=0
            )
        if self._generator is None:
            if self._run_mode == "live":
                raise ServiceUnavailableError(
                    "live 模式缺少 P-EXTRACT 模型配置，未执行材料解析。"
                )
            candidate = self._fixture_candidate(blocks)
            return [
                ProposedClaimWrite(
                    text=item["text"],
                    source_block_id=item["source_block_id"],
                    exact_quote=item["exact_quote"],
                    section=item["section"],
                )
                for item in candidate["claims"]
            ], self._metadata(
                workflow="deterministic_fixture",
                usage=_NULL_USAGE,
                model_calls=0,
            )
        # 长文档按连续段预算分多次真实 Workflow 调用；每次调用自身有
        # transport 总超时与块间 stall 预算，任一批失败则整体不落部分结果。
        batches = _build_extract_batches(blocks, self.limits.max_chars_per_extract_call)
        if not batches:
            return [], self._metadata(
                workflow="not_run", usage=_NULL_USAGE, model_calls=0
            )
        collected: list[dict[str, str]] = []
        seen_quotes: set[tuple[str, str]] = set()
        usages: list[dict[str, Any]] = []
        for batch in batches:
            payload = {"document_kind": kind, "source_blocks": batch}
            try:
                result = asyncio.run(
                    run_grounded_content_workflow(
                        generator=self._generator,
                        task="extract_claims",
                        payload=payload,
                    )
                )
            except TimeoutError as exc:
                raise UpstreamError("P-EXTRACT 材料解析超时。", timeout=True) from exc
            except ModelRequestTimeoutError as exc:
                raise UpstreamError(
                    "P-EXTRACT 模型请求超时，请重新选择并上传文件。",
                    timeout=True,
                ) from exc
            except ModelRequestError as exc:
                raise UpstreamError(
                    "P-EXTRACT 模型服务请求失败，请重新选择并上传文件。"
                ) from exc
            except ContentWorkflowError as exc:
                raise UpstreamError("P-EXTRACT 结果未通过事实来源校验。") from exc
            usages.append(result["usage"])
            for item in result["candidate"]["claims"]:
                key = (item["source_block_id"], item["exact_quote"])
                if key in seen_quotes:
                    continue
                seen_quotes.add(key)
                collected.append(item)
        if len(collected) > _MAX_PROPOSED_CLAIMS:
            # api.md：超过 50 条全部拒绝，不落部分结果，也不静默截断。
            raise UpstreamError(
                "P-EXTRACT 候选事实超过单次 50 条上限，请精简材料后重新上传。"
            )
        claims = [
            ProposedClaimWrite(
                text=item["text"],
                source_block_id=item["source_block_id"],
                exact_quote=item["exact_quote"],
                section=item["section"],
            )
            for item in collected
        ]
        return claims, self._metadata(
            workflow="openjiuwen",
            usage=_merge_usage(usages),
            model_calls=len(batches),
        )

    @staticmethod
    def _fixture_candidate(blocks: list[SourceBlockWrite]) -> dict[str, Any]:
        claims: list[dict[str, str]] = []
        seen: set[str] = set()
        section = "other"
        for block in blocks:
            for raw_line in block.text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                heading = line.rstrip("：:").strip()
                mapped = _SECTION_HEADINGS.get(heading)
                if mapped is not None:
                    section = mapped
                    continue
                for label, label_section in _SECTION_HEADINGS.items():
                    if line.startswith((f"{label}：", f"{label}:")):
                        section = label_section
                        break
                if (
                    line in seen
                    or len(line) > 2_000
                    or _CONTACT_DATA.search(line) is not None
                ):
                    continue
                seen.add(line)
                claims.append(
                    {
                        "text": line,
                        "source_block_id": block.id,
                        "exact_quote": line,
                        "section": section,
                    }
                )
                if len(claims) == 50:
                    return {"schema_version": "1.0.0", "claims": claims}
        return {"schema_version": "1.0.0", "claims": claims}

    def _metadata(
        self, *, workflow: str, usage: dict[str, Any], model_calls: int
    ) -> dict[str, Any]:
        return {
            "run_mode": self._run_mode,
            "workflow": workflow,
            "workflow_version": "1.0.0",
            "prompt_version": "p-extract.1",
            "model_calls": model_calls,
            "generator": dict(self._generator_metadata),
            "usage": dict(usage),
        }

    @staticmethod
    def _result(
        stored: DocumentWriteResult, extraction_metadata: dict[str, Any]
    ) -> DocumentImportResult:
        return DocumentImportResult(
            document=stored.document,
            resource_revision=stored.resource_revision,
            proposed_claim_count=stored.proposed_claim_count,
            extraction_metadata=extraction_metadata,
        )

    def list_blocks(
        self, document_id: str, *, cursor: str | None, limit: int
    ) -> BlockPage:
        return self._repo.list_blocks(document_id, cursor=cursor, limit=limit)

    def list_documents(self, profile_id: str) -> list[Document]:
        return self._repo.list_documents(profile_id)

    def get_document(self, document_id: str) -> Document | None:
        return self._repo.get(document_id)
