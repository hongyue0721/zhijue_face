"""确定性方法层：canonical JSON、SHA-256、JSONL 与私密文件守卫。

研究侧一切"可比较"都建立在稳定序列化上：同一输入永远得到同一 hash。
本模块是研究包唯一的序列化真源，config/prompts/trace 都从这里取。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Self

CANONICAL_SEPARATORS = (",", ":")
SECRET_FIELD_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|secret|access[_-]?token|refresh[_-]?token|password)"
)
#: 摘要类字段名（sha256/checksum/hash）不是密钥，避免误报。
ALLOWED_NAME_HINTS = ("sha256", "checksum", "hash", "fingerprint", "digest")


def canonical_json(value: Any) -> str:
    """排序键、无多余空白、保留非 ASCII：跨进程稳定的 JSON 文本。"""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=CANONICAL_SEPARATORS
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


#: 别名：trace/config 用 `sha256_value` 表达"对整个值取摘要"。
sha256_value = sha256_json


def short_hash(value: Any, length: int = 12) -> str:
    return sha256_json(value)[:length]


def redacted_public_summary(settings_summary: dict[str, Any]) -> dict[str, Any]:
    """模型配置摘要：剔除密钥类字段，只留可公开展示的采样/端点信息。"""

    return {
        key: value
        for key, value in sorted(settings_summary.items())
        if key not in {"api_key", "api_key_configured"}
        and not SECRET_FIELD_PATTERN.search(str(key))
    }


def assert_no_secret_fields(payload: Any, *, where: str) -> None:
    """写研究产物前递归检查：密钥类字段一律禁止存在（值本身由调用方负责不落盘）。"""

    if isinstance(payload, dict):
        for key, value in payload.items():
            name = str(key).lower()
            if SECRET_FIELD_PATTERN.search(name) and not any(
                hint in name for hint in ALLOWED_NAME_HINTS
            ):
                raise ValueError(f"{where} 含禁止字段 {key}")
            assert_no_secret_fields(value, where=where)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            assert_no_secret_fields(item, where=where)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_exclusive(path: Path, value: Any) -> None:
    """独占创建：实验证据文件永不静默覆盖既有结果。"""

    if path.exists():
        raise FileExistsError(f"证据文件已存在，拒绝覆盖：{path}")
    assert_no_secret_fields(value, where=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(
            value, handle, ensure_ascii=False, sort_keys=True, indent=2, default=str
        )
        handle.write("\n")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


class JsonlWriter:
    """trace 追加写入器：一行一条，逐行 flush + fsync，崩溃不丢已写记录。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self.written = 0

    def write(self, record: dict[str, Any]) -> None:
        assert_no_secret_fields(record, where=self.path.name)
        self._handle.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        )
        self._handle.write("\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.written += 1

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def require_private_file(path: Path) -> Path:
    """私密 env 必须存在且 owner-only；沿用既有模型/Knowledge 配置规则。"""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"私密配置文件不存在：{resolved}")
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode & ~0o600:
        raise PermissionError(f"私密配置文件权限必须 ≤0600，当前 {oct(mode)}")
    return resolved


def ensure_within(root: Path, target: Path) -> Path:
    """研究输出必须落在给定根目录内（一般是 research/runtime），防止误写业务数据。"""

    resolved_root = root.resolve()
    resolved = target.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"研究输出路径越界：{resolved} 不在 {resolved_root} 内")
    return resolved
