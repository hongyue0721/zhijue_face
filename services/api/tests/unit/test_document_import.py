"""M1-02 测试：PDF/文本导入、SourceBlock 定位与受控失败（T01—T04）。

全部使用合成 PDF（tests/fixtures_pdf.py）。断言业务可观察契约：
分页块、页码/块号、text_hash、requires_text 判定、失败原因码，
不是 pypdf 内部细节。
"""

from __future__ import annotations

import hashlib
from dataclasses import fields

import pytest
from fixtures_pdf import encrypt_pdf, make_pdf

from zhijue.adapters.db.documents import DocumentRepository
from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import Base, Document, Profile
from zhijue.adapters.pdf import extract_pdf_pages, sniff_kind
from zhijue.domain.errors import DocumentRejected
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
    from zhijue.application.documents import DocumentService

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
