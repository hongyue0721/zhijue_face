"""M4-02: real coaching and resume model calls through openJiuwen Workflow."""

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
    COACHING_SYSTEM_PROMPT,
    RESUME_SYSTEM_PROMPT,
    OpenAICompatibleContentGenerator,
    load_model_settings,
)
from zhijue.application.answer_workflow import AnalysisResult
from zhijue.application.content_workflow import run_grounded_content_workflow
from zhijue.domain.grounded_content import (
    validate_coaching_candidate,
    validate_resume_candidate,
)

TASK_ID = "M4-02"
SMOKE_VERSION = "1.0.0"
REPORT_ID = "report_m4_02_content_live"
ROOT_QUESTION_ID = "question_m4_02_content_live"
ANSWER_ID = "answer_m4_02_content_live"
DRAFT_ID = "resume_m4_02_content_live"
CLAIM_ONE_ID = "claim_m4_02_content_live_one"
CLAIM_TWO_ID = "claim_m4_02_content_live_two"
ANSWER_TEXT = (
    "串口接收出现偶发错帧时，我先记录复现条件和错误状态，再对照 UART 日志与逻辑分析仪结果，"
    "区分问题发生在串口接收还是后续数据处理。"
)
CLAIMS = {
    CLAIM_ONE_ID: (
        "在嵌入式项目中参与 STM32 HAL 外设开发，使用 UART、SPI 与 CAN 完成设备通信联调。"
    ),
    CLAIM_TWO_ID: (
        "使用 FreeRTOS Queue 在 ESP32-S3 项目中传递任务间消息，参与状态机与周期任务调试。"
    ),
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
            if (parent / "contracts" / "coaching-result.schema.json").is_file()
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


def _payloads() -> dict[str, dict[str, Any]]:
    return {
        "coach_answers": {
            "report_id": REPORT_ID,
            "answers_by_root": {
                ROOT_QUESTION_ID: {ANSWER_ID: ANSWER_TEXT},
            },
            "root_questions": {
                ROOT_QUESTION_ID: "你如何排查串口接收中的偶发错帧？",
            },
            "allowed_claims": CLAIMS,
        },
        "compose_resume": {
            "draft_id": DRAFT_ID,
            "allowed_claims": CLAIMS,
            "target_context": {
                "kind": "synthetic_demo_jd",
                "source_name": "SYNTHETIC_DEMO_JD",
                "raw_text": "嵌入式软件开发实习生，关注外设通信、实时任务与调试取证。",
            },
        },
    }


class _RecordingContentGenerator:
    """Keep one synthetic raw result for ignored diagnostic evidence."""

    def __init__(self, generator: OpenAICompatibleContentGenerator) -> None:
        self._generator = generator
        self.last_result: AnalysisResult | None = None

    async def generate(self, *, task: str, payload: dict[str, Any]) -> AnalysisResult:
        result = await self._generator.generate(task=task, payload=payload)
        self.last_result = result
        return result


def _diagnose_failed_candidate(
    *,
    task: str,
    payload: dict[str, Any],
    result: AnalysisResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    diagnostic: dict[str, Any] = {
        "usage": result.usage(),
        "raw_content_sha256": _sha256_bytes(result.content.encode("utf-8")),
    }
    try:
        candidate = json.loads(result.content)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        diagnostic["validation_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return diagnostic
    diagnostic["candidate"] = candidate
    try:
        if task == "coach_answers":
            validate_coaching_candidate(
                candidate,
                report_id=payload["report_id"],
                answers_by_root=payload["answers_by_root"],
                allowed_claims=payload["allowed_claims"],
            )
        else:
            validate_resume_candidate(
                candidate,
                draft_id=payload["draft_id"],
                allowed_claims=payload["allowed_claims"],
            )
    except Exception as exc:  # noqa: BLE001 - ignored diagnostic boundary.
        diagnostic["validation_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    else:
        diagnostic["validation_error"] = None
    return diagnostic


def _source_hashes(root: Path) -> dict[str, str]:
    return {
        "coaching_schema_sha256": _sha256_bytes(
            (root / "contracts" / "coaching-result.schema.json").read_bytes()
        ),
        "resume_schema_sha256": _sha256_bytes(
            (root / "contracts" / "resume-draft-result.schema.json").read_bytes()
        ),
        "workflow_source_sha256": _sha256_bytes(
            Path(inspect.getfile(run_grounded_content_workflow)).read_bytes()
        ),
        "model_adapter_source_sha256": _sha256_bytes(
            Path(inspect.getfile(OpenAICompatibleContentGenerator)).read_bytes()
        ),
    }


def _base_evidence(env_file: Path) -> tuple[dict[str, Any], str]:
    settings = load_model_settings(env_file)
    payloads = _payloads()
    evidence = {
        "task_id": TASK_ID,
        "smoke_version": SMOKE_VERSION,
        "status": "running",
        "run_mode": "live",
        "data_mode": "synthetic",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": settings.public_summary(),
        "execution_policy": {
            "tasks": ["coach_answers", "compose_resume"],
            "one_http_request_per_task": True,
            "automatic_retry": False,
        },
        "input": {
            "answer_sha256": _sha256_bytes(ANSWER_TEXT.encode("utf-8")),
            "claims_sha256": _sha256_json(CLAIMS),
            "payload_sha256": {
                task: _sha256_json(payload) for task, payload in payloads.items()
            },
            "answer_characters": len(ANSWER_TEXT),
            "claim_count": len(CLAIMS),
        },
        "versions": {
            "python": platform.python_version(),
            "openjiuwen": version("openjiuwen"),
            "coaching_prompt_sha256": _sha256_bytes(
                COACHING_SYSTEM_PROMPT.encode("utf-8")
            ),
            "resume_prompt_sha256": _sha256_bytes(RESUME_SYSTEM_PROMPT.encode("utf-8")),
        },
        "source_hashes": _source_hashes(_repo_root()),
        "workflow": {
            "sdk_class": f"{Workflow.__module__}.{Workflow.__name__}",
            "graph": "Start->Generator->SemanticValidation->End",
            "mocked_sdk": False,
            "mocked_model": False,
            "knowledge_retrieval": "NOT_RUN_THIS_SMOKE",
        },
        "tasks": {},
        "cost": {
            "value": None,
            "currency": None,
            "status": "NOT_MEASURED",
        },
    }
    return evidence, settings.api_key.get_secret_value()


async def _run_live(env_file: Path, evidence: dict[str, Any]) -> None:
    settings = load_model_settings(env_file)
    request_count = 0

    async def count_request(_request: httpx.Request) -> None:
        nonlocal request_count
        request_count += 1

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.model_timeout),
        follow_redirects=False,
        trust_env=False,
        event_hooks={"request": [count_request]},
    ) as client:
        transport = OpenAICompatibleContentGenerator(settings, client=client)
        for task, payload in _payloads().items():
            generator = _RecordingContentGenerator(transport)
            started = time.perf_counter()
            requests_before = request_count
            try:
                result = await run_grounded_content_workflow(
                    generator=generator,
                    task=task,
                    payload=payload,
                    timeout_seconds=settings.model_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - evidence boundary.
                evidence["tasks"][task] = {
                    "status": "failed",
                    "http_attempts": request_count - requests_before,
                    "duration_seconds": round(time.perf_counter() - started, 6),
                    "failure": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
                diagnostic = _diagnose_failed_candidate(
                    task=task,
                    payload=payload,
                    result=generator.last_result,
                )
                if diagnostic is not None:
                    evidence["tasks"][task]["diagnostic"] = diagnostic
            else:
                candidate = result["candidate"]
                evidence["tasks"][task] = {
                    "status": "passed",
                    "http_attempts": request_count - requests_before,
                    "duration_seconds": round(time.perf_counter() - started, 6),
                    "usage": result["usage"],
                    "candidate_sha256": _sha256_json(candidate),
                    "candidate": candidate,
                }
    evidence["http_attempts"] = request_count
    evidence["logical_model_calls"] = len(_payloads())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new evidence path")

    _configure_private_sdk_logging()
    evidence, secret = _base_evidence(args.env_file)
    started = time.perf_counter()
    asyncio.run(_run_live(args.env_file, evidence))
    task_results = list(evidence["tasks"].values())
    evidence["status"] = (
        "passed"
        if len(task_results) == 2
        and all(result["status"] == "passed" for result in task_results)
        else "failed"
    )
    evidence["duration_seconds"] = round(time.perf_counter() - started, 6)
    evidence["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    evidence["evidence_sha256"] = _sha256_json(evidence)
    _assert_safe_evidence(evidence, secret)
    _write_json_exclusive(args.output, evidence)
    print(
        f"M4-02 content live smoke {evidence['status']}; "
        f"evidence_sha256={evidence['evidence_sha256']}"
    )
    raise SystemExit(0 if evidence["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
