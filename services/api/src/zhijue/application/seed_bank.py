"""种子库加载与筛选（docs/05 §4）。

本模块是种子进入业务链的**唯一入口**：从 `data/seeds/*.json` 读取、
按契约校验、只放行 live 允许的审核状态。加载失败必须显式失败——
不允许"读不到就当作空题库"继续跑出看似正常的面试（AGENTS §2）。

live 门槛来自 `config/demo.yaml` 的 `seed_bank.live_allowed_review_status`；
加载时读取并校验该权威配置，`live_only=True` 只返回达到门槛的种子。
**不把模型知识当作技术参考依据**：技术参考要点必须带非空的
reference_ids（已由 Schema 强制），本模块只做加载与筛选。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

# 与 config/demo.yaml 的 seed_bank.review_status 语义一致（ADR-013 映射）。
REVIEW_RANK = {
    "draft": 0,
    "rejected": 0,
    "deprecated": 0,
    "technical_review": 1,  # Level 1 通过、Level 2 待做
    "approved": 2,  # 两级均通过
}


class SeedBankError(ValueError):
    """种子库不可用：缺失、契约不合法、或没有任何种子满足当前门槛。"""


@dataclass(frozen=True)
class Seed:
    id: str
    version: str
    competency_id: str
    difficulty: str
    archetype: str
    intent: str
    stem: str
    reference_ids: tuple[str, ...]
    reference_points: tuple[dict[str, Any], ...]
    red_flags: tuple[dict[str, Any], ...]
    follow_up_strategy: dict[str, Any]
    rubric: tuple[dict[str, Any], ...]
    followup_intents: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    review_status: str

    @property
    def technical_points(self) -> tuple[dict[str, Any], ...]:
        return tuple(p for p in self.reference_points if p["kind"] == "technical")


class SeedBank:
    """只读种子库：加载即校验，不做隐式补齐或默认值。"""

    def __init__(
        self,
        seeds: list[Seed],
        *,
        schema_version: str,
        live_allowed_review_status: str,
    ) -> None:
        if live_allowed_review_status not in REVIEW_RANK:
            raise SeedBankError(f"未知的 live 审核门槛：{live_allowed_review_status}")
        self._seeds = tuple(seeds)
        self.schema_version = schema_version
        self.live_allowed_review_status = live_allowed_review_status
        self._by_id = {seed.id: seed for seed in self._seeds}
        if len(self._by_id) != len(self._seeds):
            raise SeedBankError("存在重复的 seed id")

    def __len__(self) -> int:
        return len(self._seeds)

    @property
    def seeds(self) -> tuple[Seed, ...]:
        return self._seeds

    def get(self, seed_id: str) -> Seed:
        try:
            return self._by_id[seed_id]
        except KeyError as exc:
            raise SeedBankError(f"RESOURCE_NOT_FOUND: seed {seed_id}") from exc

    def live_eligible(self) -> tuple[Seed, ...]:
        threshold = REVIEW_RANK[self.live_allowed_review_status]
        return tuple(
            seed
            for seed in self._seeds
            if REVIEW_RANK.get(seed.review_status, -1) >= threshold
        )

    def by_competency(self, competency_id: str) -> tuple[Seed, ...]:
        return tuple(
            seed for seed in self._seeds if seed.competency_id == competency_id
        )

    def competency_ids(self) -> tuple[str, ...]:
        return tuple(sorted({seed.competency_id for seed in self._seeds}))

    def version_fingerprint(self) -> str:
        """种子库版本指纹（Interview.seed_bank_version）：内容变化必须改变。"""
        import hashlib

        payload = json.dumps(
            [
                {"id": s.id, "version": s.version}
                for s in sorted(self._seeds, key=lambda s: s.id)
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


def _schema_path() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        path = candidate / "contracts" / "seed.schema.json"
        if path.is_file():
            return path
    raise SeedBankError("未找到 contracts/seed.schema.json")


def _demo_config_path() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        path = candidate / "config" / "demo.yaml"
        if path.is_file():
            return path
    raise SeedBankError("未找到 config/demo.yaml")


def _live_allowed_review_status() -> str:
    path = _demo_config_path()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SeedBankError(f"无法读取 live 审核门槛：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("seed_bank"), dict):
        raise SeedBankError("config/demo.yaml 缺少 seed_bank 配置")
    status = payload["seed_bank"].get("live_allowed_review_status")
    if status not in REVIEW_RANK:
        raise SeedBankError(f"无效的 live 审核门槛：{status}")
    return status


def load_seed_bank(seeds_dir: Path, *, live_only: bool = False) -> SeedBank:
    """加载并校验种子；live_only 只返回达到配置审核门槛的条目。"""
    directory = seeds_dir.expanduser().resolve()
    if not directory.is_dir():
        raise SeedBankError(f"种子目录不存在：{directory}")
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise SeedBankError(f"种子目录为空：{directory}")

    validator = Draft202012Validator(
        json.loads(_schema_path().read_text(encoding="utf-8"))
    )
    seeds: list[Seed] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(payload), key=str)
        if errors:
            raise SeedBankError(f"{path.name} 不符合 seed 契约：{errors[0].message}")
        seeds.append(_to_seed(payload))

    live_allowed_review_status = _live_allowed_review_status()
    bank = SeedBank(
        seeds,
        schema_version="1.0.0",
        live_allowed_review_status=live_allowed_review_status,
    )
    if not live_only:
        return bank

    eligible = list(bank.live_eligible())
    if not eligible:
        raise SeedBankError(
            f"没有任何种子达到 live 门槛（需要至少 {live_allowed_review_status}）"
        )
    return SeedBank(
        eligible,
        schema_version=bank.schema_version,
        live_allowed_review_status=live_allowed_review_status,
    )


def _to_seed(payload: dict[str, Any]) -> Seed:
    return Seed(
        id=payload["id"],
        version=payload["version"],
        competency_id=payload["competency_id"],
        difficulty=payload["difficulty"],
        archetype=payload["archetype"],
        intent=payload["intent"],
        stem=payload["stem"],
        reference_ids=tuple(payload["reference_ids"]),
        reference_points=tuple(payload["reference_points"]),
        red_flags=tuple(payload["red_flags"]),
        follow_up_strategy=dict(payload["follow_up_strategy"]),
        rubric=tuple(payload["rubric"]),
        followup_intents=tuple(payload["followup_intents"]),
        out_of_scope=tuple(payload["out_of_scope"]),
        review_status=payload["review_status"],
    )
