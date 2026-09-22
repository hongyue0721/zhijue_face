"""JD 与 Requisition 的领域模型与不变量（M2-02）。

设计要点（负责人 2026-09-18 决策）：

1. **来源链不可断**：JD 必须保留 `source_type / source_name / raw_text /
   content_hash / imported_at / version / status`；每条 Requirement 必须能回到
   JD Snapshot 中的原始片段（`source_span`），禁止 `JD → LLM → 无来源要求`。
2. **等级不得升级**：`required`（must-have）与 `preferred`（nice-to-have）严格
   区分；不得把加分项自动当成硬性要求。
3. **未验证不是弱项**：覆盖率状态 `supported / claimed / unverified / unknown /
   contradicted` 语义互斥；`unverified ≠ weak`、`unknown ≠ fail`。

本模块是纯函数与值对象，不 import ORM/框架。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlparse

from zhijue.domain.errors import JdRejected


class JDSourceType(StrEnum):
    OFFICIAL_POSTING = "official_posting"
    REAL_JD_DERIVED = "real_jd_derived"
    SYNTHETIC_DEMO_JD = "synthetic_demo_jd"
    USER_PROVIDED = "user_provided"


class EvidenceRelation(StrEnum):
    """证据与能力维度的关联强度（AGENTS 事实性与追溯不变量）。

    DIRECT_CLAIM: 候选人明确自述掌握该能力（如技能清单明确自述熟悉某机制）；
    DIRECT_EXPERIENCE: 候选人明确描述在具体项目/竞赛中有该技术的使用与排障经历；
    RELATED_CONTEXT: 相关技术上下文（如使用外设、定时器、周期任务、状态机），
                     说明该能力在业务场景中可能被触及，只能帮助 Planner 判断
                     "该维度值得验证"（information value），**严禁**将 unknown 升级为 unverified/claimed；
    MODEL_INFERENCE: 模型私有推测或推断，**严禁**作为 Candidate Evidence。
    """

    DIRECT_CLAIM = "direct_claim"
    DIRECT_EXPERIENCE = "direct_experience"
    RELATED_CONTEXT = "related_context"
    MODEL_INFERENCE = "model_inference"


DIRECT_EVIDENCE_RELATIONS = frozenset(
    {EvidenceRelation.DIRECT_CLAIM, EvidenceRelation.DIRECT_EXPERIENCE}
)


class JDStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class RequirementTier(StrEnum):
    """岗位要求等级。required 与 preferred 不得互相转换（负责人决策 §5）。"""

    REQUIRED = "required"
    PREFERRED = "preferred"
    RESPONSIBILITY = "responsibility"
    CONTEXTUAL = "contextual"


class CoverageStatus(StrEnum):
    """候选人覆盖状态（docs/03 §4）。

    `unverified` 表示"有材料提及但未经面试验证"；
    `unknown` 表示"材料完全没有体现"——**不等于不会**；
    `contradicted` 仅在确有冲突时使用。
    """

    SUPPORTED = "supported"
    CLAIMED = "claimed"
    UNVERIFIED = "unverified"
    UNKNOWN = "unknown"
    CONTRADICTED = "contradicted"


# 只有 contradicted 才是需要扣分/质疑的信号；其余四类都不是"弱项"。
NEVER_A_WEAKNESS = frozenset(
    {
        CoverageStatus.SUPPORTED,
        CoverageStatus.CLAIMED,
        CoverageStatus.UNVERIFIED,
        CoverageStatus.UNKNOWN,
    }
)


@dataclass(frozen=True)
class JDSnapshot:
    """不可变 JD 快照；`content_hash` 由 raw_text 决定，严格区分上游来源与本地衍生工件。"""

    id: str
    profile_id: str
    source_type: JDSourceType
    source_name: str
    raw_text: str
    content_hash: str
    imported_at: str
    version: int
    status: JDStatus
    is_synthetic: bool
    source_url: str | None = None
    retrieved_at: str | None = None
    derived: bool = False
    upstream_source_name: str | None = None
    upstream_url: str | None = None
    upstream_retrieved_at: str | None = None
    upstream_content_hash: str | None = None
    derived_artifact_path: str | None = None
    derived_content_hash: str | None = None
    transformation_note: str | None = None

    @staticmethod
    def compute_hash(raw_text: str) -> str:
        return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Requirement:
    """一条岗位要求；`source_span` 是它回到 JD 原文的锚点。

    计量单位规范（跨语言契约）：
    - `unit`: "unicode_code_point"（Python 3 str 码点/标量值偏移，0 索引半开区间 [start, end)）
    - `utf16_start` / `utf16_end`: UTF-16 code units（JavaScript String.prototype.substring 索引）
    - `quote`: 原文切片字符串（保证 raw_text[start:end] == quote）
    """

    id: str
    jd_snapshot_id: str
    tier: RequirementTier
    competency_id: str
    statement: str
    source_span: dict[
        str, object
    ]  # {section, start, end, quote, unit, utf16_start, utf16_end}
    importance: int  # 3 = 明确 must-have 标记；1 = 加分项或上下文
    extraction: str  # rule_based / manual / model_assisted


@dataclass(frozen=True)
class JDImportResult:
    snapshot: JDSnapshot
    requirements: list[Requirement] = field(default_factory=list)


MAX_JD_CHARS = 8_000  # config/demo.yaml limits.max_jd_chars

# 规则抽取的显式标记。**只做分级与定位，不生成原文之外的要求**（负责人决策 §5）。
_REQUIRED_MARKERS = (
    "必要项",
    "必备",
    "要求",
    "任职资格",
    "任职条件",
    "基本条件",
    "qualification",
    "must",
    "required",
)
_PREFERRED_MARKERS = ("加分项", "优先", "nice", "preferred", "plus")
_RESPONSIBILITY_MARKERS = ("岗位职责", "工作内容", "职责", "responsibility")
_CONTEXTUAL_MARKERS = ("考察范围", "重点考察", "不要求", "context", "scope")

# 常见 JD 区段标题只在明确的 Markdown 标题或“标题：”边界生效。
# 不能因为正文里出现“要求/职责”字样就把无分类文本升级成 Requirement。
_PREFIXED_SECTION_TITLES = (
    "Responsibilities",
    "Qualifications",
    "Nice to Have",
    "任职要求",
    "岗位要求",
    "职位要求",
    "基本要求",
    "资格要求",
    "任职资格",
    "任职条件",
    "基本条件",
    "优先条件",
    "加分条件",
    "岗位职责",
    "工作职责",
    "职位职责",
    "主要职责",
    "考察范围",
    "重点考察",
    "Required",
    "Preferred",
    "必要项",
    "工作内容",
    "加分项",
    "必备",
    "优先",
    "职责",
)
_PREFIXED_SECTION_RE = re.compile(
    rf"^({'|'.join(re.escape(title) for title in _PREFIXED_SECTION_TITLES)})[：:]",
    re.IGNORECASE,
)

# 这些行不是要求，是来源声明/边界提示；抽取时跳过但保留在 raw_text 里。
_NON_REQUIREMENT_MARKERS = (
    "【",
    "不是任何企业",
    "demo jd",
    "version:",
    "source_type:",
    "purpose:",
    "confirmed_by:",
    "registered_on:",
    "role:",
)

_COMPETENCY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("c 程序", "c 语言", "c语言", "基础 c", "指针", "内存"), "embedded.c.basics"),
    (("中断", "nvic", "isr"), "embedded.mcu.interrupt"),
    (("uart", "串口", "dma"), "embedded.peripheral.uart_dma"),
    (("spi", "i2c", "can", "总线"), "embedded.peripheral.serial_bus"),
    (
        ("rtos", "freertos", "任务", "共享资源", "任务间通信"),
        "embedded.rtos.fundamentals",
    ),
    (("git", "版本控制", "回归"), "engineering.tooling.version_control"),
    (("本人工作", "个人贡献", "团队", "主要负责"), "project.ownership"),
    (("验证方法", "验证", "测量", "定位", "调试"), "engineering.verification"),
)


def _utf16_code_units(s: str) -> int:
    """计算字符串在 UTF-16（JavaScript String）中的 code unit 长度。"""
    return len(s.encode("utf-16-le")) // 2


def normalize_jd(raw_text: str) -> str:
    """统一换行并去除首尾空白；不做任何内容改写。"""
    return re.sub(r"\r\n?", "\n", raw_text).strip()


def validate_jd(raw_text: str) -> str:
    """校验 JD 文本；空或超长立即失败（不静默截断）。"""
    normalized = normalize_jd(raw_text)
    if not normalized:
        raise JdRejected("INVALID_REQUEST", "JD 文本为空。")
    if len(normalized) > MAX_JD_CHARS:
        raise JdRejected(
            "TEXT_TOO_LARGE", f"JD {len(normalized)} 字符，超过上限 {MAX_JD_CHARS}。"
        )
    return normalized


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _validated_public_url(value: str | None, *, field_name: str) -> str:
    """只接受可定位的公网 HTTP(S) URL；示例/本地域名不是来源事实。"""
    parsed = urlparse(value or "")
    host = (parsed.hostname or "").lower()
    labels = host.split(".")
    reserved = (
        not host
        or parsed.scheme not in {"http", "https"}
        or host == "localhost"
        or host.endswith((".local", ".test", ".invalid"))
        or any("example" in label for label in labels)
    )
    if reserved:
        raise JdRejected(
            "JD_PROVENANCE_INVALID",
            f"{field_name} 必须是可定位的公网 HTTP(S) 来源，不能使用本地路径或示例域名。",
        )
    return value or ""


def _validated_sha256(value: str | None, *, field_name: str) -> str:
    if not value or not _SHA256_RE.fullmatch(value):
        raise JdRejected("JD_PROVENANCE_INVALID", f"{field_name} 必须是 64 位 SHA256。")
    return value.lower()


def _validate_derived_provenance(
    *,
    upstream_source_name: str | None,
    upstream_url: str | None,
    upstream_retrieved_at: str | None,
    upstream_content_hash: str | None,
    derived_artifact_path: str | None,
    derived_content_hash: str | None,
    transformation_note: str | None,
    content_hash: str,
) -> tuple[str, str]:
    required = (
        ("upstream_source_name", upstream_source_name),
        ("upstream_retrieved_at", upstream_retrieved_at),
        ("derived_artifact_path", derived_artifact_path),
        ("transformation_note", transformation_note),
    )
    missing = [name for name, value in required if not value]
    if missing:
        raise JdRejected(
            "JD_PROVENANCE_INVALID",
            f"real_jd_derived 缺少来源字段：{', '.join(missing)}。",
        )
    normalized_url = _validated_public_url(upstream_url, field_name="upstream_url")
    upstream_hash = _validated_sha256(
        upstream_content_hash, field_name="upstream_content_hash"
    )
    derived_hash = _validated_sha256(
        derived_content_hash, field_name="derived_content_hash"
    )
    if derived_hash != content_hash:
        raise JdRejected(
            "JD_PROVENANCE_INVALID",
            "derived_content_hash 与当前 JD 文本不一致。",
        )
    return normalized_url, upstream_hash


def _reject_provenance_fields(
    source_type: JDSourceType, fields: dict[str, str | None]
) -> None:
    present = [name for name, value in fields.items() if value is not None]
    if present:
        raise JdRejected(
            "JD_PROVENANCE_INVALID",
            f"{source_type.value} 不得携带真实来源认证字段：{', '.join(present)}。",
        )


def _validate_provenance(
    *,
    source_type: JDSourceType,
    source_url: str | None,
    retrieved_at: str | None,
    upstream_source_name: str | None,
    upstream_url: str | None,
    upstream_retrieved_at: str | None,
    upstream_content_hash: str | None,
    derived_artifact_path: str | None,
    derived_content_hash: str | None,
    transformation_note: str | None,
    content_hash: str,
) -> tuple[str | None, str | None, str | None]:
    """验证来源类别的必要事实，返回规范化的 URL 与 hash。"""
    if source_type is JDSourceType.OFFICIAL_POSTING:
        direct_url = _validated_public_url(source_url, field_name="source_url")
        if not retrieved_at:
            raise JdRejected(
                "JD_PROVENANCE_INVALID",
                "official_posting 必须记录 retrieved_at。",
            )
        return direct_url, None, None
    if source_type is JDSourceType.REAL_JD_DERIVED:
        normalized_url, upstream_hash = _validate_derived_provenance(
            upstream_source_name=upstream_source_name,
            upstream_url=upstream_url,
            upstream_retrieved_at=upstream_retrieved_at,
            upstream_content_hash=upstream_content_hash,
            derived_artifact_path=derived_artifact_path,
            derived_content_hash=derived_content_hash,
            transformation_note=transformation_note,
            content_hash=content_hash,
        )
        return None, normalized_url, upstream_hash
    _reject_provenance_fields(
        source_type,
        {
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "upstream_source_name": upstream_source_name,
            "upstream_url": upstream_url,
            "upstream_retrieved_at": upstream_retrieved_at,
            "upstream_content_hash": upstream_content_hash,
            "derived_artifact_path": derived_artifact_path,
            "derived_content_hash": derived_content_hash,
            "transformation_note": transformation_note,
        },
    )
    return None, None, None


def classify_tier(line: str) -> RequirementTier | None:
    """按显式标记判定等级；无标记的行不自动升级为 required。"""
    lowered = line.lower()
    for marker in _NON_REQUIREMENT_MARKERS:
        if marker in lowered:
            return None
    if any(marker in lowered for marker in _RESPONSIBILITY_MARKERS):
        return RequirementTier.RESPONSIBILITY
    if any(marker in lowered for marker in _CONTEXTUAL_MARKERS):
        return RequirementTier.CONTEXTUAL
    if any(marker in lowered for marker in _PREFERRED_MARKERS):
        return RequirementTier.PREFERRED
    if any(marker in lowered for marker in _REQUIRED_MARKERS):
        return RequirementTier.REQUIRED
    return None


def detect_competency(statement: str) -> str | None:
    """把要求映射到能力维度；匹配不到就返回 None（不硬塞到某个维度）。"""
    lowered = statement.lower()
    for keywords, competency in _COMPETENCY_RULES:
        if any(keyword in lowered for keyword in keywords):
            return competency
    return None


def importance_for(tier: RequirementTier) -> int:
    """离散权重：required=3、preferred=1、responsibility=2、contextual=1（docs/04 §4）。"""
    return {
        RequirementTier.REQUIRED: 3,
        RequirementTier.PREFERRED: 1,
        RequirementTier.RESPONSIBILITY: 2,
        RequirementTier.CONTEXTUAL: 1,
    }[tier]


@dataclass(frozen=True)
class _CandidateSpan:
    section: str
    text: str
    start: int
    end: int


def split_sections(raw_text: str) -> list[_CandidateSpan]:
    """把 JD 切成"标记 + 其后的条目"片段，兼容 Markdown 标题（## ）与前缀标记（必要项：）。"""
    spans: list[_CandidateSpan] = []
    current_section: str | None = None
    current_start = 0
    cursor = 0
    lines = raw_text.splitlines(keepends=True)
    for line in lines:
        stripped = line.strip()
        header_m = re.match(r"^#{1,3}\s+(.+)$", stripped)
        prefix_m = _PREFIXED_SECTION_RE.match(stripped)

        new_header = None
        if header_m:
            new_header = header_m.group(1).strip()
        elif prefix_m:
            new_header = prefix_m.group(1).strip()

        if new_header:
            if current_section is not None:
                text = raw_text[current_start:cursor]
                if text.strip():
                    spans.append(
                        _CandidateSpan(current_section, text, current_start, cursor)
                    )
            current_section = new_header
            current_start = cursor
        cursor += len(line)

    if current_section is not None:
        text = raw_text[current_start:cursor]
        if text.strip():
            spans.append(_CandidateSpan(current_section, text, current_start, cursor))
    return spans


