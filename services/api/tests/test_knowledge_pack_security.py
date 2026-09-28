"""ZIP 上传安全与资源上限回归（主文件 4.6 / Gate 2 / B04–B07）。

全部攻击样本在内存构造并交给 `safe_extract_zip`/`read_upload_limited`，
不落盘、不解压到真实目录、不执行任何内容。
"""

from __future__ import annotations

import io
import stat
import struct
import zipfile

import pytest

from zhijue.domain.knowledge_packs import (
    PackLimits,
    PackValidationError,
    read_upload_limited,
    safe_extract_zip,
)

LIMITS = PackLimits()

GOOD_MANIFEST = (
    b'{"format_version":"1.0","pack_id":"pack-a","version":"1.0.0",'
    b'"name":"test pack","description":"contract fixture",'
    b'"competency_profile_id":"embedded-junior-v1","seeds":[],'
    b'"competencies_file":"competencies.json","sources_file":"sources.json",'
    b'"supported_scope":"scope","unsupported_scope":"none","source_kind":"mixed"}'
)


def build_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


# --- B04：路径越界与绕过形态 ---------------------------------------------------


@pytest.mark.parametrize(
    "entry_name",
    [
        "../evil.json",
        "/etc/passwd.json",
        "C:/Windows/evil.json",
        "..\\evil.json",
        "seeds/../../evil.json",
        "seeds/\x00evil.json",
        "./manifest.json",
        "seeds//a.json",
    ],
)
def test_malicious_paths_rejected_before_extraction(entry_name: str) -> None:
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(build_zip({entry_name: b"{}"}), LIMITS)
    assert excinfo.value.code == "PACK_PATH_INVALID", (
        f"{entry_name!r} 应被路径校验拦截，实际 {excinfo.value.code}"
    )


def test_symlink_entry_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("manifest.json")
        # zipfile 自身不生成 symlink 条目，手工构造与真实恶意包一致的 external_attr。
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"/etc/shadow")
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(buffer.getvalue(), LIMITS)
    assert excinfo.value.code == "PACK_SYMLINK_FORBIDDEN"


def test_hardlink_like_special_entry_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("manifest.json")
        info.create_system = 3
        info.external_attr = (stat.S_IFIFO | 0o644) << 16
        archive.writestr(info, b"x")
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(buffer.getvalue(), LIMITS)
    assert excinfo.value.code == "PACK_SPECIAL_ENTRY"


def test_case_collision_rejected() -> None:
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(
            build_zip({"manifest.json": GOOD_MANIFEST, "MANIFEST.JSON": b"{}"}),
            LIMITS,
        )
    assert excinfo.value.code == "PACK_PATH_COLLISION"


def test_duplicate_entry_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", GOOD_MANIFEST)
        archive.writestr("manifest.json", b"second copy")
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(buffer.getvalue(), LIMITS)
    assert excinfo.value.code in {"PACK_PATH_COLLISION", "PACK_DUPLICATE_ENTRY"}


# --- B07：类型与加密 -----------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["run.py", "tool.sh", "payload.exe", "nested.zip", "page.html", "no_suffix"]
)
def test_forbidden_types_rejected(name: str) -> None:
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(
            build_zip({name: b"x", "manifest.json": GOOD_MANIFEST}), LIMITS
        )
    assert excinfo.value.code in {"PACK_FORBIDDEN_TYPE", "PACK_UNSPECIFIED_TYPE"}


def test_encrypted_entry_rejected() -> None:
    plain = build_zip({"manifest.json": GOOD_MANIFEST})
    # 本地头 flags 在签名后偏移 6，中央目录 flags 在偏移 8；两处同时置 bit0，
    # 模拟真实加密 ZIP（zipfile 写路径不支持加密条目）。
    poisoned = bytearray(plain)
    for offset in range(len(poisoned) - 10):
        signature = bytes(poisoned[offset : offset + 4])
        if signature in (b"PK\x03\x04", b"PK\x01\x02"):
            flags_at = offset + (6 if signature == b"PK\x03\x04" else 8)
            flags = struct.unpack_from("<H", poisoned, flags_at)[0]
            struct.pack_into("<H", poisoned, flags_at, flags | 0x1)
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(bytes(poisoned), LIMITS)
    assert excinfo.value.code == "PACK_ENCRYPTED"


# --- B05：解压炸弹、条数与单文件上限 -------------------------------------------


def test_single_file_over_limit_rejected() -> None:
    huge = {
        "manifest.json": GOOD_MANIFEST,
        "sources.json": b"a" * (LIMITS.max_single_file_bytes + 1),
    }
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(build_zip(huge), LIMITS)
    assert excinfo.value.code == "PACK_FILE_TOO_LARGE"


def test_total_output_limit_rejects_bomb() -> None:
    # 用小额度上限验证“实际输出总量”分支，避免测试构造数百 MiB 数据。
    limits = PackLimits(
        max_extracted_total_bytes=5 * 1024 * 1024,
        max_single_file_bytes=1024 * 1024,
        max_entries=16,
    )
    entries = {"manifest.json": GOOD_MANIFEST}
    payload = b"a" * (limits.max_single_file_bytes - 1)
    for index in range(10):
        entries[f"f{index:03d}.txt"] = payload
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(build_zip(entries), limits)
    assert excinfo.value.code == "PACK_TOTAL_TOO_LARGE"


def test_compression_ratio_guard() -> None:
    # 1 MiB 重复数据声明大小不超单文件上限；用显式小额度档验证比值分支
    # （真实部署阈值见 PackLimits 默认值与 config/demo.yaml）。
    limits = PackLimits(max_compression_ratio=5, ratio_check_from_bytes=64)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", GOOD_MANIFEST)
        archive.writestr("big.txt", b"ab" * (limits.max_single_file_bytes // 2))
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(buffer.getvalue(), limits)
    assert excinfo.value.code == "PACK_COMPRESSION_BOMB"


def test_entry_count_limit() -> None:
    entries = {"manifest.json": GOOD_MANIFEST}
    for index in range(LIMITS.max_entries):
        entries[f"extra{index:04d}.txt"] = b"x"
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(build_zip(entries), LIMITS)
    assert excinfo.value.code == "PACK_ENTRY_LIMIT"


# --- 流式上传字节上限（不信任 Content-Length） ---------------------------------


def test_upload_stream_limited_by_actual_bytes() -> None:
    stream = io.BytesIO(b"z" * (LIMITS.max_upload_bytes + 10))
    with pytest.raises(PackValidationError) as excinfo:
        read_upload_limited(stream, LIMITS)
    assert excinfo.value.code == "PACK_UPLOAD_TOO_LARGE"


def test_empty_upload_rejected() -> None:
    with pytest.raises(PackValidationError) as excinfo:
        read_upload_limited(io.BytesIO(b""), LIMITS)
    assert excinfo.value.code == "PACK_UPLOAD_EMPTY"


def test_not_a_zip_container_rejected() -> None:
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(b"%PDF-1.7 not a zip", LIMITS)
    assert excinfo.value.code == "PACK_NOT_ZIP"


def test_error_message_has_no_absolute_path_or_payload() -> None:
    """安全错误不回显服务器绝对路径、密钥或整个文档。"""
    secret_body = b"SECRET-MANUSCRIPT-FULL-TEXT"
    with pytest.raises(PackValidationError) as excinfo:
        safe_extract_zip(
            build_zip({"evil/nested/../../../x.json": secret_body}), LIMITS
        )
    message = str(excinfo.value)
    assert secret_body.decode() not in message
    assert "/evil" not in message
