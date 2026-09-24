"""按版本冻结的 Prompt 注册表（防污染规则 6/7）。

Prompt 只从 `research/config/prompts/<method_id>/<version>.md` 读取，加载时校验登记 hash。
任何改动必须新建版本号并重新登记——不允许"看结果顺手改一句"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from zhijue_research.io_utils import sha256_text

VERSION_PATTERN = re.compile(r"^p[0-9]+\.[0-9]+$")
METHOD_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class PromptRegistryError(ValueError):
    """Prompt 缺失、版本非法或内容与登记 hash 不一致。"""


@dataclass(frozen=True, slots=True)
class Prompt:
    method_id: str
    version: str
    text: str
    sha256: str


class PromptRegistry:
    """`expected_hashes[method_id][version] = sha256`，通常来自 experiment 配置。"""

    def __init__(self, root: Path, expected_hashes: dict[str, dict[str, str]]) -> None:
        self._root = root
        self._expected = expected_hashes

    def load(self, method_id: str, version: str) -> Prompt:
        if not METHOD_ID_PATTERN.fullmatch(method_id):
            raise PromptRegistryError(f"非法 method_id：{method_id!r}")
        if not VERSION_PATTERN.fullmatch(version):
            raise PromptRegistryError(
                f"非法 prompt 版本：{version!r}（要求 pMAJOR.MINOR）"
            )

        # 先查登记：未登记的版本要给出明确契约错误，而不是"文件不存在"。
        registered = self._expected.get(method_id, {}).get(version)
        if registered is None:
            raise PromptRegistryError(
                f"prompt {method_id}@{version} 未在配置中登记 hash"
            )
        path = self._root / method_id / f"{version}.md"
        if not path.is_file():
            raise PromptRegistryError(f"prompt 文件不存在：{path}")
        text = path.read_text(encoding="utf-8").rstrip("\n")
        digest = sha256_text(text)
        if registered != digest:
            raise PromptRegistryError(
                f"prompt {method_id}@{version} 内容与登记 hash 不一致；改动必须新建版本"
            )
        return Prompt(method_id=method_id, version=version, text=text, sha256=digest)

    def registered_versions(self, method_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._expected.get(method_id, {})))


def compute_prompt_hashes(root: Path) -> dict[str, dict[str, str]]:
    """登记工具：扫描 prompts 目录产出 method_id → version → sha256。"""

    registry: dict[str, dict[str, str]] = {}
    for method_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        versions: dict[str, str] = {}
        for prompt_file in sorted(method_dir.glob("p*.md")):
            version = prompt_file.stem
            if not VERSION_PATTERN.fullmatch(version):
                raise PromptRegistryError(f"非法 prompt 文件名：{prompt_file}")
            versions[version] = sha256_text(
                prompt_file.read_text(encoding="utf-8").rstrip("\n")
            )
        if versions:
            registry[method_dir.name] = versions
    return registry