def _split_statements(text: str) -> list[str]:
    """将文本切分为候选要求句子，去除编号、标记和标点。"""
    statements = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"^#{1,3}\s+.*$", "", cleaned)
        cleaned = _PREFIXED_SECTION_RE.sub("", cleaned, count=1)
        cleaned = re.sub(r"^[\-\*\d\.\、\s]+", "", cleaned).strip()
        if not cleaned:
            continue
        parts = re.split(r"[；;。\n]|以及", cleaned)
        for part in parts:
            part_clean = part.strip(" 、，,")
            if part_clean and len(part_clean) >= 2:
                statements.append(part_clean)
    return statements


def extract_requirements(
    snapshot: JDSnapshot, *, extraction: str = "rule_based"
) -> list[Requirement]:
    """从 JD 原文抽取要求，每条都带可回指且定义计量单位的 `source_span`。

    规则：只用原文中的显式标记分级；映射不到能力维度或等级不可判定的条目
    一律跳过，不猜、不补写（负责人决策 §5：禁止无来源 Requirement）。
    """
    requirements: list[Requirement] = []
    for span in split_sections(snapshot.raw_text):
        tier = classify_tier(span.section)
        if tier is None:
            continue
        for index, statement in enumerate(_split_statements(span.text)):
            competency = detect_competency(statement)
            if competency is None:
                continue
            # 在原文中精确匹配偏移
            start = snapshot.raw_text.find(statement, span.start)
            if start == -1:
                start = snapshot.raw_text.find(statement)
            if start == -1:
                continue
            end = start + len(statement)
            utf16_start = _utf16_code_units(snapshot.raw_text[:start])
            utf16_end = utf16_start + _utf16_code_units(statement)

            # 强校验：切片必须与 statement 严格逐字符一致
            assert snapshot.raw_text[start:end] == statement

            requirements.append(
                Requirement(
                    id=f"requirement_{hashlib.sha256(f'{snapshot.id}:{span.start}:{index}:{statement}'.encode()).hexdigest()[:16]}",
                    jd_snapshot_id=snapshot.id,
                    tier=tier,
                    competency_id=competency,
                    statement=statement,
                    source_span={
                        "section": span.section,
                        "start": start,
                        "end": end,
                        "quote": statement,
                        "unit": "unicode_code_point",
                        "utf16_start": utf16_start,
                        "utf16_end": utf16_end,
                    },
                    importance=importance_for(tier),
                    extraction=extraction,
                )
            )
    return requirements


