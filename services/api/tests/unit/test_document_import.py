"""M1-02 测试：PDF/文本导入、SourceBlock 定位与受控失败（T01—T04）。

全部使用合成 PDF（tests/fixtures_pdf.py）。断言业务可观察契约：
分页块、页码/块号、text_hash、requires_text 判定、失败原因码，
不是 pypdf 内部细节。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields

import pytest
from fixtures_pdf import encrypt_pdf, make_pdf

from zhijue.adapters.db.documents import DocumentRepository, SourceBlockWrite
from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import Base, Document, Profile
from zhijue.adapters.pdf import extract_pdf_pages, sniff_kind
from zhijue.application.answer_workflow import (
    AnalysisResult,
    ModelRequestTimeoutError,
)
from zhijue.application.documents import (
    DocumentService,
    _build_extract_batches,
    _split_block_text,
)
from zhijue.domain.errors import DocumentRejected, UpstreamError
from zhijue.domain.extraction import ExtractionLimits


def _limits(**overrides):
    kwargs = {
        "max_bytes": 10_000_000,
        "max_pages": 5,
        "max_chars": 30_000,
        "max_documents": 5,
    }
    kwargs.update(overrides)
    return ExtractionLimits(**kwargs)


@pytest.fixture()
def service(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'docs.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            Profile.__table__.insert().values(
                id="profile_1",
                workspace_id="local",
                display_name="合成候选人",
                synthetic=1,
                status="active",
                revision=0,
                created_at="2026-09-18T00:00:00Z",
                updated_at="2026-09-18T00:00:00Z",
            )
        )

    return DocumentService(
        engine=engine,
        repo=DocumentRepository(engine),
        limits=_limits(max_bytes=1_000_000),
    )


# ---------------- 纯提取层 ----------------


def test_extract_keeps_page_numbers_and_text():
    data = make_pdf(["第一页内容 STM32 HAL", "", "第三页 CAN 仲裁"])
    pages = extract_pdf_pages(data, limits=_limits())
    assert [p.page_number for p in pages] == [1, 2, 3]  # page 从 1 起（docs/03 §3）
    assert pages[0].text == "第一页内容 STM32 HAL"
    assert pages[1].text == ""  # 空页保留结构，不静默丢页（T03 前提）
    assert pages[2].text == "第三页 CAN 仲裁"


def test_extract_rejects_encrypted_document():
    data = encrypt_pdf(make_pdf(["secret"]))
    with pytest.raises(DocumentRejected) as exc:
        extract_pdf_pages(data, limits=_limits())
    assert exc.value.code == "DOCUMENT_ENCRYPTED"
    # api.md §4：不要求用户交密码，给粘贴文本指引。
    assert exc.value.retry_hint == "paste_text"


def test_extract_enforces_page_and_char_limits():
    with pytest.raises(DocumentRejected) as exc:
        extract_pdf_pages(make_pdf(["x"] * 6), limits=_limits(max_pages=5))
    assert exc.value.code == "TOO_MANY_PAGES"

    big = make_pdf(["字" * 200])
    with pytest.raises(DocumentRejected) as exc:
        extract_pdf_pages(big, limits=_limits(max_chars=100))
    assert exc.value.code == "TEXT_TOO_LARGE"


def test_extract_rejects_corrupt_bytes():
    with pytest.raises(DocumentRejected) as exc:
        extract_pdf_pages(b"%PDF-1.4\nthis is not a real body", limits=_limits())
    assert exc.value.code == "DOCUMENT_UNREADABLE"


def test_sniff_kind_uses_magic_not_extension():
    assert sniff_kind(make_pdf(["a"])) == "pdf"
    assert sniff_kind("纯文本简历".encode()) == "text"
    with pytest.raises(DocumentRejected) as exc:
        sniff_kind(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert exc.value.code == "UNSUPPORTED_FILE_TYPE"


# ---------------- 应用服务 + 仓储 ----------------


def test_import_text_pdf_produces_blocks_with_hash(service):
    data = make_pdf(["项目经历：ESP32-S3 FreeRTOS Queue", "技能：C 语言 STM32 CAN DMA"])
    document = service.import_document(
        profile_id="profile_1",
        expected_revision=0,
        data=data,
        filename="resume.pdf",
        kind="resume",
    ).document
    assert document.sha256 == hashlib.sha256(data).hexdigest()
    assert document.extract_status == "parsed"
    assert document.page_count == 2

    page = service.list_blocks(document.id, cursor=None, limit=20)
    assert [b.page_number for b in page.items] == [1, 2]
    assert [b.block_index for b in page.items] == [0, 0]
    for block in page.items:
        assert block.origin == "text_layer"
        assert hashlib.sha256(block.text.encode("utf-8")).hexdigest() == block.text_hash


def test_scanned_document_becomes_requires_text_not_empty_success(service):
    document = service.import_document(
        profile_id="profile_1",
        expected_revision=0,
        data=make_pdf(["", ""]),
        filename="scan.pdf",
        kind="resume",
    ).document
    # T02：扫描件不得输出"解析成功，识别了零项"的假成功。
    assert document.extract_status == "requires_text"
    assert any("文字层" in w or "粘贴" in w for w in document.warnings)


def test_model_timeout_is_reported_as_upstream_timeout(service):
    class TimedOutGenerator:
        async def generate(self, *, task, payload):
            del task, payload
            raise ModelRequestTimeoutError("model request timed out")

    live_service = DocumentService(
        engine=service._engine,
        repo=DocumentRepository(service._engine),
        limits=service.limits,
        generator=TimedOutGenerator(),
        run_mode="live",
    )

    with pytest.raises(UpstreamError) as raised:
        live_service.import_document(
            profile_id="profile_1",
            expected_revision=0,
            data=make_pdf(["项目经历：使用 STM32 DMA。"]),
            filename="resume.pdf",
            kind="resume",
        )

    assert raised.value.code == "UPSTREAM_TIMEOUT"
    assert raised.value.message == "P-EXTRACT 模型请求超时，请重新选择并上传文件。"
    with live_service.session() as session:
        assert session.query(Document).count() == 0


def test_mixed_pages_keep_readable_and_warn_on_missing(service):
    # T03：一页可读一页扫描 → 保留可读页，缺页明确提示。
    document = service.import_document(
        profile_id="profile_1",
        expected_revision=0,
        data=make_pdf(["有文字层的一页", ""]),
        filename="mixed.pdf",
        kind="resume",
    ).document
    assert document.extract_status == "parsed"
    assert document.warnings  # 明确记录了缺文字层页
    blocks = service.list_blocks(document.id, cursor=None, limit=20)
    assert [b.page_number for b in blocks.items] == [1]  # 空页不生成块


def test_encrypted_document_fails_without_persisting(service):
    with pytest.raises(DocumentRejected) as exc:
        service.import_document(
            profile_id="profile_1",
            expected_revision=0,
            data=encrypt_pdf(make_pdf(["x"])),
            filename="locked.pdf",
            kind="resume",
        )
    assert exc.value.code == "DOCUMENT_ENCRYPTED"
    assert exc.value.retry_hint == "paste_text"
    with service.session() as session:
        assert session.query(Document).count() == 0


def test_oversize_upload_rejected_before_parse(service):
    with pytest.raises(DocumentRejected) as exc:
        service.import_document(
            profile_id="profile_1",
            expected_revision=0,
            data=b"%PDF-1.4" + b"\x00" * (service.limits.max_bytes + 1),
            filename="huge.pdf",
            kind="resume",
        )
    assert exc.value.code == "FILE_TOO_LARGE"
    with service.session() as session:
        assert session.query(Document).count() == 0


def test_document_count_per_profile_limit(service):
    data = make_pdf(["内容"])
    for i in range(service.limits.max_documents):
        service.import_document(
            profile_id="profile_1",
            expected_revision=i,
            data=data,
            filename=f"d{i}.pdf",
            kind="project",
        )
    with pytest.raises(DocumentRejected) as exc:
        service.import_document(
            profile_id="profile_1",
            expected_revision=service.limits.max_documents,
            data=data,
            filename="more.pdf",
            kind="project",
        )
    assert exc.value.code == "DOCUMENT_LIMIT"


def test_replacement_creates_new_document_not_overwrite(service):
    first = service.import_document(
        profile_id="profile_1",
        expected_revision=0,
        data=make_pdf(["旧内容"]),
        filename="r.pdf",
        kind="resume",
    ).document
    second = service.import_document(
        profile_id="profile_1",
        expected_revision=1,
        data=make_pdf(["新内容"]),
        filename="r.pdf",
        kind="resume",
    ).document
    assert first.id != second.id  # 原件不可覆盖，替换产生新 Document（docs/03 §3）
    assert second.filename_display == first.filename_display


def test_blocks_pagination_cursor_stable(service):
    pages = [f"第{i}页 内容" for i in range(1, 6)]
    doc = service.import_document(
        profile_id="profile_1",
        expected_revision=0,
        data=make_pdf(pages),
        filename="p.pdf",
        kind="resume",
    ).document
    page1 = service.list_blocks(doc.id, cursor=None, limit=2)
    assert [b.text for b in page1.items] == ["第1页 内容", "第2页 内容"]
    assert page1.next_cursor is not None
    page2 = service.list_blocks(doc.id, cursor=page1.next_cursor, limit=2)
    assert [b.text for b in page2.items] == ["第3页 内容", "第4页 内容"]
    page3 = service.list_blocks(doc.id, cursor=page2.next_cursor, limit=2)
    assert [b.text for b in page3.items] == ["第5页 内容"]
    assert page3.next_cursor is None
    with pytest.raises(ValueError):
        service.list_blocks(doc.id, cursor="not-a-cursor", limit=2)


def test_error_fields_are_contract_shaped():
    err = DocumentRejected("FILE_TOO_LARGE", "文件超过上限", retry_hint="reduce")
    names = {f.name for f in fields(err)}
    assert {"code", "message", "retry_hint"} <= names
    assert err.retry_hint == "reduce"


# ---------------- P-EXTRACT 分块抽取（流式修复同批落地） ----------------


class RecordingExtractGenerator:
    """返回逐字引文的真实 Workflow 生成器替身；记录每次调用的批次。"""

    def __init__(self, *, fail_on_call: int | None = None, claims_per_block: int = 1):
        self.calls: list[dict] = []
        self._fail_on_call = fail_on_call
        self._claims_per_block = claims_per_block

    async def generate(self, *, task, payload):
        self.calls.append(payload)
        if self._fail_on_call is not None and len(self.calls) == self._fail_on_call:
            raise ModelRequestTimeoutError("model request timed out")
        claims = []
        for block in payload["source_blocks"]:
            text = block["text"]
            for index in range(self._claims_per_block):
                quote = text[index * 3 : index * 3 + 15]
                if not quote.strip():
                    continue
                claims.append(
                    {
                        "text": quote,
                        "source_block_id": block["id"],
                        "exact_quote": quote,
                        "section": "other",
                    }
                )
        return AnalysisResult(
            content=json.dumps({"schema_version": "1.0.0", "claims": claims}),
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


def _live_service(tmp_path, generator, *, extract_call_limit: int):
    engine = make_engine(f"sqlite:///{tmp_path / 'live.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            Profile.__table__.insert().values(
                id="profile_1",
                workspace_id="local",
                display_name="合成候选人",
                synthetic=1,
                status="active",
                revision=0,
                created_at="2026-09-18T00:00:00Z",
                updated_at="2026-09-18T00:00:00Z",
            )
        )
    return DocumentService(
        engine=engine,
        repo=DocumentRepository(engine),
        limits=_limits(max_chars_per_extract_call=extract_call_limit),
        generator=generator,
        run_mode="live",
    )


def _sentences(count: int, length: int) -> str:
    """每句都以独特码位开头，保证跨批次的逐字引文互不重复。"""
    return "".join(
        chr(0x4E00 + index * (length - 1))
        + "".join(
            chr(0x4E00 + 0x1000 + index * length + step)
            for step in range(1, length - 1)
        )
        + "。"
        for index in range(count)
    )


def test_split_block_text_is_lossless_and_bounded():
    text = _sentences(5, 50)
    segments = _split_block_text(text, 100)
    assert "".join(segments) == text  # 无损：段拼接可还原，逐字子串不变量成立
    assert all(len(segment) <= 100 for segment in segments)
    assert len(segments) == 3  # 100/100/50

    giant = "字" * 250
    assert _split_block_text(giant, 100) == ["字" * 100, "字" * 100, "字" * 50]
    assert _split_block_text("   ", 100) == []


def test_build_extract_batches_packs_and_keeps_block_identity():
    blocks = [
        SourceBlockWrite(
            id="block_a",
            page_number=1,
            block_index=0,
            text="甲" * 40,
            origin="text_layer",
        ),
        SourceBlockWrite(
            id="block_b",
            page_number=2,
            block_index=0,
            text="乙" * 70,
            origin="text_layer",
        ),
    ]
    batches = _build_extract_batches(blocks, 100)
    # 40+70=110 > 100 → 两批；每段保留原块 ID 与页码，供逐字校验回查。
    assert [
        [(item["id"], item["page_number"], len(item["text"])) for item in batch]
        for batch in batches
    ] == [[("block_a", 1, 40)], [("block_b", 2, 70)]]


def test_long_document_extracts_in_bounded_batches(tmp_path):
    service = _live_service(
        tmp_path, RecordingExtractGenerator(), extract_call_limit=100
    )
    result = service.import_document(
        profile_id="profile_1",
        expected_revision=0,
        data=_sentences(7, 50).encode("utf-8"),
        filename="long.txt",
        kind="resume",
    )
    generator = service._generator
    assert len(generator.calls) == 4  # 350 字 → 100/100/100/50 四次真实调用
    for payload in generator.calls:
        batch_chars = sum(len(block["text"]) for block in payload["source_blocks"])
        assert 0 < batch_chars <= 100
    blocks = service.list_blocks(result.document.id, cursor=None, limit=20).items
    assert len(blocks) == 1
    stored = service  # 每条 Claim 的引文必须仍是入库块文本的逐字子串
    with stored.session() as session:
        from zhijue.adapters.db.models import Claim

        claims = session.query(Claim).all()
        assert len(claims) == 4
        for claim in claims:
            assert claim.text in blocks[0].text
    metadata = result.extraction_metadata
    assert metadata["workflow"] == "openjiuwen"
    assert metadata["model_calls"] == 4
    # 每次调用 usage 都齐全才聚合求和。
    assert metadata["usage"] == {
        "input_tokens": 40,
        "output_tokens": 20,
        "total_tokens": 60,
        "cost": None,
    }


def test_second_batch_failure_persists_nothing(tmp_path):
    generator = RecordingExtractGenerator(fail_on_call=2)
    service = _live_service(tmp_path, generator, extract_call_limit=100)
    with pytest.raises(UpstreamError) as raised:
        service.import_document(
            profile_id="profile_1",
            expected_revision=0,
            data=_sentences(7, 50).encode("utf-8"),
            filename="long.txt",
            kind="resume",
        )
    assert raised.value.code == "UPSTREAM_TIMEOUT"
    assert len(generator.calls) == 2
    with service.session() as session:
        assert session.query(Document).count() == 0


def test_merged_claims_over_fifty_rejects_all(tmp_path):
    generator = RecordingExtractGenerator(claims_per_block=9)
    service = _live_service(tmp_path, generator, extract_call_limit=50)
    with pytest.raises(UpstreamError) as raised:
        service.import_document(
            profile_id="profile_1",
            expected_revision=0,
            data=_sentences(6, 50).encode("utf-8"),
            filename="dense.txt",
            kind="resume",
        )
    # 6 批 × 9 条 = 54 > 50：全部拒绝，不静默截断。
    assert raised.value.code == "UPSTREAM_FAILED"
    assert "50 条上限" in raised.value.message
    assert len(generator.calls) == 6
    with service.session() as session:
        assert session.query(Document).count() == 0
