"""结构化岗位知识包的字节级契约：规范摘要、严格解析与 ZIP 安全（主文件 Phase 2/4.6）。

不变量：

- ZIP 字节 hash 只用于本次上传追踪/幂等，不作为内容身份；包身份由
  `pack_id + version + content_digest` 表达，`content_digest` 由服务端对
  **归一化后的包内字节**按 canonical manifest 重算（R04：旧短指纹不承担
  完整性证明，保留为兼容展示字段）。
- 归一化规则唯一且实现/测试同一：UTF-8 必需、拒绝 BOM、CRLF/CR → LF，
  其余字节原样；不做 JSON 重新序列化（避免键序/数字形态漂移）。
- 一切上传内容按不可信输入处理：严格 JSON（拒绝重复键/超深/NaN/Infinity）、
  路径与条目安全检查先于解压、解压过程仍限制实际输出字节；失败不产生半包。
- 错误消息只含相对路径与规则名，绝不回显服务器绝对路径或整文档。
"""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import stat as stat_module
import unicodedata
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

PACK_FORMAT_VERSION = "1.0"
DIGEST_PREFIX = "sha256:"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

MANIFEST_FILE = "manifest.json"
COMPETENCIES_FILE = "competencies.json"
SOURCES_FILE = "sources.json"
NOTICE_FILE = "NOTICE.txt"
EXAMPLE_JD_FILE = "examples/jd.txt"
REQUIRED_TOP_LEVEL_FILES = (MANIFEST_FILE, COMPETENCIES_FILE, SOURCES_FILE)

# 明确不允许出现在包内的类型/后缀（不执行任何导入内容）。
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".iso",
        ".cab",
        ".jar",
        ".war",
        ".apk",
        ".whl",
        ".gem",
        ".rpm",
        ".deb",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".py",
        ".pyc",
        ".sh",
        ".bash",
        ".zsh",
        ".bat",
        ".cmd",
        ".ps1",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".html",
        ".htm",
        ".xhtml",
        ".svg",
        ".lnk",
        ".url",
        ".desktop",
        ".app",
        ".elf",
        ".class",
        ".vb",
        ".vbs",
        ".scr",
    }
)
ALLOWED_SUFFIXES = frozenset({".json", ".txt"})

MAX_JSON_DEPTH = 8
SAFE_URL_SCHEMES = ("http://", "https://")


class PackValidationError(ValueError):
    """包格式/安全校验失败。code 面向机器，message 面向人，均不含绝对路径。"""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        super().__init__(f"{code}: {message}" + (f"（{path}）" if path else ""))
        self.code = code
        self.message = message
        self.path = path


class ValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PackLimits:
    """资源上限集中声明（写入 config/demo.yaml 的 knowledge_packs 节）。"""

    max_upload_bytes: int = 5 * 1024 * 1024
    max_extracted_total_bytes: int = 20 * 1024 * 1024
    max_single_file_bytes: int = 1024 * 1024
    max_entries: int = 256
    max_path_depth: int = 5
    max_compression_ratio: int = 50
    ratio_check_from_bytes: int = 8 * 1024


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"check": self.name, "status": self.status, "detail": self.detail}


