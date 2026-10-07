"""M1-03 测试：Claim 状态机、确认快照、Knowledge 激活与检索隔离。

分两层：
- unit：纯 domain（claims）+ fixture 级 ProfileService（无网络无模型）；
- integration_live 标记：真实 openJiuwen Knowledge 激活链（私密 env 才跑）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from zhijue.domain.claims import (
    ClaimStatus,
    InvalidClaimTransition,
    SourcePosition,
    ensure_transition,
    order_claims_for_reading,
    validate_exact_quote,
)

# ---------------- domain：纯规则 ----------------


def test_claim_lifecycle():
    assert (
        ensure_transition(ClaimStatus.PROPOSED, ClaimStatus.CONFIRMED)
        is ClaimStatus.CONFIRMED
    )
    assert (
        ensure_transition(ClaimStatus.PROPOSED, ClaimStatus.RETRACTED)
        is ClaimStatus.RETRACTED
    )
    assert (
        ensure_transition(ClaimStatus.CONFIRMED, ClaimStatus.RETRACTED)
        is ClaimStatus.RETRACTED
    )
    # confirmed 不能回到 proposed；retracted 是终态；disputed 保留冲突不下结论（docs/03 §4）
    with pytest.raises(InvalidClaimTransition):
        ensure_transition(ClaimStatus.CONFIRMED, ClaimStatus.PROPOSED)
    with pytest.raises(InvalidClaimTransition):
        ensure_transition(ClaimStatus.RETRACTED, ClaimStatus.CONFIRMED)
    assert (
        ensure_transition(ClaimStatus.DISPUTED, ClaimStatus.CONFIRMED)
        is ClaimStatus.CONFIRMED
    )


def test_exact_quote_must_be_substring_of_block():
    assert validate_exact_quote(
        "FreeRTOS Queue", "我们在 ESP32-S3 用了 FreeRTOS Queue 收发"
    )
    with pytest.raises(ValueError):
        validate_exact_quote("我们精通 FreeRTOS", "简历提到 FreeRTOS Queue")


@dataclass
class _Claim:
    id: str
    block_id: str | None
    quote: str = ""
    created_at: str = "2026-10-06T00:00:00Z"
    supersedes_id: str | None = None
    source_block_ids: list[str] = field(init=False)
    source_quotes: list[dict[str, str]] = field(init=False)

    def __post_init__(self) -> None:
        self.source_block_ids = [self.block_id] if self.block_id else []
        self.source_quotes = (
            [{"source_block_id": self.block_id, "exact_quote": self.quote}]
            if self.block_id
            else []
        )


_POSITIONS = {
    "b_page1_block0": SourcePosition(0, 1, 0, "张三 · 电子信息工程"),
    "b_page1_block2": SourcePosition(0, 1, 2, "负责 UART 接收；改用 DMA 循环接收"),
    "b_page2_block0": SourcePosition(0, 2, 0, "熟悉 FreeRTOS Queue"),
    "b_manual": SourcePosition(1, None, 0, "补充：做过 CAN 多节点"),
}


def test_reading_order_follows_material_not_random_ids():
    """同批抽取 created_at 相同，展示序必须是材料页→块→块内位置，而非随机 ID。"""
    claims = [
        _Claim("claim_a", "b_page2_block0", "FreeRTOS Queue"),
        _Claim("claim_b", "b_manual", "做过 CAN 多节点"),
        _Claim("claim_c", "b_page1_block2", "改用 DMA 循环接收"),
        _Claim("claim_d", "b_page1_block2", "负责 UART 接收"),
        _Claim("claim_e", "b_page1_block0", "张三"),
    ]
    ordered = order_claims_for_reading(claims, _POSITIONS)
    assert [claim.id for claim in ordered] == [
        "claim_e",
        "claim_d",
        "claim_c",
        "claim_a",
        "claim_b",
    ]


def test_correction_keeps_original_position_and_unknown_source_goes_last():
    claims = [
        _Claim(
            "claim_orphan", "b_deleted", "不存在的块", created_at="2026-10-06T00:00:00Z"
        ),
        _Claim("claim_rtos", "b_page2_block0", "FreeRTOS Queue"),
        _Claim(
            "claim_fix",
            "b_manual",
            "做过 CAN 多节点",
            created_at="2026-10-06T00:05:00Z",
            supersedes_id="claim_uart",
        ),
        _Claim("claim_uart", "b_page1_block2", "负责 UART 接收"),
        _Claim("claim_none", None),
    ]
    ordered = [claim.id for claim in order_claims_for_reading(claims, _POSITIONS)]
    # 更正沿用被更正事实的位置并紧随其后；无可解析来源的不猜位置，排最后。
    assert ordered == [
        "claim_uart",
        "claim_fix",
        "claim_rtos",
        "claim_none",
        "claim_orphan",
    ]


# ---------------- application：fixture 级（无 Knowledge live） ----------------


@pytest.fixture()
def profiles(tmp_path):
    from zhijue.adapters.db.engine import make_engine
    from zhijue.adapters.db.models import Base
    from zhijue.adapters.db.profiles import ProfileRepository
    from zhijue.application.profiles import ProfileService

    engine = make_engine(f"sqlite:///{tmp_path / 'p.db'}")
    Base.metadata.create_all(engine)
    repo = ProfileRepository(engine)
    service = ProfileService(repo=repo, knowledge=None)
    profile = service.create_profile(display_name="合成甲", synthetic=True)
    return service, profile


def test_add_facts_creates_proposed_claims_with_user_blocks(profiles):
    service, profile = profiles
    updated = service.add_facts(
        profile_id=profile.id,
        expected_revision=0,
        items=[
            {"section": "project", "text": "我用 FreeRTOS Queue 做任务间通信"},
            {"section": "skill", "text": "熟悉 C 语言与 STM32 HAL"},
        ],
    )
    assert updated.revision == 1
    claims = service.list_claims(profile.id)
    assert len(claims) == 2
    assert all(c.status == ClaimStatus.PROPOSED for c in claims)
    for claim in claims:
        assert claim.source_block_ids and claim.source_quotes
        block_text = claim.source_quotes[0]["text_context"]
        assert claim.source_quotes[0]["exact_quote"] in block_text


def test_stale_expected_revision_conflicts(profiles):
    service, profile = profiles
    service.add_facts(
        profile.id, expected_revision=0, items=[{"section": "other", "text": "x"}]
    )
    with pytest.raises(ValueError) as exc:
        service.add_facts(
            profile.id, expected_revision=0, items=[{"section": "other", "text": "y"}]
        )
    assert "REVISION_CONFLICT" in str(exc.value) or "revision" in str(exc.value).lower()


def test_confirm_creates_immutable_snapshot(profiles):
    service, profile = profiles
    service.add_facts(
        profile.id,
        expected_revision=0,
        items=[{"section": "project", "text": "负责 UART 错帧排查"}],
    )
    claims = service.list_claims(profile.id)
    decisions = [
        {"claim_id": claims[0].id, "action": "accept"},
    ]
    updated = service.confirm(profile.id, expected_revision=1, decisions=decisions)
    assert updated.revision == 2
    snapshot = service.get_snapshot(updated.latest_snapshot_id)
    assert snapshot.confirmed_claim_ids == [claims[0].id]
    assert snapshot.revision == 2
    # 快照一经生成不可修改（仓储没有 UPDATE snapshot 方法即为结构保证）。
    with pytest.raises(AttributeError):
        service.update_snapshot(snapshot.id, confirmed_claim_ids=[])


def test_reject_and_correct_do_not_enter_snapshot(profiles):
    service, profile = profiles
    service.add_facts(
        profile.id,
        expected_revision=0,
        items=[
            {"section": "project", "text": "我主导了整个 CAN 网关项目"},
            {"section": "project", "text": "参与了串口调试工具编写"},
        ],
    )
    a, b = service.list_claims(profile.id)
    updated = service.confirm(
        profile.id,
        expected_revision=1,
        decisions=[
            {"claim_id": a.id, "action": "reject"},
            {
                "claim_id": b.id,
                "action": "correct",
                "corrected_text": "我负责串口调试工具的接收解析模块",
            },
        ],
    )
    snapshot = service.get_snapshot(updated.latest_snapshot_id)
    fresh = service.list_claims(profile.id)
    corrected = [c for c in fresh if c.status == ClaimStatus.CONFIRMED]
    assert len(corrected) == 1
    assert corrected[0].text == "我负责串口调试工具的接收解析模块"
    assert corrected[0].supersedes_id == b.id  # 更正是新行，不篡改原块（docs/03 §5.3）
    assert corrected[0].source_quotes[0]["origin"] == "user_input"
    assert a.id not in snapshot.confirmed_claim_ids
    assert corrected[0].id in snapshot.confirmed_claim_ids


def test_correct_requires_text_and_rejects_unknown_claim(profiles):
    service, profile = profiles
    service.add_facts(
        profile.id, expected_revision=0, items=[{"section": "other", "text": "z"}]
    )
    claim = service.list_claims(profile.id)[0]
    with pytest.raises(ValueError):
        service.confirm(
            profile.id,
            expected_revision=1,
            decisions=[{"claim_id": claim.id, "action": "correct"}],
        )
    with pytest.raises(ValueError):
        service.confirm(
            profile.id,
            expected_revision=1,
            decisions=[{"claim_id": "claim_ghost", "action": "accept"}],
        )


def test_facts_validation_bounds(profiles):
    service, profile = profiles
    with pytest.raises(ValueError):  # 超过 50 条
        service.add_facts(
            profile.id,
            expected_revision=0,
            items=[{"section": "other", "text": f"第{i}条"} for i in range(51)],
        )
    with pytest.raises(ValueError):  # 空文本
        service.add_facts(
            profile.id, expected_revision=0, items=[{"section": "other", "text": " "}]
        )
    with pytest.raises(ValueError):  # 非法 section
        service.add_facts(
            profile.id, expected_revision=0, items=[{"section": "magic", "text": "x"}]
        )
    # 校验失败不推进 revision
    assert service.get_profile(profile.id).revision == 0


def test_profile_detail_keeps_revision_claims_and_documents_in_one_snapshot(tmp_path):
    from sqlalchemy import event

    from zhijue.adapters.db.engine import make_engine
    from zhijue.adapters.db.models import Base
    from zhijue.adapters.db.profiles import ProfileRepository
    from zhijue.application.profiles import ProfileService

    engine = make_engine(f"sqlite:///{tmp_path / 'consistent.db'}", wal=True)
    Base.metadata.create_all(engine)
    service = ProfileService(repo=ProfileRepository(engine))
    profile = service.create_profile(display_name="一致性测试")
    wrote = False

    def concurrent_fact_commit(_conn, _cursor, statement, _params, _context, _many):
        nonlocal wrote
        if wrote or "FROM profile \n" not in statement:
            return
        wrote = True
        # Commit through another connection immediately after the read of revision.
        # WAL permits that writer while the first connection holds its read snapshot.
        service.add_facts(
            profile.id,
            expected_revision=0,
            items=[{"section": "project", "text": "负责 UART 错帧排查"}],
        )

    event.listen(engine, "after_cursor_execute", concurrent_fact_commit)
    try:
        view, claims, documents = service.get_detail(profile.id)
    finally:
        event.remove(engine, "after_cursor_execute", concurrent_fact_commit)
    assert wrote
    assert view.revision == 0
    assert claims == []
    assert documents == []

    current, claims, documents = service.get_detail(profile.id)
    assert current.revision == 1
    assert len(claims) == len(documents) == 1
    confirmed = service.confirm(
        profile.id,
        expected_revision=current.revision,
        decisions=[{"claim_id": claims[0].id, "action": "accept"}],
    )
    assert confirmed.revision == 2
    engine.dispose()


def test_profile_detail_missing_profile_preserves_not_found_contract(profiles):
    service, _profile = profiles
    with pytest.raises(ValueError, match="RESOURCE_NOT_FOUND"):
        service.get_detail("profile_missing")


def test_profile_detail_returns_claims_in_resume_reading_order(profiles):
    """ProfileView 的 proposed/confirmed 列表按材料阅读顺序，不随 ID 随机排列。"""
    from sqlalchemy.orm import Session

    from zhijue.adapters.db.models import Claim, Document, SourceBlock

    service, profile = profiles
    engine = service._repo._engine
    created = "2026-10-06T00:00:00Z"
    blocks = [
        ("block_z_first", 1, 0, "千早 · 嵌入式软件开发实习生"),
        ("block_m_second", 1, 1, "负责 STM32 串口接收；改用 DMA 循环接收"),
        ("block_a_third", 2, 0, "熟悉 FreeRTOS Queue"),
    ]
    # 同一批 created_at；ID 字典序与阅读顺序相反，旧实现会把第三页排第一。
    claims = [
        ("claim_0", "block_a_third", "熟悉 FreeRTOS Queue"),
        ("claim_1", "block_m_second", "改用 DMA 循环接收"),
        ("claim_2", "block_m_second", "负责 STM32 串口接收"),
        ("claim_3", "block_z_first", "嵌入式软件开发实习生"),
    ]
    with Session(engine) as session, session.begin():
        session.add(
            Document(
                id="document_resume",
                profile_id=profile.id,
                kind="resume",
                filename_display="synthetic.pdf",
                sha256="0" * 64,
                mime="application/pdf",
                size=1,
                page_count=2,
                extract_status="parsed",
                index_status="pending",
                warnings=[],
                created_at=created,
                updated_at=created,
            )
        )
        session.flush()
        for block_id, page, index, text in blocks:
            session.add(
                SourceBlock(
                    id=block_id,
                    document_id="document_resume",
                    page_number=page,
                    block_index=index,
                    text=text,
                    text_hash="0" * 64,
                    origin="text_layer",
                )
            )
        for claim_id, block_id, quote in claims:
            session.add(
                Claim(
                    id=claim_id,
                    profile_id=profile.id,
                    text=quote,
                    source_block_ids=[block_id],
                    source_quotes=[
                        {
                            "source_block_id": block_id,
                            "exact_quote": quote,
                            "section": "project",
                        }
                    ],
                    status="proposed",
                    supersedes_id=None,
                    created_at=created,
                    updated_at=created,
                )
            )

    _view, ordered, _documents = service.get_detail(profile.id)
    assert [claim.id for claim in ordered] == [
        "claim_3",
        "claim_2",
        "claim_1",
        "claim_0",
    ]
