"""M2-02 编排：JD 导入 → Requirement 抽取 → Coverage Map → 五题 Slot 计划。

数据流（负责人 2026-09-18 决策 §4）：

    Raw JD → JD Snapshot → JD Requirements → Candidate Evidence
           → Coverage Map → 5 Interview Slots

职责边界：
- **不绑定具体 Seed、不生成自然语言题目**（种子未 approved）。
- Requirement 抽取本身属于 Evidence/Provenance 体系：每条要求带 `source_span`。
- 候选证据只从**已确认 Claim** 的 source_block 映射而来；没有证据 = unknown。
- 本服务不产生任何候选人分数，也不把缺失写成弱项。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import Claim, Profile
from zhijue.domain.competency_profiles import EMBEDDED_JUNIOR_V1, CompetencyProfile
from zhijue.domain.errors import DomainError, ResourceNotFoundError
from zhijue.domain.ids import new_id
from zhijue.domain.planning import (
    MIN_COMPETENCIES,
    ROOT_SLOT_COUNT,
    CoverageMap,
    RootPlan,
    build_coverage_map,
    plan_interview_slots,
)
from zhijue.domain.requisition import (
    EvidenceRelation,
    JDSnapshot,
    JDSourceType,
    JDStatus,
    Requirement,
    extract_requirements,
    make_snapshot,
)


@dataclass(frozen=True)
class JDPlanResult:
    snapshot: JDSnapshot
    requirements: tuple[Requirement, ...]
    coverage: CoverageMap
    plan: RootPlan


class JDPlanningError(DomainError):
    """JD/计划不可用；HTTP 层据此映射契约错误。"""

    def __init__(self, code_or_msg: str, message: str = "") -> None:
        if message:
            code = code_or_msg
            msg = message
        elif ": " in code_or_msg:
            code, msg = code_or_msg.split(": ", 1)
        else:
            code = "INVALID_REQUEST"
            msg = code_or_msg
        status_code = 400 if code == "INVALID_REQUEST" else 422
        super().__init__(msg, code=code, status_code=status_code)


class JDPlanningService:
    def __init__(self, *, engine: Engine) -> None:
        self._engine = engine

    # ---- JD ----

    def import_jd(
        self,
        *,
        profile_id: str,
        raw_text: str,
        source_name: str,
        source_type: JDSourceType = JDSourceType.SYNTHETIC_DEMO_JD,
        source_url: str | None = None,
        retrieved_at: str | None = None,
        upstream_source_name: str | None = None,
        upstream_url: str | None = None,
        upstream_retrieved_at: str | None = None,
        upstream_content_hash: str | None = None,
        derived_artifact_path: str | None = None,
        derived_content_hash: str | None = None,
        transformation_note: str | None = None,
    ) -> JDSnapshot:
        with Session(self._engine) as session:
            if session.get(Profile, profile_id) is None:
                raise ResourceNotFoundError(f"profile {profile_id} 不存在。")
        snapshot = make_snapshot(
            snapshot_id=new_id("jd"),
            profile_id=profile_id,
            raw_text=raw_text,
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            retrieved_at=retrieved_at,
            upstream_source_name=upstream_source_name,
            upstream_url=upstream_url,
            upstream_retrieved_at=upstream_retrieved_at,
            upstream_content_hash=upstream_content_hash,
            derived_artifact_path=derived_artifact_path,
            derived_content_hash=derived_content_hash,
            transformation_note=transformation_note,
        )
        return snapshot

    # ---- 候选证据 ----

    def evidence_indices(
        self,
        *,
        profile_id: str,
        profile: CompetencyProfile = EMBEDDED_JUNIOR_V1,
    ) -> tuple[
        dict[str, list[str]],
        dict[str, list[str]],
        dict[str, EvidenceRelation],
    ]:
        """从已确认 Claim 提取直接证据索引、相关上下文索引及证据关系映射。

        遵循事实性规则：
        - 只有 DIRECT_CLAIM / DIRECT_EXPERIENCE 归入 direct_index，可影响 Candidate State；
        - 仅匹配 RELATED_CONTEXT 归入 context_index，用于信息价值仲裁，不将 unknown 升级为 unverified。
        """
        direct_index: dict[str, list[str]] = {}
        context_index: dict[str, list[str]] = {}
        relation_map: dict[str, EvidenceRelation] = {}

        with Session(self._engine, expire_on_commit=False) as session:
            claims = session.scalars(
                select(Claim).where(
                    Claim.profile_id == profile_id, Claim.status == "confirmed"
                )
            )
            for claim in claims:
                text = claim.text.lower()
                # 1. 检查直接证据
                for keywords, competency in profile.direct_evidence_rules:
                    if any(keyword in text for keyword in keywords):
                        direct_index.setdefault(competency, []).append(claim.id)
                        is_exp = any(
                            w in text
                            for w in (
                                "项目",
                                "竞赛",
                                "大赛",
                                "负责",
                                "解决",
                                "排查",
                                "调试",
                                "实现",
                            )
                        )
                        current_rel = relation_map.get(competency)
                        if is_exp or current_rel is None:
                            relation_map[competency] = (
                                EvidenceRelation.DIRECT_EXPERIENCE
                                if is_exp
                                else EvidenceRelation.DIRECT_CLAIM
                            )
                # 2. 检查相关上下文
                for keywords, competency in profile.related_context_rules:
                    if any(keyword in text for keyword in keywords):
                        context_index.setdefault(competency, []).append(claim.id)

        clean_direct = {k: sorted(set(v)) for k, v in direct_index.items()}
        clean_context = {k: sorted(set(v)) for k, v in context_index.items()}
        return clean_direct, clean_context, relation_map

    def evidence_index(
        self,
        *,
        profile_id: str,
        profile: CompetencyProfile = EMBEDDED_JUNIOR_V1,
    ) -> dict[str, list[str]]:
        """仅返回所选能力配置的直接证据映射。"""
        direct, _, _ = self.evidence_indices(profile_id=profile_id, profile=profile)
        return direct

    # ---- 全链路 ----

    def plan(
        self,
        *,
        snapshot: JDSnapshot,
        evidence_index: dict[str, list[str]],
        profile_snapshot_id: str | None,
        seed_bank_version: str,
        slot_count: int = ROOT_SLOT_COUNT,
        min_competencies: int = MIN_COMPETENCIES,
        related_context_index: dict[str, list[str]] | None = None,
        relation_index: dict[str, EvidenceRelation] | None = None,
        profile: CompetencyProfile = EMBEDDED_JUNIOR_V1,
    ) -> JDPlanResult:
        requirements = extract_requirements(snapshot, profile=profile)
        if not requirements:
            raise JDPlanningError(
                "INVALID_REQUEST: JD 中没有可识别的岗位要求（需要显式标记如「必要项：」「加分项：」）"
            )
        coverage = build_coverage_map(
            requirements=requirements,
            evidence_index=evidence_index,
            profile_snapshot_id=profile_snapshot_id,
            related_context_index=related_context_index,
            relation_index=relation_index,
        )
        plan = plan_interview_slots(
            coverage=coverage,
            requirements=requirements,
            seed_bank_version=seed_bank_version,
            slot_count=slot_count,
            min_competencies=min_competencies,
            evidence_index=evidence_index,
            profile=profile,
        )
        return JDPlanResult(
            snapshot=snapshot,
            requirements=tuple(requirements),
            coverage=coverage,
            plan=plan,
        )


def snapshot_status(snapshot: JDSnapshot) -> str:
    """JD 状态用于持久化与展示；合成材料必须自报（不冒充真实招聘）。"""
    return (
        "synthetic_demo" if snapshot.is_synthetic else JDStatus(snapshot.status).value
    )
