"""岗位知识包字节级契约回归（主文件 Phase 2 / Gate 2 / B01–B03、B08–B10、C04）。

约定：内置包目录是资产真源；这里所有断言只使用仓库内文件与内存构造，
不发任何网络/模型请求（AGENTS §2 live/fixture 分界）。
"""

from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path

import pytest

from zhijue.application.seed_bank import load_seed_bank
from zhijue.domain.competency_profiles import (
    EMBEDDED_JUNIOR_V1,
    CompetencyProfileError,
    match_registered_profile,
)
from zhijue.domain.knowledge_packs import (
    MANIFEST_FILE,
    SOURCES_FILE,
    PackValidationError,
    canonicalize_file_bytes,
    compute_content_digest,
    parse_competencies,
    parse_manifest,
    parse_sources,
    release_id_for,
    safe_extract_zip,
    strict_json_loads,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_PACK_DIR = REPO_ROOT / "knowledge_packs" / "embedded_software_junior"


def builtin_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(BUILTIN_PACK_DIR.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(BUILTIN_PACK_DIR))
            files[rel] = path.read_bytes()
    return files


def canonical_from(raw_files: dict[str, bytes]) -> dict[str, bytes]:
    return {
        path: canonicalize_file_bytes(data, path=path)
        for path, data in raw_files.items()
    }


def zip_from(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def pack_digest(files: dict[str, bytes]) -> str:
    manifest = parse_manifest(files)
    digest, _index = compute_content_digest(
        pack_id=manifest.pack_id, version=manifest.version, files=files
    )
    return digest


# --- B01/B02：内置包完整通过契约，Seed 迁移不改变内容 ------------------------


def test_builtin_pack_passes_full_contract() -> None:
    files = canonical_from(builtin_files())
    manifest = parse_manifest(files)
    assert manifest.pack_id == "embedded-software-junior"
    assert len(manifest.seeds) == 6
    profile = match_registered_profile(parse_competencies(files))
    assert profile.profile_id == "embedded-junior-v1"
    sources = parse_sources(files)
    seed_payloads = {
        path: strict_json_loads(files[path].decode("utf-8"), path=path)
        for path in manifest.seeds
    }
    from zhijue.domain.knowledge_packs import assert_seed_reference_ids_resolve

    assert_seed_reference_ids_resolve(seed_payloads, sources)


def test_builtin_seeds_bytes_moved_not_rewritten() -> None:
    """B02：迁移只改目录位置；ID/版本/短指纹必须保持已验收原值。"""
    bank = load_seed_bank(BUILTIN_PACK_DIR / "seeds")
    assert len(bank) == 6
    assert bank.version_fingerprint() == "1c6716b90449d375"
    assert {seed.id for seed in bank.seeds} == {
        "seed_embedded_freertos_queue_mechanism",
        "seed_embedded_interrupt_priority",
        "seed_embedded_mutex_vs_semaphore",
        "seed_embedded_rtos_task_period",
        "seed_embedded_spi_i2c_selection",
        "seed_embedded_uart_dma_debug",
    }
    assert all(seed.version == "0.2.1" for seed in bank.seeds)


# --- 摘要规则（R04/B08/B10） --------------------------------------------------


def test_content_digest_ignores_zip_order_and_timestamps() -> None:
    files = canonical_from(builtin_files())
    digest = pack_digest(files)
    # 打包顺序完全颠倒、内容不变：同一 release 身份（B08）。
    reversed_zip = zip_from(dict(reversed(list(files.items()))))
    repacked_files = safe_extract_zip(reversed_zip, limits_default())
    assert pack_digest(repacked_files) == digest
    assert release_id_for(digest) == release_id_for(pack_digest(repacked_files))


def test_body_edit_without_version_bump_detected_by_digest_not_fingerprint(
    tmp_path,
) -> None:
    """R04/B10：旧短指纹只含 id/version，对正文篡改失明；完整摘要必须捕捉。"""
    files = canonical_from(builtin_files())
    seed_name = "seed_embedded_uart_dma_debug.json"
    seed_path = "seeds/" + seed_name
    seed = json.loads(files[seed_path].decode("utf-8"))
    assert seed["version"] == "0.2.1"
    seed["stem"] += "（未改版本号的内容篡改）"
    payload = json.dumps(seed, ensure_ascii=False, indent=2).encode("utf-8")
    mutated_dir = tmp_path / "seeds"
    mutated_dir.mkdir()
    for path, data in files.items():
        if not path.startswith("seeds/"):
            continue
        name = path.removeprefix("seeds/")
        (mutated_dir / name).write_bytes(payload if name == seed_name else data)
    original_bank = load_seed_bank(BUILTIN_PACK_DIR / "seeds")
    mutated_bank = load_seed_bank(mutated_dir)
    assert len(mutated_bank) == 6
    assert original_bank.version_fingerprint() == mutated_bank.version_fingerprint()
    mutated_files = dict(files)
    mutated_files[seed_path] = payload
    assert pack_digest(mutated_files) != pack_digest(files)


def test_crlf_variant_normalizes_to_same_digest() -> None:
    raw = builtin_files()
    files_a = canonical_from(raw)
    crlf_variant = {path: data.replace(b"\n", b"\r\n") for path, data in raw.items()}
    files_b = canonical_from(crlf_variant)
    assert files_a == files_b


def limits_default():
    from zhijue.domain.knowledge_packs import PackLimits

    return PackLimits()


# --- B03/声明式校验：负例必须明确失败，不产生可用半包 ------------------------


def _corrupt(files: dict[str, bytes], path: str, payload: dict) -> dict[str, bytes]:
    out = dict(files)
    out[path] = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return out


def test_missing_manifest_rejected() -> None:
    raw = builtin_files()
    # 完整内置包必须是可安全解压的正例（前提校验）。
    assert MANIFEST_FILE in safe_extract_zip(zip_from(raw), limits_default())
    bad = {path: data for path, data in raw.items() if path != MANIFEST_FILE}
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(zip_from(bad), limits_default())
    assert excinfo.value.code == "PACK_MANIFEST_MISSING"


def test_undeclared_extra_file_rejected() -> None:
    files = canonical_from(builtin_files())
    extra = dict(files)
    extra["notes.txt"] = b"hello\n"
    with pytest.raises(PackValidationError) as excinfo:
        parse_manifest(extra)
    assert excinfo.value.code == "PACK_UNDECLARED_FILE"


def test_declared_seed_missing_rejected() -> None:
    files = canonical_from(builtin_files())
    missing = {
        path: data for path, data in files.items() if "freertos_queue" not in path
    }
    with pytest.raises(PackValidationError) as excinfo:
        parse_manifest(missing)
    assert excinfo.value.code == "PACK_SEED_FILE_MISSING"


def test_unknown_format_version_rejected() -> None:
    files = canonical_from(builtin_files())
    manifest = json.loads(files[MANIFEST_FILE])
    manifest["format_version"] = "9.9"
    with pytest.raises(PackValidationError):
        parse_manifest(_corrupt(files, MANIFEST_FILE, manifest))


def test_unknown_competency_profile_rejected_not_defaulted() -> None:
    """C04：未登记 profile 明确拒绝，不套用嵌入式关键词兜底。"""
    declared = EMBEDDED_JUNIOR_V1.as_declared_dict()
    declared["competency_profile_id"] = "java-backend-v1"
    with pytest.raises(CompetencyProfileError) as excinfo:
        match_registered_profile(declared)
    assert excinfo.value.code == "COMPETENCY_PROFILE_UNSUPPORTED"


def test_competency_mirror_tampering_rejected() -> None:
    declared = EMBEDDED_JUNIOR_V1.as_declared_dict()
    declared["jd_keyword_rules"][0]["keywords"].append("rust")
    with pytest.raises(CompetencyProfileError) as excinfo:
        match_registered_profile(declared)
    assert excinfo.value.code == "PACK_PROFILE_MISMATCH"


def test_dangling_reference_id_rejected() -> None:
    from zhijue.domain.knowledge_packs import assert_seed_reference_ids_resolve

    files = canonical_from(builtin_files())
    sources = parse_sources(files)
    manifest = parse_manifest(files)
    seed_payloads = {
        path: strict_json_loads(files[path].decode("utf-8"), path=path)
        for path in manifest.seeds
    }
    poisoned_path = next(iter(seed_payloads))
    poisoned = {
        poisoned_path: {"reference_ids": ["nonexistent_source"], "reference_points": []}
    }
    with pytest.raises(PackValidationError) as excinfo:
        assert_seed_reference_ids_resolve(poisoned, sources)
    assert excinfo.value.code == "PACK_REFERENCE_UNRESOLVED"


def test_duplicate_source_id_and_unsafe_url_rejected() -> None:
    files = canonical_from(builtin_files())
    sources_payload = json.loads(files[SOURCES_FILE])
    sources_payload["sources"].append(copy.deepcopy(sources_payload["sources"][0]))
    with pytest.raises(PackValidationError) as excinfo:
        parse_sources(_corrupt(files, SOURCES_FILE, sources_payload))
    assert excinfo.value.code == "PACK_SOURCE_DUPLICATE_ID"

    javascript_url = copy.deepcopy(json.loads(files[SOURCES_FILE]))
    javascript_url["sources"][0]["url"] = "javascript:alert(1)"
    with pytest.raises(PackValidationError) as excinfo:
        parse_sources(_corrupt(files, SOURCES_FILE, javascript_url))
    assert excinfo.value.code == "PACK_SOURCE_URL_UNSAFE"

    no_locator = copy.deepcopy(json.loads(files[SOURCES_FILE]))
    no_locator["sources"][0]["url"] = None
    no_locator["sources"][0]["local_identifier"] = None
    with pytest.raises(PackValidationError) as excinfo:
        parse_sources(_corrupt(files, SOURCES_FILE, no_locator))
    assert excinfo.value.code == "PACK_SOURCE_UNLOCATABLE"


# --- 严格 JSON 与 Schema 拒绝 --------------------------------------------------


def test_duplicate_json_key_rejected() -> None:
    with pytest.raises(PackValidationError) as excinfo:
        strict_json_loads('{"a": 1, "a": 2}', path="x.json")
    assert excinfo.value.code == "PACK_JSON_DUPLICATE_KEY"


def test_nan_and_depth_rejected() -> None:
    with pytest.raises(PackValidationError):
        strict_json_loads("[NaN]", path="x.json")
    deep = "[]"
    for _ in range(12):
        deep = f"[{deep}]"
    with pytest.raises(PackValidationError) as excinfo:
        strict_json_loads(deep, path="x.json")
    assert excinfo.value.code == "PACK_JSON_TOO_DEEP"


def test_bom_rejected_in_canonicalization() -> None:
    with pytest.raises(PackValidationError) as excinfo:
        canonicalize_file_bytes(b"\xef\xbb\xbf{}", path="manifest.json")
    assert excinfo.value.code == "PACK_BOM_FORBIDDEN"


def test_schema_mismatch_extra_field_rejected() -> None:
    """非预期字段不允许静默存在（additionalProperties false）。"""
    files = canonical_from(builtin_files())
    manifest = json.loads(files[MANIFEST_FILE])
    manifest["approved_by_author"] = "self-declared"
    with pytest.raises(PackValidationError) as excinfo:
        parse_manifest(_corrupt(files, MANIFEST_FILE, manifest))
    assert excinfo.value.code == "PACK_SCHEMA_MISMATCH"
