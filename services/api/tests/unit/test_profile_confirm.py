"""M1-03 测试：Claim 状态机、确认快照、Knowledge 激活与检索隔离。

分两层：
- unit：纯 domain（claims）+ fixture 级 ProfileService（无网络无模型）；
- integration_live 标记：真实 openJiuwen Knowledge 激活链（私密 env 才跑）。
"""

from __future__ import annotations

import pytest

from zhijue.domain.claims import (
    ClaimStatus,
    InvalidClaimTransition,
    ensure_transition,
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
