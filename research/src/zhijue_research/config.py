"""Experiment 配置、Prompt 注册表与可复现指纹。

配置本身不含密钥；密钥仍由仓库外 0600 私密文件提供（`*_ENV_FILE` 只记路径）。
所有 hash 都走 `io_utils.canonical_json`，因此同一配置在任何机器上得到同一指纹。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from zhijue_research.io_utils import (
    canonical_json,
    redacted_public_summary,
    sha256_text,
)

CONFIG_VERSION = "experiment_config_1.0.0"
METHOD_IDS = ("vanilla", "prompt_constraint", "rag_context", "evidence_bound")
SPLITS = ("pilot", "dev", "test")
DEFAULT_GENERATION_ATTEMPTS = 1
MAX_GENERATION_ATTEMPTS = 3


class ExperimentConfigError(ValueError):
    """配置不安全、不完整或与实验契约冲突；必须失败，不得静默默认。"""


@dataclass(frozen=True, slots=True)
class ModelParams:
    """同组方法必须共用的采样参数（I5）。"""

    provider: str
    model: str
    temperature: float
    reasoning_effort: str
    max_tokens: int
    timeout_seconds: float
    stream_stall_seconds: float
    generation_attempts: int

    def fingerprint(self) -> str:
        payload = {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "stream_stall_seconds": self.stream_stall_seconds,
            "generation_attempts": self.generation_attempts,
            "transport": "openai_compatible_chat_transport_1.0.0",
        }
        return sha256_text(canonical_json(payload))

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "stream_stall_seconds": self.stream_stall_seconds,
            "generation_attempts": self.generation_attempts,
        }


@dataclass(frozen=True, slots=True)
class RetrievalParams:
    top_k: int
    query_template_version: str
    embed_mode: str
    embed_env_file: str  # 路径记录，不含密钥值

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "top_k": self.top_k,
            "query_template_version": self.query_template_version,
            "embed_mode": self.embed_mode,
        }


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    root: Path
    raw: Mapping[str, Any]
    dataset_version: str
    splits_hash: str
    split: str
    methods: tuple[str, ...]
    model: ModelParams
    retrieval: RetrievalParams
    evaluator_version: str
    prompt_versions: Mapping[str, str]
    prompt_hashes: Mapping[str, Mapping[str, str]]
    seed: int | None
    allow_paid_calls: bool
    price_per_million_input: float | None
    price_per_million_output: float | None

    @property
    def fingerprint(self) -> str:
        payload = {
            "config_version": self.raw.get("schema_version"),
            "dataset_version": self.dataset_version,
            "splits_hash": self.splits_hash,
            "split": self.split,
            "methods": list(self.methods),
            "model": self.model.as_public_dict(),
            "retrieval": self.retrieval.as_public_dict(),
            "evaluator_version": self.evaluator_version,
            "prompt_versions": dict(sorted(self.prompt_versions.items())),
            "prompt_hashes": {
                method: dict(sorted(versions.items()))
                for method, versions in sorted(self.prompt_hashes.items())
            },
            "seed": self.seed,
        }
        return sha256_text(canonical_json(payload))

    def experiment_key(
        self, *, case_id: str, method_id: str, model_fingerprint: str
    ) -> str:
        payload = {
            "case_id": case_id,
            "method_id": method_id,
            "model_fingerprint": model_fingerprint,
            "prompt_version": self.prompt_versions.get(method_id),
            "config_fingerprint": self.fingerprint,
            "dataset_version": self.dataset_version,
            "split": self.split,
        }
        return sha256_text(canonical_json(payload))

    def derive_run_id(self, experiment_key: str) -> str:
        return f"r_{experiment_key[:16]}"

    def estimated_cost(
        self, *, input_tokens: int | None, output_tokens: int | None
    ) -> dict[str, Any]:
        """目录价推导。缺单价或缺 token 时返回 null，绝不估造。"""

        if (
            self.price_per_million_input is None
            or self.price_per_million_output is None
            or input_tokens is None
            or output_tokens is None
        ):
            return {"cost": None, "cost_basis": "not_measured"}
        value = (
            input_tokens * self.price_per_million_input
            + output_tokens * self.price_per_million_output
        ) / 1_000_000
        return {
            "cost": round(value, 8),
            "cost_basis": "catalog_price",
            "price_per_million_input": self.price_per_million_input,
            "price_per_million_output": self.price_per_million_output,
        }


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping or mapping[key] is None:
        raise ExperimentConfigError(f"{where} 缺少必填项 {key}")
    return mapping[key]


def _number(value: Any, *, where: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentConfigError(f"{where} 必须是数字")
    if not minimum <= float(value) <= maximum:
        raise ExperimentConfigError(f"{where} 必须在 {minimum}..{maximum} 内")
    return float(value)


def load_experiment_config(path: Path, *, split: str | None = None) -> ExperimentConfig:
    """加载并校验实验配置。任何缺项/越界/含密钥的键都直接失败。"""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != CONFIG_VERSION:
        raise ExperimentConfigError(f"不支持的配置版本：{raw.get('schema_version')!r}")
    for key in raw:
        if "key" in key.lower() or "secret" in key.lower() or "token" in key.lower():
            raise ExperimentConfigError(f"配置禁止携带密钥类字段：{key}")

    model_raw = _require(raw, "model", "config")
    model = ModelParams(
        provider=str(_require(model_raw, "provider", "model")),
        model=str(_require(model_raw, "model", "model")),
        temperature=_number(
            _require(model_raw, "temperature", "model"),
            where="model.temperature",
            minimum=0,
            maximum=2,
        ),
        reasoning_effort=str(_require(model_raw, "reasoning_effort", "model")),
        max_tokens=int(
            _number(
                _require(model_raw, "max_tokens", "model"),
                where="model.max_tokens",
                minimum=1,
                maximum=262_144,
            )
        ),
        timeout_seconds=_number(
            _require(model_raw, "timeout_seconds", "model"),
            where="model.timeout_seconds",
            minimum=1,
            maximum=1800,
        ),
        stream_stall_seconds=_number(
            _require(model_raw, "stream_stall_seconds", "model"),
            where="model.stream_stall_seconds",
            minimum=1,
            maximum=600,
        ),
        generation_attempts=int(
            _number(
                model_raw.get("generation_attempts", DEFAULT_GENERATION_ATTEMPTS),
                where="model.generation_attempts",
                minimum=1,
                maximum=MAX_GENERATION_ATTEMPTS,
            )
        ),
    )
    if model.reasoning_effort == "none":
        # 实测该供应商 `none` 会把思维链漏进 content，直接污染被测量。
        raise ExperimentConfigError(
            "reasoning_effort=none 会污染 content，禁止用于事实一致性实验"
        )

    retrieval_raw = _require(raw, "retrieval", "config")
    retrieval = RetrievalParams(
        top_k=int(
            _number(
                _require(retrieval_raw, "top_k", "retrieval"),
                where="retrieval.top_k",
                minimum=1,
                maximum=50,
            )
        ),
        query_template_version=str(
            _require(retrieval_raw, "query_template_version", "retrieval")
        ),
        embed_mode=str(_require(retrieval_raw, "embed_mode", "retrieval")),
        embed_env_file=str(retrieval_raw.get("embed_env_file", "")),
    )
    if retrieval.embed_mode not in {"live", "fixture"}:
        raise ExperimentConfigError("retrieval.embed_mode 只能是 live 或 fixture")
    if retrieval.embed_mode == "live" and not retrieval.embed_env_file:
        raise ExperimentConfigError("embed_mode=live 必须给出私密 env 文件路径")

    methods = tuple(raw.get("methods") or ())
    if not methods or any(item not in METHOD_IDS for item in methods):
        raise ExperimentConfigError(f"methods 必须是 {METHOD_IDS} 的非空子集")
    prompt_versions = dict(_require(raw, "prompt_versions", "config"))
    missing = sorted(set(methods) - set(prompt_versions))
    if missing:
        raise ExperimentConfigError(f"缺少 prompt 版本登记：{missing}")

    # 规则 7：正文改动必须新建版本；因此加载时就要求每个 (method, version) 都有登记 hash。
    prompt_hashes = {
        str(method): {
            str(version): str(digest) for version, digest in (versions or {}).items()
        }
        for method, versions in (raw.get("prompt_hashes") or {}).items()
    }
    for method in methods:
        version = prompt_versions[method]
        digest = prompt_hashes.get(method, {}).get(version)
        if not digest:
            raise ExperimentConfigError(
                f"prompt {method}@{version} 没有登记 hash；请先运行 scripts/pin_prompts.py"
            )
        if len(digest) != 64:
            raise ExperimentConfigError(
                f"prompt {method}@{version} 的登记 hash 长度异常"
            )

    split_value = split or str(_require(raw, "split", "config"))
    if split_value not in SPLITS:
        raise ExperimentConfigError(f"split 只能是 {SPLITS}")

    return ExperimentConfig(
        root=path.resolve().parent,
        raw=raw,
        dataset_version=str(_require(raw, "dataset_version", "config")),
        splits_hash=str(_require(raw, "splits_hash", "config")),
        split=split_value,
        methods=methods,
        model=model,
        retrieval=retrieval,
        evaluator_version=str(_require(raw, "evaluator_version", "config")),
        prompt_versions=prompt_versions,
        prompt_hashes=prompt_hashes,
        seed=raw.get("seed"),
        allow_paid_calls=bool(raw.get("allow_paid_calls", False)),
        price_per_million_input=_optional_number(raw.get("price_per_million_input")),
        price_per_million_output=_optional_number(raw.get("price_per_million_output")),
    )


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def model_fingerprint_from_settings(summary: Mapping[str, Any]) -> str:
    """把私密配置摘要（去密钥）并入指纹，保证"同一 transport 配置"可核对。"""

    return sha256_text(canonical_json(redacted_public_summary(dict(summary))))
