"""Strict, finite competency rules loaded from the selected immutable pack.

Keywords are literal case-normalized substrings, never executable expressions.
Rule order is preserved: JD uses the first match; direct and related evidence
remain separate indices. Parsing establishes shape/references, not owner approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zhijue.domain.knowledge_packs import PackValidationError, _validate_against

KeywordRule = tuple[tuple[str, ...], str]
FamilyRule = tuple[str, str]


class CompetencyProfileError(ValueError):
    """Invalid profile data; never fall back to another occupation's rules."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Capability:
    competency_id: str
    label: str


@dataclass(frozen=True)
class CompetencyProfile:
    profile_id: str
    profile_version: str
    capabilities: tuple[Capability, ...]
    jd_keyword_rules: tuple[KeywordRule, ...]
    direct_evidence_rules: tuple[KeywordRule, ...]
    related_context_rules: tuple[KeywordRule, ...]
    seed_family_rules: tuple[FamilyRule, ...]

    @property
    def competency_ids(self) -> frozenset[str]:
        return frozenset(capability.competency_id for capability in self.capabilities)

    def label_for(self, competency_id: str) -> str:
        return next(
            (c.label for c in self.capabilities if c.competency_id == competency_id),
            competency_id,
        )

    def as_declared_dict(self) -> dict[str, Any]:
        return {
            "competency_profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "capabilities": [
                {"competency_id": c.competency_id, "label": c.label}
                for c in self.capabilities
            ],
            **{
                name: [
                    {"competency_id": comp, "keywords": list(keywords)}
                    for keywords, comp in getattr(self, name)
                ]
                for name in (
                    "jd_keyword_rules",
                    "direct_evidence_rules",
                    "related_context_rules",
                )
            },
            "seed_family_rules": [
                {"root_competency": root, "target_prefix": prefix}
                for root, prefix in self.seed_family_rules
            ],
        }


def parse_competency_profile(declared: Any) -> CompetencyProfile:
    """Validate every field and reference, then preserve literal rule priority."""
    try:
        _validate_against("competencies", declared, path="competencies.json")
    except PackValidationError as exc:
        raise CompetencyProfileError("PACK_PROFILE_INVALID", exc.message) from exc
    capabilities = tuple(Capability(**entry) for entry in declared["capabilities"])
    ids = frozenset(c.competency_id for c in capabilities)
    if len(ids) != len(capabilities):
        raise CompetencyProfileError("PACK_PROFILE_INVALID", "能力 ID 必须唯一。")
    rules: dict[str, tuple[KeywordRule, ...]] = {}
    for name in ("jd_keyword_rules", "direct_evidence_rules", "related_context_rules"):
        entries = declared[name]
        if any(entry["competency_id"] not in ids for entry in entries):
            raise CompetencyProfileError(
                "PACK_PROFILE_INVALID", f"{name} 引用未声明能力。"
            )
        if any(
            not keyword.strip() or keyword != keyword.lower()
            for entry in entries
            for keyword in entry["keywords"]
        ):
            raise CompetencyProfileError(
                "PACK_PROFILE_INVALID", f"{name} 关键词必须非空并使用小写匹配规范。"
            )
        rules[name] = tuple(
            (tuple(entry["keywords"]), entry["competency_id"]) for entry in entries
        )
    families = tuple(
        (entry["root_competency"], entry["target_prefix"])
        for entry in declared["seed_family_rules"]
    )
    if len(set(families)) != len(families) or any(
        root not in ids or not any(cid.startswith(prefix) for cid in ids)
        for root, prefix in families
    ):
        raise CompetencyProfileError(
            "PACK_PROFILE_INVALID", "家族规则必须唯一，根与目标前缀须覆盖已声明能力。"
        )
    if any(not c.label.strip() for c in capabilities):
        raise CompetencyProfileError("PACK_PROFILE_INVALID", "能力 label 不可为空白。")
    return CompetencyProfile(
        profile_id=declared["competency_profile_id"],
        profile_version=declared["profile_version"],
        capabilities=capabilities,
        seed_family_rules=families,
        **rules,
    )
