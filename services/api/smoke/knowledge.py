"""M0-03: real openJiuwen Knowledge lifecycle probe on synthetic text."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import multiprocessing
import os
import platform
import stat
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from openjiuwen.core.retrieval import RetrievalConfig, SimpleKnowledgeBase
from pydantic import Field, field_validator

# Knowledge/Embedding 的构造权威只有一处（zhijue.adapters.knowledge）；
# 探针复用生产实现，避免出现"探针验证的组件"和"应用实际用的组件"两套。
from zhijue.adapters.knowledge import (
    SDK_COMPONENTS,
    KnowledgeSettings,
    build_embedding,
    build_knowledge_base,
)

TASK_ID = "M0-03"
SMOKE_VERSION = "1.0.0"
PHASES = ("ingest", "restart_check", "delete", "post_delete_check")


@dataclass(frozen=True)
class SyntheticProfile:
    key: str
    kb_id: str
    source_id: str
    file_name: str
    marker: str
    content: str
    query: str


PROFILES = (
    SyntheticProfile(
        key="profile_a",
        kb_id="m0_03_profile_a",
        source_id="synthetic_profile_a_v1",
        file_name="profile_a.txt",
        marker="ALPHA_UART_DMA_7391",
        content=(
            "这是 M0-03 合成测试资料，不是候选人事实。"
            "控制器 Alpha 通过 UART 与 DMA 传输周期遥测数据，"
            "唯一标记为 ALPHA_UART_DMA_7391。"
        ),
        query="哪个合成控制器使用 UART 和 DMA 传输周期遥测数据？",
    ),
    SyntheticProfile(
        key="profile_b",
        kb_id="m0_03_profile_b",
        source_id="synthetic_profile_b_v1",
        file_name="profile_b.txt",
        marker="BETA_CAN_STATE_2846",
        content=(
            "这是 M0-03 合成测试资料，不是候选人事实。"
            "控制器 Beta 使用 CAN 仲裁与非阻塞状态机处理节点通信，"
            "唯一标记为 BETA_CAN_STATE_2846。"
        ),
        query="哪个合成控制器使用 CAN 仲裁与非阻塞状态机？",
    ),
)


class KnowledgeSmokeSettings(KnowledgeSettings):
    """M0-03 探针设置：沿用生产环境契约，另加冻结模型与阶段超时约束。"""

    knowledge_phase_timeout: int = Field(default=180, ge=10, le=600)

    @field_validator("embedding_model")
    @classmethod
    def validate_frozen_model(cls, value: str) -> str:
        value = value.strip()
        if value != "BAAI/bge-m3":
            raise ValueError("M0-03 is frozen to BAAI/bge-m3")
        return value


def load_settings(env_file: Path) -> KnowledgeSmokeSettings:
    """只读一个显式私有 env 文件；绝不回退到隐式密钥。"""
    path = env_file.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("private env file does not exist")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(
            "private env file must not be accessible by group or others"
        )
    return KnowledgeSmokeSettings(_env_file=path, _env_file_encoding="utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
    path.chmod(0o600)


def assert_safe_evidence(value: Any, secret: str) -> None:
    """Reject accidental key or server-path disclosure before evidence is written."""
    if isinstance(value, dict):
        for nested in value.values():
            assert_safe_evidence(nested, secret)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            assert_safe_evidence(nested, secret)
        return
    if not isinstance(value, str):
        return
    if secret and secret in value:
        raise ValueError("evidence contains a secret")
    if value.startswith("/") or (len(value) > 2 and value[1:3] in {":\\", ":/"}):
        raise ValueError("evidence contains an absolute path")


def prepare_runtime(runtime_dir: Path) -> None:
    if runtime_dir.exists():
        raise FileExistsError("runtime directory already exists; choose a new path")
    runtime_dir.mkdir(parents=True, mode=0o700)
    runtime_dir.chmod(0o700)
    fixture_dir = runtime_dir / "fixtures"
    fixture_dir.mkdir(mode=0o700)
    for profile in PROFILES:
        target = fixture_dir / profile.file_name
        target.write_text(profile.content + "\n", encoding="utf-8")
        target.chmod(0o600)


async def parse_profile(
    kb: SimpleKnowledgeBase,
    fixture_path: Path,
    profile: SyntheticProfile,
):
    documents = await kb.parse_files([str(fixture_path)], file_name=profile.file_name)
    if len(documents) != 1 or not documents[0].text.strip():
        raise RuntimeError(
            f"{profile.key}: parser did not return exactly one non-empty document"
        )
    document = documents[0]
    if document.text.strip() != profile.content:
        raise RuntimeError(
            f"{profile.key}: parsed text differs from the source fixture"
        )
    source_hash = sha256_bytes(fixture_path.read_bytes())
    document.metadata.update(
        {
            "source_id": profile.source_id,
            "source_name": profile.file_name,
            "source_sha256": source_hash,
            "data_mode": "synthetic",
        }
    )
    return document, source_hash


def check_retrieval(
    profile: SyntheticProfile,
    source_hash: str,
    document_id: str,
    results: list[Any],
) -> dict[str, Any]:
    if not results:
        raise RuntimeError(f"{profile.key}: retrieval returned no result")
    top = results[0]
    metadata = top.metadata or {}
    if profile.marker not in top.text:
        raise RuntimeError(f"{profile.key}: retrieved text does not contain its marker")
    if top.doc_id != document_id or metadata.get("doc_id") != document_id:
        raise RuntimeError(f"{profile.key}: retrieval lost document provenance")
    if metadata.get("source_id") != profile.source_id:
        raise RuntimeError(
            f"{profile.key}: retrieval crossed the knowledge-base boundary"
        )
    if metadata.get("source_sha256") != source_hash:
        raise RuntimeError(f"{profile.key}: source hash provenance changed")
    if not metadata.get("chunk_id") or top.text not in profile.content:
        raise RuntimeError(f"{profile.key}: chunk provenance is incomplete")
    return {
        "hit_count": len(results),
        "document_id": document_id,
        "chunk_id_present": True,
        "source_id": profile.source_id,
        "source_sha256": source_hash,
        "retrieved_text_sha256": sha256_bytes(top.text.encode("utf-8")),
        "marker_found": True,
        "score": top.score,
    }


async def reject_missing_input(kb: SimpleKnowledgeBase, runtime_dir: Path) -> bool:
    missing = runtime_dir / "fixtures" / "does-not-exist.txt"
    documents = await kb.parse_files([str(missing)])
    if documents:
        raise RuntimeError("missing source was incorrectly accepted")
    return True


async def reject_duplicate(kb: SimpleKnowledgeBase, document: Any) -> bool:
    try:
        await kb.add_documents([document])
    except Exception as exc:  # SDK exception type is version-specific.
        message = str(exc)
        if "duplicate_doc_ids" not in message and "same doc_id" not in message:
            raise
        return True
    raise RuntimeError("duplicate document was incorrectly accepted")


async def run_ingest_phase(
    settings: KnowledgeSmokeSettings, runtime_dir: Path
) -> dict[str, Any]:
    database_path = runtime_dir / "knowledge.db"
    embedding = build_embedding(settings)
    dimension = await asyncio.to_thread(lambda: embedding.dimension)
    if dimension != settings.embedding_expected_dimension:
        raise RuntimeError(
            "embedding dimension does not match the frozen model contract"
        )

    profiles: dict[str, Any] = {}
    missing_input_rejected = False
    for profile in PROFILES:
        kb = build_knowledge_base(
            settings, database_path, profile.kb_id, embed_model=embedding
        )
        try:
            if not missing_input_rejected:
                missing_input_rejected = await reject_missing_input(kb, runtime_dir)
            fixture = runtime_dir / "fixtures" / profile.file_name
            document, source_hash = await parse_profile(kb, fixture, profile)
            document_ids = await kb.add_documents([document])
            if document_ids != [document.id_]:
                raise RuntimeError(
                    f"{profile.key}: add_documents returned unexpected IDs"
                )
            duplicate_rejected = await reject_duplicate(kb, document)
            results = await kb.retrieve(profile.query, RetrievalConfig(top_k=1))
            retrieval = check_retrieval(profile, source_hash, document.id_, results)
            profiles[profile.key] = {
                "kb_id": profile.kb_id,
                "document_id": document.id_,
                "source_id": profile.source_id,
                "source_name": profile.file_name,
                "source_sha256": source_hash,
                "parsed_text_sha256": sha256_bytes(document.text.encode("utf-8")),
                "parsed_non_empty": True,
                "duplicate_rejected": duplicate_rejected,
                "retrieval": retrieval,
            }
        finally:
            await kb.close()

    state = {"profiles": profiles, "embedding_dimension": dimension}
    write_json_exclusive(runtime_dir / "state.json", state)
    return {
        "status": "passed",
        "pid": os.getpid(),
        "embedding_dimension": dimension,
        "embedding_logical_calls": 5,
        "missing_input_rejected": missing_input_rejected,
        "profiles": profiles,
    }


def load_state(runtime_dir: Path) -> dict[str, Any]:
    with (runtime_dir / "state.json").open(encoding="utf-8") as source:
        return json.load(source)


async def run_restart_phase(
    settings: KnowledgeSmokeSettings, runtime_dir: Path
) -> dict[str, Any]:
    state = load_state(runtime_dir)
    embedding = build_embedding(settings)
    results_by_profile = {}
    for profile in PROFILES:
        stored = state["profiles"][profile.key]
        kb = build_knowledge_base(
            settings, runtime_dir / "knowledge.db", profile.kb_id, embed_model=embedding
        )
        try:
            results = await kb.retrieve(profile.query, RetrievalConfig(top_k=1))
            results_by_profile[profile.key] = check_retrieval(
                profile,
                stored["source_sha256"],
                stored["document_id"],
                results,
            )
        finally:
            await kb.close()
    if embedding.dimension != settings.embedding_expected_dimension:
        raise RuntimeError("restart embedding dimension changed")
    return {
        "status": "passed",
        "pid": os.getpid(),
        "embedding_logical_calls": 2,
        "profiles": results_by_profile,
    }


async def run_delete_phase(
    settings: KnowledgeSmokeSettings, runtime_dir: Path
) -> dict[str, Any]:
    state = load_state(runtime_dir)
    deleted = {}
    for profile in PROFILES:
        kb = build_knowledge_base(settings, runtime_dir / "knowledge.db", profile.kb_id)
        try:
            document_id = state["profiles"][profile.key]["document_id"]
            success = await kb.delete_documents([document_id])
            if not success:
                raise RuntimeError(f"{profile.key}: openJiuwen delete_documents failed")
            kb.index_manager.client.flush(f"kb_{profile.kb_id}_chunks")
            deleted[profile.key] = {"document_id": document_id, "deleted": True}
        finally:
            await kb.close()
    return {
        "status": "passed",
        "pid": os.getpid(),
        "embedding_logical_calls": 0,
        "profiles": deleted,
    }


async def run_post_delete_phase(
    settings: KnowledgeSmokeSettings, runtime_dir: Path
) -> dict[str, Any]:
    embedding = build_embedding(settings)
    profiles = {}
    total_hits = 0
    for profile in PROFILES:
        kb = build_knowledge_base(
            settings, runtime_dir / "knowledge.db", profile.kb_id, embed_model=embedding
        )
        try:
            results = await kb.retrieve(profile.query, RetrievalConfig(top_k=1))
            if results:
                raise RuntimeError(
                    f"{profile.key}: deleted content remained retrievable"
                )
            profiles[profile.key] = {"post_restart_hits": 0}
        finally:
            await kb.close()
    return {
        "status": "passed",
        "pid": os.getpid(),
        "embedding_logical_calls": 2,
        "post_restart_hits": total_hits,
        "profiles": profiles,
    }


async def dispatch_phase(
    phase: str, settings: KnowledgeSmokeSettings, runtime_dir: Path
) -> dict[str, Any]:
    if phase == "ingest":
        return await run_ingest_phase(settings, runtime_dir)
    if phase == "restart_check":
        return await run_restart_phase(settings, runtime_dir)
    if phase == "delete":
        return await run_delete_phase(settings, runtime_dir)
    if phase == "post_delete_check":
        return await run_post_delete_phase(settings, runtime_dir)
    raise ValueError(f"unknown phase: {phase}")


def sanitized_error(
    exc: BaseException, settings: KnowledgeSmokeSettings, runtime_dir: Path
) -> str:
    message = str(exc).replace(
        settings.embedding_api_key.get_secret_value(), "<redacted>"
    )
    message = message.replace(str(runtime_dir.resolve()), "<runtime>")
    return message[:1000]


def safe_exception_chain(exc: BaseException) -> list[dict[str, Any]]:
    """Expose only diagnostic type/status/route, never response bodies or queries."""
    chain = []
    current: BaseException | None = exc
    seen = set()
    while current is not None and id(current) not in seen and len(chain) < 6:
        seen.add(id(current))
        detail: dict[str, Any] = {"type": type(current).__name__}
        response = getattr(current, "response", None)
        if response is not None:
            detail["http_status"] = getattr(response, "status_code", None)
            request = getattr(response, "request", None)
            request_url = getattr(request, "url", None)
            if request_url:
                parsed = urlsplit(str(request_url))
                detail["endpoint"] = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            request_method = getattr(request, "method", None)
            if request_method:
                detail["method"] = request_method
        chain.append(detail)
        current = current.__cause__ or current.__context__
    return chain


def phase_worker(
    phase: str, env_file: Path, runtime_dir: Path, result_file: Path
) -> None:
    os.umask(0o077)
    settings = load_settings(env_file)
    try:
        result = asyncio.run(dispatch_phase(phase, settings, runtime_dir))
    except Exception as exc:  # noqa: BLE001 - process boundary records a sanitized failure.
        result = {
            "status": "failed",
            "pid": os.getpid(),
            "error_type": type(exc).__name__,
            "error_message": sanitized_error(exc, settings, runtime_dir),
            "error_chain": safe_exception_chain(exc),
        }
        write_json_exclusive(result_file, result)
        raise SystemExit(1) from None
    write_json_exclusive(result_file, result)


def run_phase_process(
    phase: str,
    settings: KnowledgeSmokeSettings,
    env_file: Path,
    runtime_dir: Path,
) -> dict[str, Any]:
    result_file = runtime_dir / f"phase-{phase}.json"
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=phase_worker,
        args=(phase, env_file, runtime_dir, result_file),
        name=f"knowledge-{phase}",
    )
    process.start()
    process.join(settings.knowledge_phase_timeout)
    if process.is_alive():
        process.terminate()
        process.join(10)
        raise TimeoutError(f"Knowledge phase timed out: {phase}")
    if not result_file.is_file():
        raise RuntimeError(f"Knowledge phase produced no result: {phase}")
    with result_file.open(encoding="utf-8") as source:
        result = json.load(source)
    if process.exitcode != 0 or result.get("status") != "passed":
        error_type = result.get("error_type", "UnknownError")
        error_message = result.get("error_message", "no error detail")
        error_chain = result.get("error_chain", [])
        raise RuntimeError(
            f"Knowledge phase {phase} failed: {error_type}: {error_message}; "
            f"diagnostics={error_chain}"
        )
    return result


def sdk_sources() -> dict[str, Any]:
    entries = SDK_COMPONENTS
    return {
        entry.__name__: {
            "module": entry.__module__,
            "sha256": sha256_bytes(Path(inspect.getfile(entry)).read_bytes()),
        }
        for entry in entries
    }


def assemble_evidence(
    settings: KnowledgeSmokeSettings,
    phases: dict[str, dict[str, Any]],
    started_at: str,
) -> dict[str, Any]:
    pids = [phases[name]["pid"] for name in PHASES]
    calls = sum(phases[name]["embedding_logical_calls"] for name in PHASES)
    ingest = phases["ingest"]
    evidence = {
        "task_id": TASK_ID,
        "smoke_version": SMOKE_VERSION,
        "status": "passed",
        "run_mode": "live",
        "data_mode": "synthetic",
        "native_openjiuwen_knowledge": True,
        "versions": {
            "python": platform.python_version(),
            "openjiuwen": version("openjiuwen"),
            "pymilvus": version("pymilvus"),
            "milvus_lite": version("milvus-lite"),
        },
        "embedding": {
            **settings.public_summary(),
            "actual_dimension": ingest["embedding_dimension"],
            "logical_calls": calls,
            "http_requests": None,
            "tokens": None,
            "cost": None,
        },
        "storage": {
            "backend": "Milvus Lite",
            "index": "FLAT",
            "distance_metric": "cosine",
            "database_persisted": True,
        },
        "parsing": {
            "parser": "openjiuwen.core.retrieval.indexing.processor.parser.TxtMdParser",
            "profile_count": len(PROFILES),
            "all_non_empty": True,
            "missing_input_rejected": ingest["missing_input_rejected"],
        },
        "provenance": {
            key: {
                "document_id": value["document_id"],
                "source_id": value["source_id"],
                "source_sha256": value["source_sha256"],
                "retrieved_text_sha256": value["retrieval"]["retrieved_text_sha256"],
                "chunk_id_present": value["retrieval"]["chunk_id_present"],
            }
            for key, value in ingest["profiles"].items()
        },
        "isolation": {
            "knowledge_base_count": len(PROFILES),
            "all_retrieved_source_ids_matched": True,
        },
        "persistence": {
            "phase_pids": pids,
            "distinct_process_count": len(set(pids)),
            "restart_retrieval_passed": True,
        },
        "deletion": {
            "openjiuwen_delete_documents_passed": True,
            "post_restart_hits": phases["post_delete_check"]["post_restart_hits"],
        },
        "guards": {
            "duplicate_document_rejected": all(
                item["duplicate_rejected"] for item in ingest["profiles"].values()
            ),
            "phase_timeout_seconds": settings.knowledge_phase_timeout,
            "max_retries": settings.embedding_max_retries,
        },
        "sdk_sources": sdk_sources(),
        "mocked_sdk": False,
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    evidence["evidence_sha256"] = canonical_hash(evidence)
    return evidence


def run_lifecycle(env_file: Path, runtime_dir: Path) -> dict[str, Any]:
    """Run four phases in four fresh OS processes against one persisted Lite DB."""
    os.umask(0o077)
    env_file = env_file.expanduser().resolve()
    runtime_dir = runtime_dir.expanduser().resolve()
    settings = load_settings(env_file)
    prepare_runtime(runtime_dir)
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    phases = {
        phase: run_phase_process(phase, settings, env_file, runtime_dir)
        for phase in PHASES
    }
    evidence = assemble_evidence(settings, phases, started_at)
    if evidence["persistence"]["distinct_process_count"] != len(PHASES):
        raise RuntimeError("restart proof did not use distinct processes")
    assert_safe_evidence(evidence, settings.embedding_api_key.get_secret_value())
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new evidence path")
    evidence = run_lifecycle(args.env_file, args.runtime_dir)
    write_json_exclusive(args.output, evidence)
    print(
        "M0-03 passed; "
        f"dimension={evidence['embedding']['actual_dimension']}; "
        f"evidence_sha256={evidence['evidence_sha256']}"
    )


if __name__ == "__main__":
    main()
