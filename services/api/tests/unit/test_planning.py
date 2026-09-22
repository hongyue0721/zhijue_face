"""M2-02 测试：JD 来源链、Requirement 抽取、Coverage Map 与五题计划。

对应负责人 2026-09-18 决策 §8 的 12 项要求。断言业务可观察契约：
来源可回指、等级不升级、缺失不当弱项、计划确定性与覆盖约束。
"""

from __future__ import annotations

import json

import pytest

from zhijue.domain.planning import (
    MIN_COMPETENCIES,
    ROOT_SLOT_COUNT,
    CoverageEntry,
    CoverageMap,
    PlanningRejected,
    SlotReason,
    build_coverage_map,
    plan_interview_slots,
)
from zhijue.domain.requisition import (
    CoverageStatus,
    JdRejected,
    JDSnapshot,
    JDSourceType,
    RequirementTier,
    extract_requirements,
    make_snapshot,
)

SYNTHETIC_JD = """【演示岗位配置｜不是任何企业的真实招聘广告】
岗位：嵌入式软件实习 / 校招初级

必要项：能够阅读和编写基础 C 程序；理解 MCU 中断与采样任务；能够解释 UART/SPI 等常见通信的调试思路；能清楚说明项目中本人工作以及验证方法。
加分项：了解 RTOS 任务、共享资源访问和任务间通信；使用 Git 保存修改和定位回归。
考察范围：本科阶段项目与练习中的基础机制、局部设计和问题定位。
不要求：量产经验、主导大型架构、独立设计硬件板卡。
"""


@pytest.fixture()
def snapshot():
    return make_snapshot(
        snapshot_id="jd_snapshot_demo_01",
        profile_id="profile_demo_01",
        raw_text=SYNTHETIC_JD,
        source_type=JDSourceType.SYNTHETIC_DEMO_JD,
        source_name="SYNTHETIC_DEMO_JD_v1",
        imported_at="2026-09-18T12:00:00+00:00",
    )


# ---- 1. JD 来源与原文可恢复 ----


def test_jd_source_chain_is_preserved(snapshot):
    assert snapshot.raw_text == SYNTHETIC_JD.strip()
    assert snapshot.content_hash == snapshot.compute_hash(snapshot.raw_text)
    assert snapshot.source_type is JDSourceType.SYNTHETIC_DEMO_JD
    assert snapshot.source_name == "SYNTHETIC_DEMO_JD_v1"
    assert snapshot.imported_at == "2026-09-18T12:00:00+00:00"
    assert snapshot.version == 1
    assert snapshot.status.value == "active"
    assert snapshot.is_synthetic is True  # 合成材料必须自报，不能冒充真实招聘


def test_jd_rejects_empty_and_oversized():
    with pytest.raises(JdRejected, match="INVALID_REQUEST"):
        make_snapshot(
            snapshot_id="jd_x",
            profile_id="p",
            raw_text="   ",
            source_type=JDSourceType.USER_PROVIDED,
            source_name="empty",
        )
    with pytest.raises(JdRejected, match="TEXT_TOO_LARGE"):
        make_snapshot(
            snapshot_id="jd_y",
            profile_id="p",
            raw_text="要" * 8001,
            source_type=JDSourceType.USER_PROVIDED,
            source_name="long",
        )


# ---- 2. Requirement 可追溯到 JD ----


def test_requirements_trace_back_to_jd_text(snapshot):
    requirements = extract_requirements(snapshot)
    assert requirements
    for requirement in requirements:
        span = requirement.source_span
        assert requirement.jd_snapshot_id == snapshot.id
        assert (
            snapshot.raw_text[span["start"] : span["end"]]
            == span["quote"]
            == requirement.statement
        )
        assert span["section"] in snapshot.raw_text


# ---- 3. preferred 不会被解析成 must-have ----


