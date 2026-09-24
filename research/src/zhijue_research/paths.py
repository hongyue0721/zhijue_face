"""研究输出路径：全部落在 `research/runtime/`，并拒绝越界写入。

业务 `runtime/`、`business.db`、Knowledge 索引、报告与草稿都不在本模块可达范围内。
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = RESEARCH_ROOT / "runtime"
_DATA_ROOT = RESEARCH_ROOT / "data"


def runtime_path(*parts: str) -> Path:
    """research/runtime/... ；自动建目录，越界即抛错。"""

    target = RUNTIME_DIR.joinpath(*parts)
    resolved = target.resolve()
    if (
        RUNTIME_DIR.resolve() not in resolved.parents
        and resolved != RUNTIME_DIR.resolve()
    ):
        raise ValueError(f"研究输出路径越界：{resolved}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def data_root() -> Path:
    return _DATA_ROOT


def traces_dir() -> Path:
    path = RUNTIME_DIR / "traces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def knowledge_dir() -> Path:
    """隔离的 Milvus Lite 文件目录；与业务 `runtime/knowledge.db` 完全分开。"""

    path = RUNTIME_DIR / "knowledge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def require_private_model_env(path: Path | None, config: Any) -> Path:
    """live 模型配置：显式路径优先，否则用配置登记的私密文件；两者都必须 0600。"""

    declared = path or (config.raw.get("model_env_file") or "").strip()
    if not declared:
        raise ValueError("live 驱动需要 model_env_file（仓库外 0600 私密文件）")
    resolved = Path(str(declared)).expanduser().resolve()
    mode = stat.S_IMODE(resolved.stat().st_mode) if resolved.is_file() else 0o777
    if not resolved.is_file() or mode & ~0o600:
        raise ValueError(f"私密模型 env 必须存在且权限 ≤0600：{resolved}")
    return resolved
