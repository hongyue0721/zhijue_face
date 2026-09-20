"""M3-01: real business answer-model call through the openJiuwen workflow."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import platform
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
from openjiuwen.core.common.logging.log_config import (
    configure_log_config,
    get_log_config_snapshot,
)
from openjiuwen.core.workflow import Workflow

from zhijue.adapters.model import (
    OBSERVATION_SYSTEM_PROMPT,
    OpenAICompatibleAnswerAnalyzer,
    load_model_settings,
)
from zhijue.application.answer_workflow import run_handle_answer_workflow
from zhijue.domain.interview_policy import POLICY_VERSION

TASK_ID = "M3-01"
SMOKE_VERSION = "1.0.0"
SEED_FILENAME = "seed_embedded_uart_dma_debug.json"
QUESTION_TEXT = (
    "串口 DMA 接收偶发丢数据，你会按什么顺序排查？接收链路上有哪些状态可以帮你定位？"
)
ANSWER_TEXT = (
    "我会先固定芯片型号和复现条件，再检查 UART 接收侧的 overrun、framing、noise、"
    "parity 状态；随后核对 DMA 映射、NDTR、缓冲区边界和中断优先级，最后用逻辑分析仪"
    "与软件计数器对照，判断数据丢在串口接收还是 DMA 搬运阶段。"
)
IDS = {
    "observation_id": "observation_m3_01_live",
    "answer_id": "answer_m3_01_live",
    "question_id": "question_m3_01_live",
    "root_question_id": "question_m3_01_live",
    "decision_id": "decision_m3_01_live",
}


def _configure_private_sdk_logging() -> None:
    sdk_logging = get_log_config_snapshot()
    sdk_logging["level"] = "WARNING"
    for output_key in ("output", "interface_output", "performance_output"):
        sdk_logging[output_key] = ["console"]
    configure_log_config(sdk_logging)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    root = next(
        (
            parent
            for parent in here.parents
            if (parent / "contracts" / "observation.schema.json").is_file()
        ),
        None,
    )
    if root is None:
        raise RuntimeError("cannot locate repository root")
    return root


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
    path.chmod(0o600)


def _assert_safe_evidence(value: Any, secret: str) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _assert_safe_evidence(nested, secret)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _assert_safe_evidence(nested, secret)
        return
    if not isinstance(value, str):
        return
    if secret and secret in value:
        raise ValueError("evidence contains the API key")
    if value.startswith("/") or (len(value) > 2 and value[1:3] in {":\\", ":/"}):
        raise ValueError("evidence contains an absolute path")


def _load_seed(root: Path) -> tuple[dict[str, Any], Path]:
    path = root / "data" / "seeds" / SEED_FILENAME
    seed = json.loads(path.read_text(encoding="utf-8"))
    if seed.get("review_status") != "approved":
        raise ValueError("live smoke requires an approved Seed")
    review_levels = seed.get("review_levels") or {}
    if any(
        (review_levels.get(level) or {}).get("status") != "passed"
        for level in ("level1", "level2")
    ):
        raise ValueError("live smoke requires passed Level 1 and Level 2 review")
    return seed, path


def _rubric_snapshot(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "approved_seed",
        "rubric": seed["rubric"],
        "reference_ids": seed["reference_ids"],
        "followup_intents": seed["followup_intents"],
    }


def _reference_material(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "approved_seed",
        "seed_id": seed["id"],
        "reference_points": seed["reference_points"],
    }


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    observation = result["observation"]
    return {
        "observation": {
            "id": observation["id"],
            "relevance": observation["relevance"],
            "knowledge_status": observation["knowledge_status"],
            "criteria": [
                {
                    "criterion_id": criterion["criterion_id"],
                    "level": criterion["level"],
                    "finding": criterion["finding"],
                    "knowledge_refs": criterion["knowledge_refs"],
                    "answer_quote_count": len(criterion["answer_quotes"]),
                }
                for criterion in observation["criteria"]
            ],
            "clarification_needed": observation["clarification_needed"],
            "validation_flags": observation["validation_flags"],
        },
        "decision": {
            "id": result["decision"]["id"],
            "action": result["decision"]["action"],
            "reason_code": result["decision"]["reason_code"],
            "policy_version": result["decision"]["policy_version"],
        },
        "usage": result["usage"],
    }


async def _run_live(env_file: Path, request_counter: list[int]) -> dict[str, Any]:
    root = _repo_root()
    seed, _ = _load_seed(root)
    settings = load_model_settings(env_file)

    async def count_request(_request: httpx.Request) -> None:
        request_counter[0] += 1

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.model_timeout),
        follow_redirects=False,
        trust_env=False,
        event_hooks={"request": [count_request]},
    ) as client:
        analyzer = OpenAICompatibleAnswerAnalyzer(settings, client=client)
        return await run_handle_answer_workflow(
            analyzer=analyzer,
            question_text=QUESTION_TEXT,
            answer_text=ANSWER_TEXT,
            rubric_snapshot=_rubric_snapshot(seed),
            reference_material=_reference_material(seed),
            competency_id=seed["competency_id"],
            followup_count=0,
            remaining_roots=4,
            allowed_followup_intents=seed["followup_intents"],
            timeout_seconds=settings.model_timeout,
            **IDS,
        )


def _base_evidence(env_file: Path) -> tuple[dict[str, Any], str]:
    root = _repo_root()
    seed, seed_path = _load_seed(root)
    settings = load_model_settings(env_file)
    workflow_source = Path(inspect.getfile(run_handle_answer_workflow))
    model_source = Path(inspect.getfile(OpenAICompatibleAnswerAnalyzer))
    schema_path = root / "contracts" / "observation.schema.json"
    evidence = {
        "task_id": TASK_ID,
        "smoke_version": SMOKE_VERSION,
        "status": "running",
        "run_mode": "live",
        "data_mode": "synthetic",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": settings.public_summary(),
        "input": {
            "seed_id": seed["id"],
            "seed_version": seed["version"],
            "seed_review_status": seed["review_status"],
            "seed_review_record_id": seed["review_record_id"],
            "rubric_version": seed["version"],
            "question_sha256": _sha256_bytes(QUESTION_TEXT.encode("utf-8")),
            "answer_sha256": _sha256_bytes(ANSWER_TEXT.encode("utf-8")),
            "question_characters": len(QUESTION_TEXT),
            "answer_characters": len(ANSWER_TEXT),
        },
        "versions": {
            "python": platform.python_version(),
            "openjiuwen": version("openjiuwen"),
            "policy": POLICY_VERSION,
            "prompt_sha256": _sha256_bytes(OBSERVATION_SYSTEM_PROMPT.encode("utf-8")),
        },
        "source_hashes": {
            "seed_sha256": _sha256_bytes(seed_path.read_bytes()),
            "observation_schema_sha256": _sha256_bytes(schema_path.read_bytes()),
            "workflow_source_sha256": _sha256_bytes(workflow_source.read_bytes()),
            "model_adapter_source_sha256": _sha256_bytes(model_source.read_bytes()),
        },
        "workflow": {
            "sdk_class": f"{Workflow.__module__}.{Workflow.__name__}",
            "graph": "Start->Analyzer->SemanticValidation->DeterministicPolicy->End",
            "mocked_sdk": False,
            "mocked_model": False,
            "knowledge_retrieval": "NOT_RUN_THIS_SMOKE",
        },
        "cost": {
            "value": None,
            "currency": None,
            "status": "NOT_MEASURED",
        },
    }
    return evidence, settings.api_key.get_secret_value()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new evidence path")

    _configure_private_sdk_logging()

    evidence, secret = _base_evidence(args.env_file)
    exit_code = 0
    request_counter = [0]
    started = time.perf_counter()
    try:
        result = asyncio.run(_run_live(args.env_file, request_counter))
    except Exception as exc:  # noqa: BLE001 - evidence boundary records typed failure.
        evidence.update(
            {
                "status": "failed",
                "http_attempts": request_counter[0],
                "logical_model_calls": 1,
                "duration_seconds": round(time.perf_counter() - started, 6),
                "failure": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        exit_code = 1
    else:
        evidence.update(
            {
                "status": "passed",
                "http_attempts": request_counter[0],
                "logical_model_calls": 1,
                "duration_seconds": round(time.perf_counter() - started, 6),
                "result": _result_summary(result),
            }
        )
    evidence["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    evidence["evidence_sha256"] = _sha256_json(evidence)
    _assert_safe_evidence(evidence, secret)
    _write_json_exclusive(args.output, evidence)
    print(
        f"M3-01 live smoke {evidence['status']}; evidence_sha256={evidence['evidence_sha256']}"
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