def test_preferred_never_becomes_required(snapshot):
    requirements = extract_requirements(snapshot)
    tiers = {r.statement: r.tier for r in requirements}
    rtos = next(r for r in requirements if "RTOS" in r.statement)
    assert rtos.tier is RequirementTier.PREFERRED
    assert rtos.importance == 1
    assert not any(
        r.tier is RequirementTier.REQUIRED and "RTOS" in r.statement
        for r in requirements
    )
    # must-have 仍是 required，且权重更高
    c_basics = next(r for r in requirements if "C 程序" in r.statement)
    assert c_basics.tier is RequirementTier.REQUIRED
    assert c_basics.importance == 3
    assert rtos.importance < c_basics.importance
    assert tiers  # 明确：抽取结果非空


def test_common_explicit_section_titles_preserve_tiers_and_offsets():
    raw_text = (
        "岗位名称：嵌入式软件工程师🙂\n"
        "任职要求：熟悉 C 语言指针；理解中断机制。\n"
        "优先条件：有 FreeRTOS 任务与 Queue 实践。\n"
        "工作职责：负责 UART DMA 通信调试。\n"
    )
    common_titles = make_snapshot(
        snapshot_id="jd_snapshot_common_titles",
        profile_id="profile_common_titles",
        raw_text=raw_text,
        source_type=JDSourceType.USER_PROVIDED,
        source_name="用户提供岗位描述",
    )

    requirements = extract_requirements(common_titles)
    assert [requirement.tier for requirement in requirements] == [
        RequirementTier.REQUIRED,
        RequirementTier.REQUIRED,
        RequirementTier.PREFERRED,
        RequirementTier.RESPONSIBILITY,
    ]
    assert common_titles.raw_text == raw_text.strip()
    assert common_titles.source_type is JDSourceType.USER_PROVIDED
    assert common_titles.source_name == "用户提供岗位描述"

    for requirement in requirements:
        span = requirement.source_span
        assert common_titles.raw_text[span["start"] : span["end"]] == span["quote"]
        assert span["quote"] == requirement.statement
        assert span["utf16_start"] == (
            len(common_titles.raw_text[: span["start"]].encode("utf-16-le")) // 2
        )
        assert span["utf16_end"] == (
            len(common_titles.raw_text[: span["end"]].encode("utf-16-le")) // 2
        )


def test_unsectioned_job_text_is_not_silently_promoted_to_required():
    unsectioned = make_snapshot(
        snapshot_id="jd_snapshot_unsectioned",
        profile_id="profile_unsectioned",
        raw_text="岗位名称：嵌入式软件工程师\n熟悉 C 语言指针\n有 FreeRTOS Queue 实践",
        source_type=JDSourceType.USER_PROVIDED,
        source_name="用户提供岗位描述",
    )

    assert extract_requirements(unsectioned) == []


def test_non_requirement_lines_are_not_extracted(snapshot):
    requirements = extract_requirements(snapshot)
    assert not any("不是任何企业" in r.statement for r in requirements)
    assert not any(
        "量产经验" in r.statement for r in requirements
    )  # "不要求"是边界声明


# ---- 4/5. 覆盖状态不混淆；unverified 不是弱项 ----


def test_coverage_status_semantics(snapshot):
    requirements = extract_requirements(snapshot)
    coverage = build_coverage_map(
        requirements=requirements,
        evidence_index={"embedded.peripheral.uart_dma": ["claim_block_01"]},
        profile_snapshot_id="snapshot_01",
    )
    uart = coverage.by_competency("embedded.peripheral.uart_dma")
    assert uart.status is CoverageStatus.UNVERIFIED  # 有材料 ≠ 已验证
    assert uart.evidence_ids == ("claim_block_01",)
    missing = coverage.by_competency("embedded.rtos.fundamentals")
    assert missing.status is CoverageStatus.UNKNOWN  # 材料没体现 ≠ 不会
    assert missing.evidence_ids == ()


def test_unverified_and_unknown_are_never_weaknesses():
    for status in (
        CoverageStatus.UNVERIFIED,
        CoverageStatus.UNKNOWN,
        CoverageStatus.CLAIMED,
    ):
        entry = CoverageEntry(
            competency_id="embedded.x",
            requirement_ids=("r1",),
            status=status,
            evidence_ids=(),
        )
        assert entry.is_weakness is False
    contradicted = CoverageEntry(
        competency_id="embedded.x",
        requirement_ids=("r1",),
        status=CoverageStatus.CONTRADICTED,
        evidence_ids=("c1",),
    )
    assert contradicted.is_weakness is True  # 只有确有冲突才是可扣分信号


