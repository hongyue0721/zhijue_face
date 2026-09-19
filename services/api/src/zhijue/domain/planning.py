"""Coverage Map 与五题 Interview Slot Planning（M2-02）。

负责人 2026-09-18 决策：

- M2-02 **不绑定具体 Seed、不生成最终自然语言题目**：Planner 只规划"应该验证
  什么"。具体怎么问由后续 Approved Seed Bank 决定。
- Coverage 不得把缺失当弱项：`unverified ≠ weak`、`unknown ≠ fail`、
  "resume 没写 ≠ 用户不会"。Planner 可以因"岗位重要且未验证"提高**提问**优先级，
  但不得因此降低 Candidate Score——本模块不产生任何分数。
- 排序依据 `JD importance × verification need × information value`，
  不是"简历里写得最多的技能优先"。
- 必须有确定性 tie-break：同输入产生稳定计划。
- 必须走 Seed approval gate：未 approved 的种子不得进入 slot（本阶段 slot
  `seed_id` 恒为 null，仅记录 competency 与验证目标）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from zhijue.domain.errors import PlanningRejected
from zhijue.domain.requisition import (
    NEVER_A_WEAKNESS,
    CoverageStatus,
    EvidenceRelation,
    Requirement,
    RequirementTier,
)

ROOT_SLOT_COUNT = 5  # config/demo.yaml interview.root_question_count
MIN_COMPETENCIES = 3  # config/demo.yaml interview.min_competency_dimensions


class SlotReason(StrEnum):
    """结构化理由码（不展示模型私有推理）。"""

    JD_CRITICAL_NOT_IN_MATERIAL = "JD_CRITICAL_NOT_IN_MATERIAL"
    JD_CRITICAL_CLAIMED_NEEDS_EVIDENCE = "JD_CRITICAL_CLAIMED_NEEDS_EVIDENCE"
    JD_CRITICAL_SUPPORTED_LOWER_REPEAT = "JD_CRITICAL_SUPPORTED_LOWER_REPEAT"
    JD_PREFERRED_SECONDARY = "JD_PREFERRED_SECONDARY"
    COMPETENCY_DIVERSITY = "COMPETENCY_DIVERSITY"
    EVIDENCE_CONTRADICTION = "EVIDENCE_CONTRADICTION"
    CONTEXTUAL_BACKGROUND = "CONTEXTUAL_BACKGROUND"


# 覆盖状态 → 验证需求（越大越需要问）。注意：这只影响"该问什么"，
# **不构成任何扣分**；不在此表的状态（supported）表示已有材料支持，重复验证价值低。
_VERIFICATION_NEED: dict[CoverageStatus, int] = {
    CoverageStatus.CONTRADICTED: 4,  # 确有冲突 → 需要澄清
    CoverageStatus.UNKNOWN: 3,  # 材料没体现 ≠ 不会，但岗位关键时必须问
    CoverageStatus.UNVERIFIED: 2,  # 有材料提及，未经面试确认
    CoverageStatus.CLAIMED: 2,  # 自述声明，同样需要验证
    CoverageStatus.SUPPORTED: 1,  # 已有证据支持 → 降低重复验证
}

# 覆盖状态权重已覆盖信息价值，M2-02 规划阶段尚未选定题型，不预设 archetype_value。


@dataclass(frozen=True)
class CoverageEntry:
    """一条要求 × 候选人证据的覆盖结论。"""

    competency_id: str
    requirement_ids: tuple[str, ...]
    status: CoverageStatus
    evidence_ids: tuple[str, ...]
    relation: EvidenceRelation = EvidenceRelation.RELATED_CONTEXT
    related_context_ids: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_weakness(self) -> bool:
        """只有确有冲突才可能成为弱项；其余状态一律不是（负责人决策 §6）。"""
        return self.status not in NEVER_A_WEAKNESS


@dataclass(frozen=True)
class CoverageMap:
    entries: tuple[CoverageEntry, ...]
    profile_snapshot_id: str | None

    def by_competency(self, competency_id: str) -> CoverageEntry | None:
        for entry in self.entries:
            if entry.competency_id == competency_id:
                return entry
        return None

    def weakness_entries(self) -> tuple[CoverageEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_weakness)


@dataclass(frozen=True)
class InterviewSlot:
    """五题计划中的一个槽位：只说明"验证什么"，不含题目文本。"""

    slot_id: str
    competency: str
    jd_requirement_ids: tuple[str, ...]
    candidate_evidence_ids: tuple[str, ...]
    current_verification_status: CoverageStatus
    verification_goal: str
    priority: int
    difficulty: str
    reason_code: SlotReason
    structured_reason: str
    seed_id: str | None = None  # M2-02 阶段恒为 None（种子未 approved）

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "slot_id": self.slot_id,
            "competency": self.competency,
            "jd_requirement_ids": list(self.jd_requirement_ids),
            "candidate_evidence_ids": list(self.candidate_evidence_ids),
            "current_verification_status": self.current_verification_status.value,
            "verification_goal": self.verification_goal,
            "priority": self.priority,
            "difficulty": self.difficulty,
            "reason_code": self.reason_code.value,
            "structured_reason": self.structured_reason,
            "seed_id": self.seed_id,
        }


@dataclass(frozen=True)
class RootPlan:
    slots: tuple[InterviewSlot, ...]
    seed_bank_version: str
    planner_version: str
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "slots": [slot.as_dict() for slot in self.slots],
            "seed_bank_version": self.seed_bank_version,
            "planner_version": self.planner_version,
            "limitations": list(self.limitations),
        }

    def competency_coverage(self) -> tuple[str, ...]:
        return tuple(sorted({slot.competency for slot in self.slots}))


PLANNER_VERSION = "0.1.0"


def build_coverage_map(
    *,
    requirements: list[Requirement],
    evidence_index: dict[str, list[str]],
    profile_snapshot_id: str | None,
    related_context_index: dict[str, list[str]] | None = None,
    relation_index: dict[str, EvidenceRelation] | None = None,
) -> CoverageMap:
    """按能力维度聚合要求与候选人证据，得出覆盖状态与关联关系。

    证据关系规则（AGENTS 事实性）：
    - DIRECT_CLAIM / DIRECT_EXPERIENCE：产生已确认材料 → unverified（尚未经面试确认，不可算 supported）。
    - RELATED_CONTEXT：仅有相关技术上下文（如 TIM/输入捕获之于中断），**严禁**把 unknown 升级为 unverified！
      保持 status=unknown，并将 context 记录于 related_context_ids 供 Planner 判断信息价值。
    - 无材料：status=unknown，不作负面推断。
    """
    grouped: dict[str, list[Requirement]] = {}
    for requirement in requirements:
        grouped.setdefault(requirement.competency_id, []).append(requirement)

    rel_ctx = related_context_index or {}
    rel_map = relation_index or {}

    entries: list[CoverageEntry] = []
    for competency_id in sorted(grouped):
        requirement_ids = tuple(
            r.id for r in sorted(grouped[competency_id], key=lambda r: r.id)
        )
        evidence_ids = tuple(sorted(evidence_index.get(competency_id, [])))
        context_ids = tuple(sorted(rel_ctx.get(competency_id, [])))

        if evidence_ids:
            status = CoverageStatus.UNVERIFIED
            relation = rel_map.get(competency_id, EvidenceRelation.DIRECT_EXPERIENCE)
            note = "材料中有相关直接经历/自述声明，尚未经面试验证"
        elif context_ids:
            status = CoverageStatus.UNKNOWN
            relation = EvidenceRelation.RELATED_CONTEXT
            evidence_ids = ()  # 严禁将上下文冒充为直接证据
            note = "材料未体现直接经历/自述，但有相关工程上下文；不作负面推断"
        else:
            status = CoverageStatus.UNKNOWN
            relation = EvidenceRelation.RELATED_CONTEXT
            evidence_ids = ()
            note = "材料未体现，不作负面推断"

        entries.append(
            CoverageEntry(
                competency_id=competency_id,
                requirement_ids=requirement_ids,
                status=status,
                evidence_ids=evidence_ids,
                relation=relation,
                related_context_ids=context_ids,
                note=note,
            )
        )
    return CoverageMap(entries=tuple(entries), profile_snapshot_id=profile_snapshot_id)


def _verification_goal(competency_id: str, status: CoverageStatus) -> str:
    if status is CoverageStatus.UNKNOWN:
        return (
            f"确认是否具备 {competency_id} 的岗位相关能力（材料未体现，不作负面推断）"
        )
    if status is CoverageStatus.CONTRADICTED:
        return f"澄清 {competency_id} 上的材料冲突"
    return f"请候选人说明 {competency_id} 的具体做法与边界"


def _difficulty(importance: int, status: CoverageStatus) -> str:
    """难度按岗位重要度与验证需求给；不依赖候选人是否声称会。"""
    score = importance + _VERIFICATION_NEED.get(status, 1)
    if score >= 6:
        return "medium"
    if score >= 4:
        return "medium"
    return "easy"


@dataclass(frozen=True)
class _CandidateSlot:
    requirement: Requirement | None
    competency_id: str
    status: CoverageStatus
    evidence_ids: tuple[str, ...]
    importance: int
    verification_need: int
    tier: RequirementTier
    reason_code: SlotReason
    requirement_ids: tuple[str, ...]
    reason_text: str
    relation: EvidenceRelation = EvidenceRelation.RELATED_CONTEXT
    related_context_ids: tuple[str, ...] = ()
    requirement_count: int = 1
    probing_richness: int = 0

    @property
    def priority(self) -> int:
        """多维度业务优先级分值（消除单纯字母序 tie）。

        1. 岗位基准重要度：required=30, responsibility=20, preferred=10, contextual=10
        2. 验证需求与证据关系分值：
           - CONTRADICTED: +8
           - UNKNOWN + RELATED_CONTEXT: +7（岗位关键且材料有上下文但缺直接机制自述/经历，高信息价值目标）
           - UNKNOWN 无上下文: +6（岗位关键但材料完全未体现）
           - UNVERIFIED/CLAIMED + DIRECT_EXPERIENCE: +5（有明确项目/竞赛排障经历，具备深度探测价值）
           - UNVERIFIED/CLAIMED + DIRECT_CLAIM: +4（仅有自述）
           - SUPPORTED: +2（已有证据，重复验证价值低）
        3. JD 需求覆盖密度：承载该维度的 JD 要求条数（min(requirement_count, 3)）
        4. 证据丰富度：拥有的项目细节/事实数（min(probing_richness, 3)）
        """
        base_importance = self.importance * 10
        if self.status is CoverageStatus.CONTRADICTED:
            relation_score = 8
        elif (
            self.status is CoverageStatus.UNKNOWN
            and self.relation is EvidenceRelation.RELATED_CONTEXT
        ):
            relation_score = 7
        elif self.status is CoverageStatus.UNKNOWN:
            relation_score = 6
        elif (
            self.status in (CoverageStatus.UNVERIFIED, CoverageStatus.CLAIMED)
            and self.relation is EvidenceRelation.DIRECT_EXPERIENCE
        ):
            relation_score = 5
        elif self.status in (CoverageStatus.UNVERIFIED, CoverageStatus.CLAIMED):
            relation_score = 4
        else:
            relation_score = 2

        density_score = min(self.requirement_count, 3)
        richness_score = min(self.probing_richness, 3)
        return base_importance + relation_score + density_score + richness_score

    @property
    def tiebreak(self) -> tuple[object, ...]:
        """确定性 tie-break：业务优先级 → 重要度 → 需求覆盖数 → 证据丰富度 → 能力维度名。"""
        return (
            -self.priority,
            -self.importance,
            -self.requirement_count,
            -self.probing_richness,
            self.competency_id,
        )


def _reason_for(
    requirement: Requirement, status: CoverageStatus
) -> tuple[SlotReason, str]:
    if status is CoverageStatus.CONTRADICTED:
        return SlotReason.EVIDENCE_CONTRADICTION, "材料之间存在冲突，需要当面澄清"
    if requirement.tier is RequirementTier.PREFERRED:
        return SlotReason.JD_PREFERRED_SECONDARY, "岗位加分项，优先级低于必备项"
    if requirement.tier is RequirementTier.CONTEXTUAL:
        return SlotReason.CONTEXTUAL_BACKGROUND, "岗位背景说明，仅作补充验证"
    if status is CoverageStatus.UNKNOWN:
        return (
            SlotReason.JD_CRITICAL_NOT_IN_MATERIAL,
            "岗位必备且材料未体现，需要验证能力是否存在（材料未体现≠不会）",
        )
    if status in {CoverageStatus.CLAIMED, CoverageStatus.UNVERIFIED}:
        return (
            SlotReason.JD_CRITICAL_CLAIMED_NEEDS_EVIDENCE,
            "有自述或材料声明，但缺少过程与边界证据",
        )
    return (
        SlotReason.JD_CRITICAL_SUPPORTED_LOWER_REPEAT,
        "材料已有支持，降低重复验证优先级",
    )


def plan_interview_slots(
    *,
    coverage: CoverageMap,
    requirements: list[Requirement],
    seed_bank_version: str,
    slot_count: int = ROOT_SLOT_COUNT,
    min_competencies: int = MIN_COMPETENCIES,
    evidence_index: dict[str, list[str]] | None = None,
) -> RootPlan:
    """生成固定数量的 Interview Slots；同输入必然同输出。

    关键约束：不得为凑数让同一 competency 无理由占据多个 slot；
    若确实需要重复，必须在 `structured_reason` 中给出理由。
    """
    if slot_count < min_competencies:
        raise PlanningRejected("INVALID_REQUEST", "slot 数量不能少于最少能力维度数")
    requirements_by_competency: dict[str, list[Requirement]] = {}
    for requirement in requirements:
        requirements_by_competency.setdefault(requirement.competency_id, []).append(
            requirement
        )
    if not requirements_by_competency:
        raise PlanningRejected("INVALID_REQUEST", "JD 没有可用的岗位要求，无法生成计划")

    candidates: list[_CandidateSlot] = []
    for competency_id in sorted(requirements_by_competency):
        entry = coverage.by_competency(competency_id)
        status = entry.status if entry else CoverageStatus.UNKNOWN
        evidence_ids = entry.evidence_ids if entry else ()
        # 同一能力维度内取重要度最高的要求作为代表（并列时按 id 稳定）。
        representative = min(
            requirements_by_competency[competency_id],
            key=lambda r: (-r.importance, r.id),
        )
        reason_code, reason_text = _reason_for(representative, status)
        relation = (
            entry.relation
            if entry
            else (
                EvidenceRelation.DIRECT_EXPERIENCE
                if evidence_ids
                else EvidenceRelation.RELATED_CONTEXT
            )
        )
        related_contexts = entry.related_context_ids if entry else ()
        candidates.append(
            _CandidateSlot(
                requirement=representative,
                competency_id=competency_id,
                status=status,
                evidence_ids=evidence_ids,
                importance=representative.importance,
                verification_need=_VERIFICATION_NEED.get(status, 1),
                tier=representative.tier,
                reason_code=reason_code,
                reason_text=reason_text,
                requirement_ids=tuple(
                    r.id
                    for r in sorted(
                        requirements_by_competency[competency_id], key=lambda r: r.id
                    )
                ),
                relation=relation,
                related_context_ids=related_contexts,
                requirement_count=len(requirements_by_competency[competency_id]),
                probing_richness=len(evidence_ids),
            )
        )
    ordered = sorted(candidates, key=lambda c: c.tiebreak)
    if len(ordered) < min_competencies:
        raise PlanningRejected(
            "INVALID_REQUEST",
            f"JD 可用能力维度不足 {min_competencies} 个，无法满足覆盖要求",
        )

    chosen: list[_CandidateSlot] = ordered[:slot_count]
    limitations: list[str] = []
    if len(chosen) < slot_count:
        # 能力维度少于槽位数：按优先级补足，并**必须**给出结构化重复理由
        # （负责人决策 §7：同一 competency 重复需要 reason，不得无理由占用）。
        remaining = list(ordered)
        while remaining and len(chosen) < slot_count:
            duplicate = remaining.pop(0)
            chosen.append(duplicate)
            limitations.append(
                f"{duplicate.competency_id} 出现多次（原因：JD 可用能力维度 "
                f"{len(ordered)} 个少于 {slot_count} 个槽位，按优先级补足；"
                "非按简历篇幅选择）"
            )

    slots: list[InterviewSlot] = []
    for index, candidate in enumerate(chosen, start=1):
        competency = candidate.competency_id
        slots.append(
            InterviewSlot(
                slot_id=f"slot_{index}_{hashlib.sha256(f'{competency}:{index}'.encode()).hexdigest()[:8]}",
                competency=competency,
                jd_requirement_ids=candidate.requirement_ids,
                candidate_evidence_ids=candidate.evidence_ids,
                current_verification_status=candidate.status,
                verification_goal=_verification_goal(competency, candidate.status),
                priority=candidate.priority,
                difficulty=_difficulty(candidate.importance, candidate.status),
                reason_code=candidate.reason_code,
                structured_reason=(
                    f"{candidate.reason_text}；JD 重要度 {candidate.importance} × "
                    f"验证需求 {candidate.verification_need}（{candidate.status.value}）"
                ),
                seed_id=None,  # 种子未 approved，本阶段不绑定
            )
        )

    if len({slot.competency for slot in slots}) < min_competencies:
        raise PlanningRejected(
            "INVALID_REQUEST",
            f"计划只覆盖 {len({s.competency for s in slots})} 个能力维度，少于 {min_competencies}",
        )

    covered = {slot.competency for slot in slots}
    for candidate in ordered:
        if candidate.competency_id not in covered:
            limitations.append(f"{candidate.competency_id} 未进入本轮五题范围")
    limitations.append(
        "五题计划只规定验证目标，不包含题目文本；题目由已批准种子库在后续阶段实例化"
    )
    if coverage.profile_snapshot_id is None:
        limitations.append(
            "尚无候选人资料快照，所有槽位按材料未体现处理（不推断为不会）"
        )

    return RootPlan(
        slots=tuple(slots),
        seed_bank_version=seed_bank_version,
        planner_version=PLANNER_VERSION,
        limitations=tuple(limitations),
    )