def read_upload_limited(stream: io.IOBase, limits: PackLimits) -> bytes:
    """按实际读取字节数限制上传，绝不信任 Content-Length。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limits.max_upload_bytes:
            raise PackValidationError(
                "PACK_UPLOAD_TOO_LARGE",
                f"上传超过 {limits.max_upload_bytes} 字节上限",
            )
        chunks.append(chunk)
    if total == 0:
        raise PackValidationError("PACK_UPLOAD_EMPTY", "上传字节为空")
    return b"".join(chunks)


def canonicalize_file_bytes(raw: bytes, *, path: str) -> bytes:
    """唯一承认的归一化：UTF-8 必需、拒绝 BOM、CRLF/CR → LF。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PackValidationError(
            "PACK_BOM_FORBIDDEN", "包内文件不允许 UTF-8 BOM", path=path
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackValidationError(
            "PACK_NOT_UTF8", "包内文件必须是 UTF-8 文本", path=path
        ) from exc
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def strict_json_loads(text: str, *, path: str) -> Any:
    """严格 JSON：拒绝重复键、非标准常量、超深对象。"""

    def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PackValidationError(
                    "PACK_JSON_DUPLICATE_KEY", f"JSON 含重复键 {key!r}", path=path
                )
            result[key] = value
        return result

    def _constant(name: str) -> Any:
        raise PackValidationError(
            "PACK_JSON_INVALID_NUMBER", f"JSON 不允许 {name}", path=path
        )

    try:
        loaded = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except PackValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise PackValidationError(
            "PACK_JSON_INVALID", f"JSON 解析失败：{exc.msg}", path=path
        ) from exc
    _check_depth(loaded, path=path, depth=0)
    return loaded


def _check_depth(value: Any, *, path: str, depth: int) -> None:
    if depth > MAX_JSON_DEPTH:
        raise PackValidationError(
            "PACK_JSON_TOO_DEEP", f"嵌套超过 {MAX_JSON_DEPTH} 层", path=path
        )
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, path=path, depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _check_depth(child, path=path, depth=depth + 1)


def file_sha256(canonical_bytes: bytes) -> str:
    return hashlib.sha256(canonical_bytes).hexdigest()


def compute_content_digest(
    *, pack_id: str, version: str, files: dict[str, bytes]
) -> tuple[str, list[dict[str, str]]]:
    """files 的字节必须已经过 canonicalize_file_bytes。

    canonical manifest = 明确字段的 JSON（键排序、紧凑分隔符、UTF-8、
    文件按归一化路径排序）。时间戳/打包顺序不参与，因此同内容不同 ZIP
    识别为同一 release（B08）。
    """
    index = [
        {"path": path, "sha256": file_sha256(files[path])} for path in sorted(files)
    ]
    canonical = json.dumps(
        {
            "content_index": index,
            "format_version": PACK_FORMAT_VERSION,
            "pack_id": pack_id,
            "version": version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = DIGEST_PREFIX + hashlib.sha256(canonical).hexdigest()
    return digest, index


def release_id_for(digest: str) -> str:
    return "kpr_" + digest.removeprefix(DIGEST_PREFIX)[:16]


def _validate_entry_path(name: str) -> str:
    if "\x00" in name:
        raise PackValidationError("PACK_PATH_INVALID", "路径含空字节")
    if "\\" in name:
        raise PackValidationError(
            "PACK_PATH_INVALID", "路径含反斜杠（Windows 分隔符绕过）"
        )
    if re.match(r"^[A-Za-z]:", name):
        raise PackValidationError("PACK_PATH_INVALID", "路径含盘符")
    if name.startswith("/"):
        raise PackValidationError("PACK_PATH_INVALID", "路径为绝对路径")
    if unicodedata.normalize("NFC", name) != name:
        raise PackValidationError(
            "PACK_PATH_INVALID", "路径必须为 NFC 规范化形式（防归一化冲突）"
        )
    normalized = posixpath.normpath(name)
    if normalized != name or normalized == ".." or normalized.startswith("../"):
        raise PackValidationError(
            "PACK_PATH_INVALID", "路径含 .、.. 或冗余分隔（归一化冲突）"
        )
    if ".." in name.split("/"):
        raise PackValidationError("PACK_PATH_INVALID", "路径越界（..）")
    return normalized


def safe_extract_zip(zip_bytes: bytes, limits: PackLimits) -> dict[str, bytes]:
    """解压前检查全部条目；解压过程中仍限制实际输出。

    返回 归一化路径 → canonical 字节。任何违规立即失败，不产出部分内容。
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise PackValidationError("PACK_NOT_ZIP", "上传内容不是合法 ZIP 容器") from exc
    infos = archive.infolist()
    if len(infos) > limits.max_entries:
        raise PackValidationError(
            "PACK_ENTRY_LIMIT", f"条目数 {len(infos)} 超过上限 {limits.max_entries}"
        )
    files: dict[str, bytes] = {}
    seen_casefold: dict[str, str] = {}
    total_output = 0
    for info in infos:
        path = _validate_entry_path(info.filename)
        if info.is_dir():
            # 目录条目不带内容；仍参与冲突检查。
            key = path.casefold()
            if key in seen_casefold:
                raise PackValidationError(
                    "PACK_PATH_COLLISION", f"大小写/归一化路径冲突：{path}"
                )
            seen_casefold[key] = path
            continue
        key = path.casefold()
        if key in seen_casefold:
            raise PackValidationError(
                "PACK_PATH_COLLISION", f"大小写/归一化路径冲突：{path}"
            )
        seen_casefold[key] = path
        mode = info.external_attr >> 16
        file_type = stat_module.S_IFMT(mode)
        if mode and file_type == stat_module.S_IFLNK:
            raise PackValidationError(
                "PACK_SYMLINK_FORBIDDEN", "拒绝符号链接条目", path=path
            )
        if mode and file_type not in (0, stat_module.S_IFREG):
            raise PackValidationError(
                "PACK_SPECIAL_ENTRY", "只允许普通文件条目", path=path
            )
        if info.flag_bits & 0x1:
            raise PackValidationError("PACK_ENCRYPTED", "拒绝加密 ZIP 条目", path=path)
        suffix = posixpath.splitext(path)[1].lower()
        if suffix in FORBIDDEN_SUFFIXES:
            raise PackValidationError(
                "PACK_FORBIDDEN_TYPE",
                f"禁止的可执行/嵌套压缩类型 {suffix or '(无后缀)'}",
                path=path,
            )
        if suffix not in ALLOWED_SUFFIXES:
            raise PackValidationError(
                "PACK_UNSPECIFIED_TYPE", "仅允许 .json/.txt 文件", path=path
            )
        if info.file_size > limits.max_single_file_bytes:
            raise PackValidationError(
                "PACK_FILE_TOO_LARGE",
                f"声明大小超过单文件上限 {limits.max_single_file_bytes}",
                path=path,
            )
        if (
            info.compress_size >= limits.ratio_check_from_bytes
            and info.file_size > info.compress_size * limits.max_compression_ratio
        ):
            raise PackValidationError(
                "PACK_COMPRESSION_BOMB",
                f"压缩比超过 {limits.max_compression_ratio} 倍上限",
                path=path,
            )
        # 解压时以实际输出字节为准，声明值不可信。
        raw = bytearray()
        with archive.open(info) as source:
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > limits.max_single_file_bytes:
                    raise PackValidationError(
                        "PACK_FILE_TOO_LARGE",
                        f"实际输出超过单文件上限 {limits.max_single_file_bytes}",
                        path=path,
                    )
                total_output += len(chunk)
                if total_output > limits.max_extracted_total_bytes:
                    raise PackValidationError(
                        "PACK_TOTAL_TOO_LARGE",
                        f"解压总量超过 {limits.max_extracted_total_bytes} 字节上限",
                    )
        if path in files:
            raise PackValidationError("PACK_DUPLICATE_ENTRY", "重复路径", path=path)
        files[path] = canonicalize_file_bytes(bytes(raw), path=path)
    if MANIFEST_FILE not in files:
        raise PackValidationError("PACK_MANIFEST_MISSING", f"缺少 {MANIFEST_FILE}")
    return files


@dataclass(frozen=True)
class PackManifest:
    pack_id: str
    version: str
    name: str
    description: str
    competency_profile_id: str
    seeds: tuple[str, ...]
    example_jd_file: str | None
    supported_scope: str
    unsupported_scope: str
    source_kind: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "competency_profile_id": self.competency_profile_id,
            "seeds": list(self.seeds),
            "example_jd_file": self.example_jd_file,
            "supported_scope": self.supported_scope,
            "unsupported_scope": self.unsupported_scope,
            "source_kind": self.source_kind,
        }


def _schema_def(name: str) -> dict[str, Any]:
    """惰性加载契约文件，避免领域层 import 时依赖仓库布局。"""
    from pathlib import Path

    here = Path(__file__).resolve()
    for candidate in here.parents:
        path = candidate / "contracts" / "knowledge_pack.schema.json"
        if path.is_file():
            schema = json.loads(path.read_text(encoding="utf-8"))
            return {**schema["$defs"][name], "$defs": schema["$defs"]}
    raise PackValidationError(
        "PACK_SCHEMA_MISSING", "未找到 contracts/knowledge_pack.schema.json"
    )


def _validate_against(def_name: str, payload: Any, *, path: str) -> None:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(_schema_def(def_name))
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.json_path)
    if errors:
        first = errors[0]
        message = first.message
        if len(message) > 200:
            message = message[:200] + "…"
        raise PackValidationError(
            "PACK_SCHEMA_MISMATCH", f"{path} 不符合契约：{message}", path=path
        )


def parse_manifest(files: dict[str, bytes]) -> PackManifest:
    payload = strict_json_loads(
        files[MANIFEST_FILE].decode("utf-8"), path=MANIFEST_FILE
    )
    _validate_against("manifest", payload, path=MANIFEST_FILE)
    if payload["format_version"] != PACK_FORMAT_VERSION:
        raise PackValidationError(
            "PACK_FORMAT_VERSION_UNSUPPORTED",
            f"包格式 {payload['format_version']!r} 不受支持（当前 {PACK_FORMAT_VERSION}）",
            path=MANIFEST_FILE,
        )
    declared_seeds = tuple(payload["seeds"])
    for seed_path in declared_seeds:
        if seed_path not in files:
            raise PackValidationError(
                "PACK_SEED_FILE_MISSING",
                "manifest 声明的 Seed 文件不在包内",
                path=seed_path,
            )
    example = payload.get("example_jd_file")
    if example is not None and example not in files:
        raise PackValidationError(
            "PACK_DECLARED_FILE_MISSING", "声明的示例 JD 不在包内", path=example
        )
    allowed = {
        MANIFEST_FILE,
        COMPETENCIES_FILE,
        SOURCES_FILE,
        NOTICE_FILE,
        *declared_seeds,
    }
    if example is not None:
        allowed.add(example)
    for path in files:
        if path not in allowed:
            raise PackValidationError(
                "PACK_UNDECLARED_FILE", "包内存在 manifest 未声明的文件", path=path
            )
    return PackManifest(
        pack_id=payload["pack_id"],
        version=payload["version"],
        name=payload["name"],
        description=payload["description"],
        competency_profile_id=payload["competency_profile_id"],
        seeds=declared_seeds,
        example_jd_file=example,
        supported_scope=payload["supported_scope"],
        unsupported_scope=payload["unsupported_scope"],
        source_kind=payload["source_kind"],
    )


def parse_competencies(files: dict[str, bytes]) -> dict[str, Any]:
    payload = strict_json_loads(
        files[COMPETENCIES_FILE].decode("utf-8"), path=COMPETENCIES_FILE
    )
    _validate_against("competencies", payload, path=COMPETENCIES_FILE)
    return payload


def parse_sources(files: dict[str, bytes]) -> tuple[dict[str, Any], ...]:
    payload = strict_json_loads(files[SOURCES_FILE].decode("utf-8"), path=SOURCES_FILE)
    _validate_against("sources", payload, path=SOURCES_FILE)
    ids: set[str] = set()
    for record in payload["sources"]:
        source_id = record["source_id"]
        if source_id in ids:
            raise PackValidationError(
                "PACK_SOURCE_DUPLICATE_ID",
                f"source_id 重复：{source_id}",
                path=SOURCES_FILE,
            )
        ids.add(source_id)
        url = record.get("url")
        if url is not None and not url.startswith(SAFE_URL_SCHEMES):
            raise PackValidationError(
                "PACK_SOURCE_URL_UNSAFE",
                "来源 URL 只允许 http/https（纯展示，不自动抓取）",
                path=SOURCES_FILE,
            )
        if url is None and not record.get("local_identifier"):
            raise PackValidationError(
                "PACK_SOURCE_UNLOCATABLE",
                "来源必须至少有展示用 URL 或本地标识，保证可追溯定位",
                path=SOURCES_FILE,
            )
        if record.get("content_sha256") is not None:
            # 没有真正保存原文时不允许伪造 hash；正则已在 Schema 中限形。
            pass
    return tuple(payload["sources"])


def assert_seed_reference_ids_resolve(
    seed_payloads: dict[str, Any], sources: tuple[dict[str, Any], ...]
) -> None:
    """每个 Seed 的 reference ID 必须解析到来源记录（4.3）。"""
    known = {record["source_id"] for record in sources}
    for seed_path, seed in seed_payloads.items():
        referenced = set(seed.get("reference_ids", []))
        for point in seed.get("reference_points", []):
            referenced.update(point.get("reference_ids", []))
        missing = sorted(referenced - known)
        if missing:
            raise PackValidationError(
                "PACK_REFERENCE_UNRESOLVED",
                "Seed 引用了未登记的来源 ID：" + ", ".join(missing),
                path=seed_path,
            )


def seed_content_hash(canonical_bytes: bytes) -> str:
    """审核范围绑定用的 Seed 内容 hash（归一化后字节）。"""
    return file_sha256(canonical_bytes)