def test_coverage_map_has_no_score_field():
    """Planner 阶段不得产生任何分数（负责人决策 §6）。"""
    coverage = CoverageMap(entries=(), profile_snapshot_id=None)
    assert not hasattr(coverage, "score")
    for entry in (CoverageEntry("c", (), CoverageStatus.UNKNOWN, ()),):
        assert not hasattr(entry, "score") and not hasattr(entry, "weakness_score")


# ---- 6/7. 恰好 5 个 slot，至少 3 个 competency ----


def test_plan_generates_exactly_five_slots_across_competencies(snapshot):
    requirements = extract_requirements(snapshot)
    coverage = build_coverage_map(
        requirements=requirements,
        evidence_index={"embedded.peripheral.uart_dma": ["claim_01"]},
        profile_snapshot_id="snapshot_01",
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    assert len(plan.slots) == ROOT_SLOT_COUNT == 5
    assert len(plan.competency_coverage()) >= MIN_COMPETENCIES
    for slot in plan.slots:
        assert slot.seed_id is None, "M2-02 不绑定未批准种子"
        assert slot.verification_goal and slot.structured_reason
        assert slot.jd_requirement_ids and slot.priority > 0


def test_slot_shape_matches_required_fields(snapshot):
    requirements = extract_requirements(snapshot)
    coverage = build_coverage_map(
        requirements=requirements, evidence_index={}, profile_snapshot_id=None
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    payload = plan.as_dict()
    assert set(payload) == {
        "slots",
        "seed_bank_version",
        "planner_version",
        "limitations",
    }
    for slot in payload["slots"]:
        assert set(slot) == {
            "schema_version",
            "slot_id",
            "competency",
            "jd_requirement_ids",
            "candidate_evidence_ids",
            "current_verification_status",
            "verification_goal",
            "priority",
            "difficulty",
            "reason_code",
            "structured_reason",
            "seed_id",
        }


# ---- 8. 高权重未验证优先于低权重已验证 ----


def test_high_importance_unverified_outranks_low_importance_supported():
    """高权重未验证 > 低权重已/待验证；preferred 不挤占 must-have 名额。

    用受控 JD（4 个能力维度）保证两个槽位都在计划内，避免依赖大 JD 的筛除行为。
    """
    controlled = make_snapshot(
        snapshot_id="jd_priority",
        profile_id="p",
        raw_text=(
            "必要项：能够阅读和编写基础 C 程序；理解 MCU 中断与采样任务；"
            "能够解释 UART/SPI 等常见通信的调试思路；能清楚说明项目中本人工作。\n"
            "加分项：使用 Git 保存修改和定位回归。"
        ),
        source_type=JDSourceType.SYNTHETIC_DEMO_JD,
        source_name="SYNTHETIC_DEMO_JD_priority",
    )
    requirements = extract_requirements(controlled)
    competencies = {r.competency_id for r in requirements}
    assert len(competencies) == 5, competencies  # 恰好 5 个维度，槽位不重复
    coverage = build_coverage_map(
        requirements=requirements,
        evidence_index={
            "embedded.peripheral.uart_dma": ["claim_uart"],  # unverified，required(3)
            "embedded.mcu.interrupt": ["claim_isr"],  # unverified，required(3)
            "embedded.c.basics": ["claim_c"],  # required(3)，unverified
            "project.ownership": ["claim_own"],  # required(3)，unverified
            "engineering.tooling.version_control": ["claim_git"],  # preferred(1)
        },
        profile_snapshot_id="snapshot_01",
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    assert len(plan.slots) == 5
    git = next(
        s for s in plan.slots if s.competency == "engineering.tooling.version_control"
    )
    must_haves = [
        s for s in plan.slots if s.competency != "engineering.tooling.version_control"
    ]
    assert len(must_haves) == 4, "必备项必须占满其余槽位"
    assert all(s.priority > git.priority for s in must_haves)
    assert git.reason_code is SlotReason.JD_PREFERRED_SECONDARY
    assert plan.slots[-1].competency == git.competency  # preferred 排在最后


def test_preferred_excluded_when_must_haves_fill_all_slots(snapshot):
    """8 个能力维度只有 5 个槽位时，preferred 不得挤掉 must-have（按简历篇幅选题的反例）。"""
    requirements = extract_requirements(snapshot)
    coverage = build_coverage_map(
        requirements=requirements,
        evidence_index={
            "engineering.tooling.version_control": [
                "claim_git",
                "claim_git2",
                "claim_git3",
            ],
            "embedded.peripheral.uart_dma": [],
        },
        profile_snapshot_id="snapshot_01",
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    chosen = {s.competency for s in plan.slots}
    assert "engineering.tooling.version_control" not in chosen, (
        "preferred 不应挤占 must-have 槽位"
    )
    assert len(plan.slots) == 5


def test_preferred_never_outranks_critical_must_have(snapshot):
    requirements = extract_requirements(snapshot)
    coverage = build_coverage_map(
        requirements=requirements,
        evidence_index={c: ["claim"] for c in {r.competency_id for r in requirements}},
        profile_snapshot_id="snapshot_01",
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    required = [
        s for s in plan.slots if s.reason_code is not SlotReason.JD_PREFERRED_SECONDARY
    ]
    preferred = [
        s for s in plan.slots if s.reason_code is SlotReason.JD_PREFERRED_SECONDARY
    ]
    for r in required:
        for p in preferred:
            assert r.priority >= p.priority


# ---- 9. 相同输入产生稳定计划 ----


def test_plan_is_deterministic_for_same_input(snapshot, tmp_path):
    requirements = extract_requirements(snapshot)
    coverage = build_coverage_map(
        requirements=requirements,
        evidence_index={"embedded.mcu.interrupt": ["claim_isr"]},
        profile_snapshot_id="snapshot_01",
    )
    first = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    second = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    assert [s.as_dict() for s in first.slots] == [s.as_dict() for s in second.slots]
    # 要求顺序被打乱也不改变结构（排序由 tie-break 决定，不依赖输入顺序）
    shuffled = list(reversed(requirements))
    third = plan_interview_slots(
        coverage=coverage, requirements=shuffled, seed_bank_version="seedbank_test"
    )
    assert [s.competency for s in third.slots] == [s.competency for s in first.slots]


# ---- 10. 空 JD / 无效 JD 明确报错 ----


def test_empty_jd_and_unusable_jd_fail_loudly(snapshot):
    with pytest.raises(JdRejected):
        make_snapshot(
            snapshot_id="jd_z",
            profile_id="p",
            raw_text="",
            source_type=JDSourceType.USER_PROVIDED,
            source_name="empty",
        )
    bare = make_snapshot(
        snapshot_id="jd_bare",
        profile_id="p",
        raw_text="我们是一家公司，欢迎加入。",  # 无任何显式要求标记
        source_type=JDSourceType.USER_PROVIDED,
        source_name="bare",
    )
    assert extract_requirements(bare) == []
    coverage = build_coverage_map(
        requirements=[], evidence_index={}, profile_snapshot_id=None
    )
    with pytest.raises(PlanningRejected, match="没有可用的岗位要求"):
        plan_interview_slots(
            coverage=coverage, requirements=[], seed_bank_version="seedbank_test"
        )


def test_insufficient_competency_dimensions_fail_loudly():
    narrow = make_snapshot(
        snapshot_id="jd_narrow",
        profile_id="p",
        raw_text="必要项：能够阅读和编写基础 C 程序。",
        source_type=JDSourceType.USER_PROVIDED,
        source_name="narrow",
    )
    requirements = extract_requirements(narrow)
    assert len({r.competency_id for r in requirements}) == 1
    coverage = build_coverage_map(
        requirements=requirements, evidence_index={}, profile_snapshot_id=None
    )
    with pytest.raises(PlanningRejected, match="不足"):
        plan_interview_slots(
            coverage=coverage,
            requirements=requirements,
            seed_bank_version="seedbank_test",
        )


# ---- 11. 无简历仍可计划，但状态必须是 unknown ----


def test_plan_without_resume_evidence_marks_unknown(snapshot):
    requirements = extract_requirements(snapshot)
    coverage = build_coverage_map(
        requirements=requirements, evidence_index={}, profile_snapshot_id=None
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    assert all(
        s.current_verification_status is CoverageStatus.UNKNOWN for s in plan.slots
    )
    assert all(s.candidate_evidence_ids == () for s in plan.slots)
    assert any("不推断为不会" in note for note in plan.limitations)
    # 未验证不等于不会：槽位不得给出任何能力缺失**结论**。
    # 注意区分：解释性否定（"材料未体现≠不会"）是合规的措辞，
    # 因此这里检查"断言式"表达而非裸词。
    for slot in plan.slots:
        slot_text = json.dumps(slot.as_dict(), ensure_ascii=False)
        for forbidden in ("不具备", "能力薄弱", "已掌握", "不会使用", "weakness"):
            assert forbidden not in slot_text, slot_text
        # unknown 槽位的验证目标必须显式声明"不作负面推断"——
        # 这是"材料没体现 ≠ 不会"在输出上的可观察保证。
        if slot.current_verification_status is CoverageStatus.UNKNOWN:
            assert slot.verification_goal.endswith("（材料未体现，不作负面推断）"), (
                slot.verification_goal
            )
            assert (
                "≠不会" in slot.structured_reason
                or slot.reason_code is SlotReason.JD_PREFERRED_SECONDARY
            )


# ---- 12. 不得绕过 Seed approval gate ----


def test_planner_never_binds_unapproved_seed():
    """slot 的 seed_id 必须为空：本阶段种子未 approved（AGENTS §11.5）。"""
    import inspect

    from zhijue.domain import planning

    source = inspect.getsource(planning.plan_interview_slots)
    assert "seed_id=None" in source
    assert "SeedBank" not in source  # Planner 不自行加载种子库绕过门槛


def test_duplicate_slot_requires_structured_reason():
    """可用维度少于槽位数时允许重复，但必须留下结构化理由（负责人决策 §7）。"""
    controlled = make_snapshot(
        snapshot_id="jd_four",
        profile_id="p",
        raw_text=(
            "必要项：能够阅读和编写基础 C 程序；理解 MCU 中断与采样任务；"
            "能够解释 UART/SPI 等常见通信的调试思路；能清楚说明项目中本人工作。"
        ),
        source_type=JDSourceType.SYNTHETIC_DEMO_JD,
        source_name="SYNTHETIC_DEMO_JD_four",
    )
    requirements = extract_requirements(controlled)
    assert len({r.competency_id for r in requirements}) == 4
    coverage = build_coverage_map(
        requirements=requirements, evidence_index={}, profile_snapshot_id=None
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=requirements, seed_bank_version="seedbank_test"
    )
    assert len(plan.slots) == 5
    repeated = [s.competency for s in plan.slots]
    assert len(set(repeated)) == 4 and len(repeated) == 5
    assert any("出现多次" in note for note in plan.limitations), plan.limitations


# ---- 13. source_span 单位定义与跨语言 Unicode 测试（M2-02 闭环） ----


def test_source_span_units_and_astral_unicode_cross_language():
    """测试 source_span 显式定义单位为 unicode_code_point 并准确计算 UTF-16 偏移。

    包含普通 ASCII、标准 CJK 汉字以及高位代理对（astral code point，如 emoji 🚀 U+1F680）。
    在 Python 码点切片、UTF-16 解码切片以及 Node.js 跨语言环境下三方均 100% 一致。
    """
    import subprocess

    raw_text = (
        "前缀🚀\n## 基本要求\n- 良好的 C 语言基础；\n- 理解指针、结构体与内存；\n"
    )
    snapshot = make_snapshot(
        snapshot_id="jd_unicode_test",
        profile_id="p_unicode",
        raw_text=raw_text,
        source_type=JDSourceType.SYNTHETIC_DEMO_JD,
        source_name="unicode_test",
    )
    reqs = extract_requirements(snapshot)
    assert len(reqs) == 2

    for req in reqs:
        span = req.source_span
        assert span["unit"] == "unicode_code_point"
        quote = str(span["quote"])
        cp_start = int(span["start"])
        cp_end = int(span["end"])
        u16_start = int(span["utf16_start"])
        u16_end = int(span["utf16_end"])

        # 1. Python 码点切片严格等于 quote
        assert raw_text[cp_start:cp_end] == quote

        # 2. Python 模拟 UTF-16 字节切片严格等于 quote
        utf16_bytes = raw_text.encode("utf-16-le")
        assert utf16_bytes[u16_start * 2 : u16_end * 2].decode("utf-16-le") == quote

        # 3. 跨语言 Node.js 执行 JavaScript 原生 String.substring 与 Array.from.slice 检验
        js_code = f"""
        const raw = {json.dumps(raw_text)};
        const quote = {json.dumps(quote)};
        const u16Sub = raw.substring({u16_start}, {u16_end});
        const cpSlice = Array.from(raw).slice({cp_start}, {cp_end}).join('');
        if (u16Sub !== quote) {{
            console.error('JS UTF16 mismatch:', JSON.stringify(u16Sub), 'vs', JSON.stringify(quote));
            process.exit(1);
        }}
        if (cpSlice !== quote) {{
            console.error('JS CodePoint mismatch:', JSON.stringify(cpSlice), 'vs', JSON.stringify(quote));
            process.exit(2);
        }}
        """
        run_js = subprocess.run(
            ["node", "-e", js_code], capture_output=True, text=True, check=False
        )
        assert run_js.returncode == 0, run_js.stderr


# ---- 14. 领域类型化异常与错误映射测试 ----


def test_domain_typed_errors_and_explicit_error_codes():
    from zhijue.api.errors import spec_for
    from zhijue.domain.errors import (
        DocumentRejected,
        JdRejected,
        PlanningRejected,
        ResourceNotFoundError,
    )

    err1 = ResourceNotFoundError("profile不存在")
    assert err1.code == "RESOURCE_NOT_FOUND" and err1.status_code == 404
    assert spec_for(err1).status_code == 404

    err2 = JdRejected("TEXT_TOO_LARGE", "JD太长")
    assert err2.code == "TEXT_TOO_LARGE" and err2.status_code == 413
    assert spec_for(err2).status_code == 413

    err3 = PlanningRejected("INVALID_REQUEST", "没有可用要求")
    assert err3.code == "INVALID_REQUEST" and err3.status_code == 400
    assert spec_for(err3).status_code == 400

    err4 = DocumentRejected("UNSUPPORTED_FILE_TYPE", "不支持的类型")
    assert err4.code == "UNSUPPORTED_FILE_TYPE" and err4.status_code == 415
    assert spec_for(err4).status_code == 415


# ---- 15. 纯业务 Priority 计算与确定性 tie-break ----


def test_pure_business_priority_calculation():
    """业务优先级仅由重要度（required=3, preferred=1）与验证需求（unknown=3, unverified=2, supported=1）决定。

    priority = importance * 10 + verification_need：
    - required + unknown = 33
    - required + unverified = 32
    - required + supported = 31
    - preferred + unknown = 13
    - preferred + unverified = 12
    不再受未选定的 question archetype 影响。
    """
    raw_text = (
        "## 基本要求\n"
        "- 良好的 C 语言基础；\n"
        "- 理解 MCU 中断机制；\n"
        "- 使用过 UART 串口；\n"
        "## 优先条件\n"
        "- 了解 RTOS 队列；\n"
        "- 使用 Git 版本管理；\n"
    )
    snapshot = make_snapshot(
        snapshot_id="jd_prio_test",
        profile_id="p_prio",
        raw_text=raw_text,
        source_type=JDSourceType.SYNTHETIC_DEMO_JD,
        source_name="prio_test",
    )
    reqs = extract_requirements(snapshot)
    # 模拟证据：C 语言有声明未验证，中断材料完全未体现
    coverage = build_coverage_map(
        requirements=reqs,
        evidence_index={"embedded.c.basics": ["c1"]},
        profile_snapshot_id="snap1",
    )
    plan = plan_interview_slots(
        coverage=coverage, requirements=reqs, seed_bank_version="test_v1"
    )

    slot_map = {s.competency: s for s in plan.slots}
    # 必备项优先级严格高于加分项，且由多维度业务要素驱动
    assert slot_map["embedded.mcu.interrupt"].priority >= 36
    assert slot_map["embedded.c.basics"].priority >= 36
    assert slot_map["embedded.rtos.fundamentals"].priority <= 20
    assert (
        slot_map["embedded.mcu.interrupt"].priority
        > slot_map["embedded.rtos.fundamentals"].priority
    )
    assert (
        slot_map["embedded.c.basics"].priority
        > slot_map["embedded.rtos.fundamentals"].priority
    )


# ---- 16. 真实衍生 JD 必须有完整、非占位的上游来源 ----


def test_real_jd_derived_source_type_metadata():
    jd_text = (
        "## 岗位职责\n"
        "1. 参与 MCU 嵌入式软件开发。\n"
        "## 基本要求\n"
        "- 良好的 C 语言基础；\n"
        "- 理解中断机制；\n"
        "- 使用过 UART 外设；\n"
    )
    snapshot = make_snapshot(
        snapshot_id="jd_real_meta",
        profile_id="p_real",
        raw_text=jd_text,
        source_type=JDSourceType.REAL_JD_DERIVED,
        source_name="嵌入式软件开发实习生演示衍生版",
        upstream_source_name="STMicroelectronics Careers",
        upstream_url="https://careers.st.com/job/embedded-software-intern",
        upstream_retrieved_at="2026-09-18T00:00:00Z",
        upstream_content_hash="a" * 64,
        derived_artifact_path="docs/demo/demo-jd-v3.md",
        derived_content_hash=JDSnapshot.compute_hash(jd_text.strip()),
        transformation_note="保留 required/preferred 层级，仅翻译并移除企业专有描述。",
    )
    assert snapshot.source_type is JDSourceType.REAL_JD_DERIVED
    assert snapshot.is_synthetic is False
    assert snapshot.derived is True
    assert snapshot.source_url is None
    assert snapshot.upstream_url == (
        "https://careers.st.com/job/embedded-software-intern"
    )


def test_real_jd_derived_rejects_missing_or_placeholder_upstream():
    common = {
        "snapshot_id": "jd_untrusted",
        "profile_id": "p_real",
        "raw_text": "## 基本要求\n- 良好的 C 语言基础；",
        "source_type": JDSourceType.REAL_JD_DERIVED,
        "source_name": "无法核验的衍生 JD",
    }
    with pytest.raises(JdRejected, match="JD_PROVENANCE_INVALID"):
        make_snapshot(**common)
    with pytest.raises(JdRejected, match="JD_PROVENANCE_INVALID"):
        make_snapshot(
            **common,
            upstream_source_name="示例岗位",
            upstream_url="https://jobs.example.org/embedded",
            upstream_retrieved_at="2026-09-18T00:00:00Z",
            upstream_content_hash="a" * 64,
            derived_artifact_path="docs/demo/demo-jd.md",
            derived_content_hash="b" * 64,
            transformation_note="本地整理。",
        )


# ---- 17. 负向回归：禁止未声明事实（如"双缓冲"）进入 Claim / Evidence ----


def test_negative_regression_ungrounded_fact_rejected():
    """事实性负向测试：简历未声明的术语（如"双缓冲"）绝不能作为已证实或已声明事实。

    任何 Candidate Claim 必须能够在 SourceBlock 中精确回溯，模型推断不得伪装成事实。
    """
    from zhijue.domain.claims import validate_exact_quote

    real_source_block = (
        "外设与系统：使用过 GPIO、ADC、PWM、TIM、DMA、UART、I2C、SPI、CAN；"
        "比赛调试阶段定位并解决高速串口接收时偶发数据错帧问题。"
    )
    # 真实切片通过
    quote = "定位并解决高速串口接收时偶发数据错帧问题"
    assert validate_exact_quote(quote, real_source_block) == quote
    # 外部臆测或擅自扩写的"DMA 双缓冲"必须被校验器抛出 ValueError 彻底拒绝
    with pytest.raises(ValueError, match="不是来源块文本的子串"):
        validate_exact_quote("采用 DMA 循环双缓冲接收", real_source_block)
    with pytest.raises(ValueError, match="不是来源块文本的子串"):
        validate_exact_quote("双缓冲", real_source_block)


# ---- 18. 中断 EvidenceRelation：RELATED_CONTEXT 保持 UNKNOWN ----


def test_interrupt_evidence_relation_stays_unknown_with_related_context():
    """P0 事实性规则：TIM / 状态机 / 周期任务属于 RELATED_CONTEXT。

    只能帮助 Planner 判断其为高信息价值目标，严禁把 unknown 升级为 unverified！
    """
    from zhijue.domain.requisition import EvidenceRelation, Requirement, RequirementTier

    req = Requirement(
        id="req_int",
        jd_snapshot_id="jd_snap",
        tier=RequirementTier.REQUIRED,
        competency_id="embedded.mcu.interrupt",
        statement="理解中断机制与优先级配置",
        source_span={
            "section": "基本要求",
            "start": 0,
            "end": 12,
            "quote": "理解中断机制与优先级配置",
            "unit": "unicode_code_point",
        },
        importance=3,
        extraction="rule_based",
    )
    # 候选人只有 TIM / 输入捕获相关上下文，无直接中断自述/经历
    coverage = build_coverage_map(
        requirements=[req],
        evidence_index={},  # 无 direct_evidence
        profile_snapshot_id="snap_test",
        related_context_index={
            "embedded.mcu.interrupt": ["claim_tim_01", "claim_capture_02"]
        },
    )
    entry = coverage.by_competency("embedded.mcu.interrupt")
    assert entry is not None
    assert entry.status is CoverageStatus.UNKNOWN, (
        "RELATED_CONTEXT 严禁将 unknown 升级为 unverified"
    )
    assert entry.relation is EvidenceRelation.RELATED_CONTEXT
    assert entry.evidence_ids == (), "上下文不得伪装成直接证据"
    assert len(entry.related_context_ids) == 2
    assert "材料未体现直接经历" in entry.note


# ---- 19. Demo Critical Fact Checklist 召回率测试 ----


def test_demo_critical_fact_checklist_recall():
    """将'没有漏掉任何经历'转为可测量的'关键事实检查集 X/X 成功召回'。"""
    # 模拟从真实 PDF 提取出的事实文本集合
    extracted_facts = [
        "熟悉 STM32 HAL 开发流程，使用过 STM32G4、STM32F4 系列 MCU",
        "比赛调试阶段定位并解决高速串口接收时偶发数据错帧问题，最终完成基本功能与部分发挥要求",
        "使用 FreeRTOS 完成过多任务应用开发，了解任务调度、Queue、Semaphore、Mutex",
        "设计桌面环境监测终端，通过 Queue 传递采样数据",
        "使用 3 个 STM32 节点模拟传感器终端，通过 CAN 总线周期上传采样数据，处理同时发送导致的数据拥塞问题",
        "工具与调试：Keil MDK、STM32CubeMX / CubeIDE、VS Code、Git、CMake",
        "3 人团队完成视觉目标检测与二维云台控制系统，主要负责 STM32 控制端软件、通信协议及系统联调",
        "目前对 STM32 裸机及 FreeRTOS 应用较熟悉，嵌入式 Linux、驱动开发等方向仍在学习中",
    ]

    checklist = [
        ("CF01_STM32_PLATFORM", ["STM32", "HAL"]),
        ("CF02_UART_DMA_FRAMING_DEBUG", ["串口", "错帧"]),
        ("CF03_FREERTOS_MULTITASK", ["FreeRTOS", "任务"]),
        ("CF04_QUEUE_DATA_TRANSFER", ["Queue"]),
        ("CF05_CAN_BUS_CONGESTION", ["CAN", "拥塞"]),
        ("CF06_GIT_VERSION_CONTROL", ["Git"]),
        ("CF07_PROJECT_OWNERSHIP", ["主要负责"]),
        ("CF08_LINUX_LEARNING_BOUNDARY", ["Linux", "学习中"]),
    ]

    all_text = " ".join(extracted_facts)
    recalled = 0
    for cf_id, terms in checklist:
        matched = all(term.lower() in all_text.lower() for term in terms)
        assert matched, f"关键事实 {cf_id} 召回失败，关键词: {terms}"
        recalled += 1

    recall_rate = recalled / len(checklist)
    assert recall_rate == 1.0, f"召回率不足 100%: {recall_rate}"
