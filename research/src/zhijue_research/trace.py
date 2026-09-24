"""Research trace：一行一个 `case × method × model`，落盘前必须过 JSON Schema。

规则 I6：取不到的数据只能是 null。本模块不提供"默认 0"或"猜测"的入口：
`absent()` 与真实数值走同一条构造路径，但 cost 只允许 provider 或 catalog_price 两种来源。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from jsonschema import Draft202012Validator

from zhijue_research.io_utils import JsonlWriter, sha256_text, sha256_value

TRACE_SCHEMA_VERSION = "1.0.0"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "research-trace.schema.json"
)

_validator: Draft202012Validator | None = None


def trace_validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _validator = Draft202012Validator(schema)
    return _validator


class TraceValidationError(ValueError):
    """trace 不符合契约；实验证据不允许"先写了再说"。"""


def validate_trace(record: dict[str, Any]) -> None:
    errors = sorted(
        trace_validator().iter_errors(record), key=lambda item: str(item.path)
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise TraceValidationError(f"trace 违反 research-trace 契约：{detail}")


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    """检索中间结果。不保存最终拼好的 Prompt，才能区分 Retrieval/Generation Failure。"""

    query: str
    query_template_version: str
    embed_mode: str
    kb_backend: str
    top_k: int
    hits: tuple[dict[str, Any], ...]

    @property
    def query_hash(self) -> str:
        return sha256_text(self.query)

    def evidence_input_hash(self) -> str:
        return sha256_value(
            [dict(hit, text_hash=hit["text_hash"]) for hit in self.hits]
        )

    def as_trace_block(self) -> dict[str, Any]:
        return {
            "config": {
                "query_template_version": self.query_template_version,
                "embed_mode": self.embed_mode,
                "kb_backend": self.kb_backend,
            },
            "query": self.query,
            "query_hash": self.query_hash,
            "top_k": self.top_k,
            "hits": [dict(hit) for hit in self.hits],
        }


class TraceWriter:
    """独占创建 JSONL；同名文件已存在时失败，不覆盖既有实验结果。"""

    def __init__(self, path: Path) -> None:
        if path.exists():
            raise FileExistsError(f"trace 文件已存在，拒绝覆盖：{path}")
        self._writer = JsonlWriter(path)
        self.path = path

    def emit(self, record: dict[str, Any]) -> dict[str, Any]:
        validate_trace(record)
        self._writer.write(record)
        return record

    def close(self) -> None:
        self._writer.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def read_traces(path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for record in records:
        validate_trace(record)
    return records


def now_rfc3339() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
