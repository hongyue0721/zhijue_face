"""M0-03 tests for the real openJiuwen Knowledge lifecycle probe."""

import asyncio
import json
import os
from importlib.metadata import distribution
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from openjiuwen.core.retrieval import SimpleKnowledgeBase, VectorStoreConfig
from openjiuwen.core.retrieval.embedding.openai_embedding import OpenAIEmbedding
from openjiuwen.core.retrieval.indexing.indexer.milvus_indexer import MilvusIndexer
from openjiuwen.core.retrieval.vector_store.milvus_store import MilvusVectorStore
from pydantic import ValidationError

from smoke.knowledge import (
    KnowledgeSmokeSettings,
    assert_safe_evidence,
    build_knowledge_base,
    load_settings,
    run_lifecycle,
    safe_exception_chain,
    write_json_exclusive,
)


def valid_settings(**overrides) -> KnowledgeSmokeSettings:
    values = {
        "embedding_provider": "openjiuwen_api",
        "embedding_model": "BAAI/bge-m3",
        "embedding_api_base": "https://api.rinko.ai/v1",
        "embedding_api_key": "unit-test-secret",
        "embedding_timeout": 15,
        "embedding_max_retries": 1,
        "embedding_expected_dimension": 1024,
        "knowledge_phase_timeout": 60,
    }
    values.update(overrides)
    return KnowledgeSmokeSettings(**values)


def test_native_knowledge_constructs_on_lite(tmp_path):
    settings = valid_settings()
    kb = build_knowledge_base(settings, tmp_path / "knowledge.db", "native_probe")
    try:
        assert type(kb) is SimpleKnowledgeBase
        assert type(kb.vector_store) is MilvusVectorStore
        assert type(kb.index_manager) is MilvusIndexer
        assert type(kb.embed_model) is OpenAIEmbedding
    finally:
        asyncio.run(kb.close())


VALIDATED_OPENJIUWEN_COMMIT = "72c4985111b835530ec616f70dd67117eb2e015c"
VALIDATED_OPENJIUWEN_REPOSITORY = "https://github.com/hongyue0721/agent-core.git"


def test_installed_openjiuwen_uses_validated_compatibility_commit():
    direct_url_text = distribution("openjiuwen").read_text("direct_url.json")
    assert direct_url_text is not None
    direct_url = json.loads(direct_url_text)
    assert direct_url["url"] == VALIDATED_OPENJIUWEN_REPOSITORY
    assert direct_url["vcs_info"]["commit_id"] == VALIDATED_OPENJIUWEN_COMMIT
    assert direct_url["vcs_info"]["requested_revision"] == VALIDATED_OPENJIUWEN_COMMIT


@pytest.mark.parametrize(
    ("delete_result", "expected"),
    [(["pk-1", "pk-2"], True), ([], False)],
)
def test_milvus_lite_delete_return_shape_is_supported(delete_result, expected):
    target = (
        "openjiuwen.core.retrieval.indexing.indexer.milvus_indexer."
        "MilvusVectorStore.create_client"
    )
    with patch(target) as create_client:
        client = MagicMock()
        client.delete.return_value = delete_result
        create_client.return_value = client
        indexer = MilvusIndexer(
            config=VectorStoreConfig(
                store_provider="milvus", collection_name="test_collection"
            ),
            milvus_uri="http://localhost:19530",
        )
        assert asyncio.run(indexer.delete_index("doc_1", "test_index")) is expected


def test_settings_require_exact_supported_provider():
    with pytest.raises(ValidationError):
        valid_settings(embedding_provider="local_fake")


def test_settings_require_https_embedding_endpoint():
    with pytest.raises(ValidationError):
        valid_settings(embedding_api_base="http://api.rinko.ai/embeddings")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.rinko.ai",
        "https://api.rinko.ai/embeddings",
        "https://api.rinko.ai/embeddings?token=unsafe",
        "https://user:pass@api.rinko.ai/embeddings",
    ],
)
def test_settings_do_not_guess_or_accept_unsafe_embedding_endpoint(url):
    with pytest.raises(ValidationError):
        valid_settings(embedding_api_base=url)


