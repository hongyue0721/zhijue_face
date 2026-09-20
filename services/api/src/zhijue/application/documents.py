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
from zhijue.application.content_workflow import (
    ContentGenerator,
    ContentWorkflowError,
    run_grounded_content_workflow,
)
from zhijue.domain.errors import DocumentRejected
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
            return [], self._metadata(workflow="not_run", usage=_NULL_USAGE)
        if self._generator is None:
            if self._run_mode == "live":
                raise RuntimeError(
                    "SERVICE_NOT_READY: live 模式缺少 P-EXTRACT 模型配置"
                )
            candidate = self._fixture_candidate(blocks)
            usage = _NULL_USAGE
            workflow = "deterministic_fixture"
        else:
            payload = {
                "document_kind": kind,
                "source_blocks": [
                    {
                        "id": block.id,
                        "page_number": block.page_number,
                        "text": block.text,
                    }
                    for block in blocks
                ],
            }
            try:
                result = asyncio.run(
                    run_grounded_content_workflow(
                        generator=self._generator,
                        task="extract_claims",
                        payload=payload,
                    )
                )
            except TimeoutError as exc:
                raise RuntimeError("UPSTREAM_TIMEOUT: P-EXTRACT 超时") from exc
            except ContentWorkflowError as exc:
                raise RuntimeError("UPSTREAM_FAILED: P-EXTRACT 输出无效") from exc
            candidate = result["candidate"]
            usage = result["usage"]
            workflow = "openjiuwen"
        claims = [
            ProposedClaimWrite(
                text=item["text"],
                source_block_id=item["source_block_id"],
                exact_quote=item["exact_quote"],
                section=item["section"],
            )
            for item in candidate["claims"]
        ]
        return claims, self._metadata(workflow=workflow, usage=usage)

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

    def _metadata(self, *, workflow: str, usage: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_mode": self._run_mode,
            "workflow": workflow,
            "workflow_version": "1.0.0",
            "prompt_version": "p-extract.1",
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