def make_snapshot(
    *,
    snapshot_id: str,
    profile_id: str,
    raw_text: str,
    source_type: JDSourceType,
    source_name: str,
    version: int = 1,
    imported_at: str | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
    upstream_source_name: str | None = None,
    upstream_url: str | None = None,
    upstream_retrieved_at: str | None = None,
    upstream_content_hash: str | None = None,
    derived_artifact_path: str | None = None,
    derived_content_hash: str | None = None,
    transformation_note: str | None = None,
) -> JDSnapshot:
    normalized = validate_jd(raw_text)
    if not source_name.strip():
        raise JdRejected("JD_PROVENANCE_INVALID", "source_name 不能为空。")
    content_hash = JDSnapshot.compute_hash(normalized)
    direct_url, normalized_upstream_url, normalized_upstream_hash = (
        _validate_provenance(
            source_type=source_type,
            source_url=source_url,
            retrieved_at=retrieved_at,
            upstream_source_name=upstream_source_name,
            upstream_url=upstream_url,
            upstream_retrieved_at=upstream_retrieved_at,
            upstream_content_hash=upstream_content_hash,
            derived_artifact_path=derived_artifact_path,
            derived_content_hash=derived_content_hash,
            transformation_note=transformation_note,
            content_hash=content_hash,
        )
    )
    is_synthetic = source_type is JDSourceType.SYNTHETIC_DEMO_JD
    is_derived = source_type is JDSourceType.REAL_JD_DERIVED
    return JDSnapshot(
        id=snapshot_id,
        profile_id=profile_id,
        source_type=source_type,
        source_name=source_name,
        raw_text=normalized,
        content_hash=content_hash,
        imported_at=imported_at or datetime.now(UTC).isoformat(timespec="seconds"),
        version=version,
        status=JDStatus.ACTIVE,
        is_synthetic=is_synthetic,
        source_url=direct_url,
        retrieved_at=retrieved_at,
        derived=is_derived,
        upstream_source_name=upstream_source_name,
        upstream_url=normalized_upstream_url,
        upstream_retrieved_at=upstream_retrieved_at,
        upstream_content_hash=normalized_upstream_hash,
        derived_artifact_path=derived_artifact_path,
        derived_content_hash=derived_content_hash.lower()
        if derived_content_hash
        else None,
        transformation_note=transformation_note,
    )