def test_settings_bound_timeout_and_retries():
    with pytest.raises(ValidationError):
        valid_settings(embedding_timeout=0)
    with pytest.raises(ValidationError):
        valid_settings(embedding_max_retries=0)
    with pytest.raises(ValidationError):
        valid_settings(embedding_max_retries=4)


def test_load_settings_rejects_group_readable_secret_file(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "EMBEDDING_PROVIDER=openjiuwen_api\n"
        "EMBEDDING_MODEL=BAAI/bge-m3\n"
        "EMBEDDING_API_BASE=https://api.rinko.ai/v1\n"
        "EMBEDDING_API_KEY=not-a-real-key\n",
        encoding="utf-8",
    )
    env_file.chmod(0o644)
    with pytest.raises(PermissionError):
        load_settings(env_file)


def test_load_settings_reads_private_file_without_exposing_key(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "EMBEDDING_PROVIDER=openjiuwen_api\n"
        "EMBEDDING_MODEL=BAAI/bge-m3\n"
        "EMBEDDING_API_BASE=https://api.rinko.ai/v1\n"
        "EMBEDDING_API_KEY=not-a-real-key\n"
        "EMBEDDING_TIMEOUT=15\n"
        "EMBEDDING_MAX_RETRIES=1\n"
        "EMBEDDING_EXPECTED_DIMENSION=1024\n"
        "KNOWLEDGE_PHASE_TIMEOUT=60\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    settings = load_settings(env_file)
    assert settings.embedding_model == "BAAI/bge-m3"
    assert "not-a-real-key" not in repr(settings)
    assert "not-a-real-key" not in json.dumps(settings.public_summary())


def test_write_json_exclusive_refuses_overwrite(tmp_path):
    target = tmp_path / "evidence.json"
    write_json_exclusive(target, {"status": "first"})
    with pytest.raises(FileExistsError):
        write_json_exclusive(target, {"status": "second"})


def test_exception_diagnostics_keep_status_but_drop_query_and_body():
    response = requests.Response()
    response.status_code = 401
    response._content = b"server-body-must-not-be-recorded"
    response.request = requests.Request(
        "POST", "https://api.example.test/embeddings?token=must-not-leak"
    ).prepare()
    cause = requests.HTTPError("request failed", response=response)
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = cause
    diagnostics = safe_exception_chain(wrapper)
    encoded = json.dumps(diagnostics)
    assert diagnostics[-1]["http_status"] == 401
    assert diagnostics[-1]["endpoint"] == "https://api.example.test/embeddings"
    assert "must-not-leak" not in encoded
    assert "server-body" not in encoded


def test_evidence_guard_rejects_secret_and_absolute_path(tmp_path):
    secret = "unit-test-secret"
    assert_safe_evidence({"status": "passed", "source_id": "synthetic_a"}, secret)
    with pytest.raises(ValueError, match="secret"):
        assert_safe_evidence({"detail": f"prefix-{secret}"}, secret)
    with pytest.raises(ValueError, match="absolute path"):
        assert_safe_evidence(
            {"path": str((tmp_path / "private.txt").resolve())}, secret
        )


@pytest.mark.integration_live
def test_real_knowledge_lifecycle_when_private_env_is_explicit(tmp_path):
    env_value = os.getenv("ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE")
    if not env_value:
        pytest.skip("private live env file not explicitly selected")
    evidence = run_lifecycle(
        env_file=Path(env_value),
        runtime_dir=tmp_path / "knowledge-live",
    )
    assert evidence["status"] == "passed"
    assert evidence["native_openjiuwen_knowledge"] is True
    assert evidence["persistence"]["distinct_process_count"] == 4
    assert evidence["deletion"]["post_restart_hits"] == 0
