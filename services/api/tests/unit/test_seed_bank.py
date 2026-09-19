"""M2-01 种子库测试：契约加载、live 门槛、可追溯性与受控失败。

断言的是业务可观察契约（哪些种子可用、缺来源会不会放行），
不是 JSON 字段搬运。
"""

from __future__ import annotations

import json

import pytest

from zhijue.application.seed_bank import REVIEW_RANK, SeedBankError, load_seed_bank


@pytest.fixture()
def seeds_dir():
    from pathlib import Path

    here = Path(__file__).resolve()
    for candidate in here.parents:
        path = candidate / "data" / "seeds"
        if path.is_dir():
            return path
    raise RuntimeError("未找到 data/seeds")


def test_loads_all_seeds_and_reports_competencies(seeds_dir):
    bank = load_seed_bank(seeds_dir)
    assert len(bank) == 6
    assert len(bank.competency_ids()) >= 5
    for seed in bank.seeds:
        assert seed.review_status == "approved"
        assert seed.follow_up_strategy["max_followups"] == 1  # P0 上限
        assert seed.rubric, "每条种子必须有 rubric"
        assert seed.intent and seed.stem
    assert len(load_seed_bank(seeds_dir, live_only=True)) == 6


def test_technical_review_seeds_never_reach_live(tmp_path, seeds_dir):
    for path in seeds_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["review_status"] = "technical_review"
        payload["review_record_id"] = None
        payload["review_levels"]["level2"] = {
            "status": "pending",
            "reviewer_role": "owner",
            "checked": ["fixture pending owner decision"],
            "at": None,
        }
        (tmp_path / path.name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    bank = load_seed_bank(tmp_path)
    assert bank.live_allowed_review_status == "approved"
    assert bank.live_eligible() == ()
    with pytest.raises(SeedBankError, match="需要至少 approved"):
        load_seed_bank(tmp_path, live_only=True)


def test_draft_seeds_never_reach_live(tmp_path, seeds_dir):
    """live 门槛是真实的：把种子降为 draft 后 live 加载必须失败。"""
    for path in seeds_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["review_status"] = "draft"
        payload["review_levels"]["level1"]["status"] = "pending"
        payload["review_record_id"] = None
        payload["review_levels"]["level2"]["status"] = "pending"
        payload["review_levels"]["level2"]["at"] = None
        (tmp_path / path.name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    with pytest.raises(SeedBankError, match="live 门槛"):
        load_seed_bank(tmp_path, live_only=True)
    # fixture 模式仍可加载（draft 只用于流程测试）
    assert len(load_seed_bank(tmp_path)) == 6


def test_live_load_returns_only_approved_seeds(tmp_path, seeds_dir):
    payload = json.loads(
        (seeds_dir / "seed_embedded_interrupt_priority.json").read_text(
            encoding="utf-8"
        )
    )
    payload["review_status"] = "approved"
    payload["review_record_id"] = "review_owner_demo"
    payload["review_levels"]["level2"] = {
        "status": "passed",
        "reviewer_role": "owner",
        "checked": ["fixture owner decision"],
        "at": "2026-09-19",
    }
    (tmp_path / "approved.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    technical = json.loads(
        (seeds_dir / "seed_embedded_uart_dma_debug.json").read_text(encoding="utf-8")
    )
    technical["review_status"] = "technical_review"
    technical["review_record_id"] = None
    technical["review_levels"]["level2"] = {
        "status": "pending",
        "reviewer_role": "owner",
        "checked": ["fixture pending owner decision"],
        "at": None,
    }
    (tmp_path / "technical.json").write_text(
        json.dumps(technical, ensure_ascii=False), encoding="utf-8"
    )

    bank = load_seed_bank(tmp_path, live_only=True)

    assert [seed.id for seed in bank.seeds] == ["seed_embedded_interrupt_priority"]


def test_technical_reference_points_always_carry_sources(seeds_dir):
    bank = load_seed_bank(seeds_dir)
    for seed in bank.seeds:
        assert seed.technical_points, f"{seed.id} 缺少技术参考要点"
        for point in seed.technical_points:
            assert point["reference_ids"], (
                f"{seed.id}:{point['point_id']} 技术要点没有来源"
            )


@pytest.mark.parametrize(
    "seed_id",
    [
        "seed_embedded_uart_dma_debug",
        "seed_embedded_spi_i2c_selection",
    ],
)
def test_demo_peripheral_seeds_cover_f4_g4_and_h7_sources(seeds_dir, seed_id):
    """主演示含 F407/G431；外设事实不能继续只靠 H7 手册。"""
    required_sources = {
        "rm0090_stm32f4",
        "rm0440_stm32g4",
        "rm0433_stm32h7",
    }
    seed = load_seed_bank(seeds_dir).get(seed_id)
    assert required_sources <= set(seed.reference_ids)
    for point in seed.technical_points:
        assert required_sources <= set(point["reference_ids"]), (
            f"{seed_id}:{point['point_id']} 没有覆盖 F4/G4/H7 平台来源"
        )


def test_red_flags_never_imply_deduction(seeds_dir):
    bank = load_seed_bank(seeds_dir)
    for seed in bank.seeds:
        for flag in seed.red_flags:
            assert flag["requires_followup"] is True


def test_invalid_seed_fails_loudly(tmp_path, seeds_dir):
    payload = json.loads(
        (seeds_dir / "seed_embedded_interrupt_priority.json").read_text(
            encoding="utf-8"
        )
    )
    payload["reference_points"][0]["reference_ids"] = []
    (tmp_path / "bad.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(SeedBankError, match="不符合 seed 契约"):
        load_seed_bank(tmp_path)


def test_empty_and_missing_directory_fail_loudly(tmp_path):
    with pytest.raises(SeedBankError, match="为空"):
        load_seed_bank(tmp_path)
    with pytest.raises(SeedBankError, match="不存在"):
        load_seed_bank(tmp_path / "nope")


def test_version_fingerprint_changes_with_content(tmp_path, seeds_dir):
    bank = load_seed_bank(seeds_dir)
    original = bank.version_fingerprint()
    payload = json.loads(
        (seeds_dir / "seed_embedded_interrupt_priority.json").read_text(
            encoding="utf-8"
        )
    )
    payload["version"] = "99.0.0"
    (tmp_path / "seed_embedded_interrupt_priority.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert load_seed_bank(tmp_path).version_fingerprint() != original


def test_review_rank_keeps_two_level_semantics():
    assert (
        REVIEW_RANK["draft"] < REVIEW_RANK["technical_review"] < REVIEW_RANK["approved"]
    )
    assert REVIEW_RANK["rejected"] == REVIEW_RANK["draft"] == 0
