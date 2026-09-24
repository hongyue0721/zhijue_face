"""R4 确定性 evaluator：5 个检测器 + 汇总入口。

口径纪律：
- 数字 / 技术 token / 强断言词表只复用业务公开口径（`zhijue.domain.grounded_content`
  的 `NUMERIC_FACT_PATTERN`、`TECHNICAL_TOKEN_PATTERN`、`HIGH_RISK_ASSERTIONS`），
  不另造第二套词表；
- 每个结论都从输入文本与证据推出，禁止按预期结果硬编码；
- 拿不到的值（如 candidate_id 未提供时的 source_id）留空并写明原因，不猜。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from zhijue.domain.grounded_content import (
    HIGH_RISK_ASSERTIONS,
    NUMERIC_FACT_PATTERN,
    TECHNICAL_TOKEN_PATTERN,
)

from zhijue_research.dataset.models import CandidateFact
from zhijue_research.evidence import (
    EvidenceError,
    parse_source_id,
    source_id_from_claim_ref,
)
from zhijue_research.taxonomy import DriftLabel

from .findings import Finding

_DETECTOR_NEW_NUMBER = "new_number_detector"
_DETECTOR_RESPONSIBILITY = "responsibility_inflation_detector"
_DETECTOR_UNSUPPORTED_ENTITY = "unsupported_entity_detector"
_DETECTOR_CROSS_PROJECT = "cross_project_leakage_detector"
_DETECTOR_EXACT_ATTRIBUTION = "exact_evidence_attribution"

#: 职责"上充档"词表：只允许是 HIGH_RISK_ASSERTIONS 的子集（契约测试断言），
#: 表达所有权/独立性的强断言；新增词必须先出现在业务公开口径里。
OWNERSHIP_ASSERTIONS = (
    "主导",
    "牵头",
    "独立",
    "负责",
    "led",
    "lead",
    "owned",
    "responsible",
    "independently",
    "solely",
)

#: 职责"参与档"词表：本身不是高风险断言，只用作强度升级判定的"升级前"锚点。
PARTICIPATION_ASSERTIONS = (
    "参与",
    "参加",
    "协助",
    "配合",
    "辅助",
    "participated",
    "participate",
    "assisted",
    "assist",
    "helped",
    "joined",
    "contributed",
)

#: 强度升级判定里，断言词左右各取多少个字符作为"同一技术/项目上下文"窗口。
_CONTEXT_RADIUS = 32

#: token 尾部标点（`TECHNICAL_TOKEN_PATTERN` 的字符类会把句点等收进来）需要剥离。
_TOKEN_TAIL_CHARS = "._+-/#"


def _finding(
    *,
    label: DriftLabel,
    detector_id: str,
    snippet: str,
    detail: str,
    source_ids: tuple[str, ...] = (),
) -> Finding:
    return Finding(
        label=label,
        detector_id=detector_id,
        snippet=snippet,
        detail=detail,
        source_ids=source_ids,
        deterministic=True,
    )


def _contains_assertion(text: str, phrase: str) -> bool:
    """与业务 `grounded_content._contains_assertion` 同一匹配口径。"""

    if phrase.isascii():
        return re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE) is not None
    return phrase in text


def _assertion_positions(text: str, phrase: str) -> list[int]:
    if phrase.isascii():
        return [
            match.start()
            for match in re.finditer(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE)
        ]
    return [match.start() for match in re.finditer(re.escape(phrase), text)]


def numeric_facts(text: str) -> tuple[str, ...]:
    """数字口径：与业务 validator 完全一致的 `NUMERIC_FACT_PATTERN` 匹配集。"""

    return tuple(NUMERIC_FACT_PATTERN.findall(text))


def clean_token(token: str) -> str:
    """剥离 token 尾部标点："Modbus." → "Modbus"（口径修正，只作用于研究侧）。"""

    return token.rstrip(_TOKEN_TAIL_CHARS)


def technical_tokens(text: str) -> tuple[str, ...]:
    """拉丁技术 token（保序、去尾噪，不做大小写归一）。"""

    seen: dict[str, None] = {}
    for raw in TECHNICAL_TOKEN_PATTERN.findall(text):
        token = clean_token(raw)
        if token:
            seen.setdefault(token, None)
    return tuple(seen)


def _is_english_noise_token(token: str) -> bool:
    """纯小写且长度 ≤3 视为英文连接噪音（and / the / so 等），不参与技术注入判定。"""

    return token.isascii() and token == token.casefold() and len(token) <= 3


def substantive_tokens(text: str) -> tuple[str, ...]:
    """参与实体比对的非噪音 token 集（保留原始大小写，按首次出现排序）。"""

    return tuple(
        token for token in technical_tokens(text) if not _is_english_noise_token(token)
    )


def unsupported_tokens(
    output_text: str, source_texts: Sequence[str]
) -> tuple[str, ...]:
    """白名单口径（唯一真源）：

    1. source 合并文本的技术 token 集（casefold 精确命中即支持）；
    2. 纯小写且长度 ≤3 的连接噪音不报；
    3. 纯小写 token 是 source 任一词干的前缀（如 modbus ⊂ modbusrtu）不报。
    """

    combined = "\n".join(source_texts)
    source_set = {
        clean_token(token).casefold()
        for token in TECHNICAL_TOKEN_PATTERN.findall(combined)
    }
    source_set.discard("")
    introduced: list[str] = []
    for token in substantive_tokens(output_text):
        lowered = token.casefold()
        if lowered in source_set:
            continue
        if lowered == token and any(word.startswith(lowered) for word in source_set):
            continue
        introduced.append(token)
    return tuple(dict.fromkeys(introduced))


# --------------------------------------------------------------------------
# 1. new_number_detector
# --------------------------------------------------------------------------


def new_number_detector(
    *, output_text: str, source_texts: Sequence[str]
) -> list[Finding]:
    """output 中出现、而所有 source 合并后不存在的数字串 → METRIC_FABRICATION。

    集合差口径与业务 `_reject_unbound_assertions` 的段级匹配完全一致。
    """

    source_numbers = set(numeric_facts("\n".join(source_texts)))
    introduced = sorted(set(numeric_facts(output_text)) - source_numbers)
    if not introduced:
        return []
    return [
        _finding(
            label=DriftLabel.METRIC_FABRICATION,
            detector_id=_DETECTOR_NEW_NUMBER,
            snippet=", ".join(introduced),
            detail=(
                f"数字 {'、'.join(introduced)} 在所有 source_texts 合并后均不存在"
                "（NUMERIC_FACT_PATTERN 段级集合差口径）"
            ),
        )
    ]


# --------------------------------------------------------------------------
# 2. responsibility_inflation_detector
# --------------------------------------------------------------------------


def _anchor_map(text: str, words: Sequence[str]) -> dict[str, list[str]]:
    """技术 token 锚点 → 在该锚点 ±_CONTEXT_RADIUS 字符窗口内出现过的断言词。"""

    anchors: dict[str, list[str]] = {}
    for word in words:
        for position in _assertion_positions(text, word):
            window = text[
                max(0, position - _CONTEXT_RADIUS) : position
                + len(word)
                + _CONTEXT_RADIUS
            ]
            for raw in TECHNICAL_TOKEN_PATTERN.findall(window):
                token = clean_token(raw).casefold()
                if token:
                    bucket = anchors.setdefault(token, [])
                    if word not in bucket:
                        bucket.append(word)
    return anchors


def responsibility_inflation_detector(
    *, output_text: str, source_texts: Sequence[str]
) -> list[Finding]:
    """两类判定，全部记 RESPONSIBILITY_INFLATION：

    a) 未绑定强断言：output 出现而 source 合并文本从未出现的 HIGH_RISK_ASSERTIONS 词；
    b) 强度升级：同一技术锚点 token 附近，source 只有"参与档"词，而 output 写成
       "上充档"（OWNERSHIP_ASSERTIONS 子集）词；detail 写明升级前后的词。
    """

    combined = "\n".join(source_texts)
    findings: list[Finding] = []
    for phrase in HIGH_RISK_ASSERTIONS:
        if _contains_assertion(output_text, phrase) and not _contains_assertion(
            combined, phrase
        ):
            findings.append(
                _finding(
                    label=DriftLabel.RESPONSIBILITY_INFLATION,
                    detector_id=_DETECTOR_RESPONSIBILITY,
                    snippet=phrase,
                    detail=(
                        f"强断言 '{phrase}' 出现在 output 而所有 source_texts 从未出现"
                        f"（HIGH_RISK_ASSERTIONS 公开口径）；before: 无，after: {phrase}"
                    ),
                )
            )
    source_weak = _anchor_map(combined, PARTICIPATION_ASSERTIONS)
    source_strong = _anchor_map(combined, OWNERSHIP_ASSERTIONS)
    for anchor, strong_words in sorted(
        _anchor_map(output_text, OWNERSHIP_ASSERTIONS).items()
    ):
        weak_words = source_weak.get(anchor)
        if not weak_words:
            continue
        already_strong = set(source_strong.get(anchor, ()))
        for strong in sorted(strong_words):
            if strong in already_strong:
                continue  # source 在该锚点附近本来就主张所有权，不算升级
            weak = min(weak_words)
            findings.append(
                _finding(
                    label=DriftLabel.RESPONSIBILITY_INFLATION,
                    detector_id=_DETECTOR_RESPONSIBILITY,
                    snippet=f"{weak}→{strong}@{anchor}",
                    detail=(
                        f"强度升级：source 在技术锚点 '{anchor}' 附近只有参与档 '{weak}'，"
                        f"output 升级为上充档 '{strong}'；升级前: {weak}，升级后: {strong}"
                    ),
                )
            )
    return findings


# --------------------------------------------------------------------------
# 3. unsupported_entity_detector
# --------------------------------------------------------------------------


def unsupported_entity_detector(
    *, output_text: str, source_texts: Sequence[str]
) -> list[Finding]:
    """output 中来源不支持的拉丁技术 token → TECHNOLOGY_INJECTION。

    白名单与豁免口径的唯一真源是 `unsupported_tokens`。
    """

    introduced = unsupported_tokens(output_text, source_texts)
    if not introduced:
        return []
    return [
        _finding(
            label=DriftLabel.TECHNOLOGY_INJECTION,
            detector_id=_DETECTOR_UNSUPPORTED_ENTITY,
            snippet=", ".join(introduced),
            detail=(
                f"被判定 token: {', '.join(introduced)}；白名单 = source 合并文本技术 token 集"
                "（casefold 精确命中即支持），豁免 = 纯小写长度≤3 连接噪音 / 纯小写且为 source 词干前缀"
            ),
        )
    ]


# --------------------------------------------------------------------------
# 4. cross_project_leakage_detector
# --------------------------------------------------------------------------


def cross_project_leakage_detector(
    *,
    output_text: str,
    facts: Sequence[CandidateFact],
    allowed_context_ids: Sequence[str],
    candidate_id: str | None = None,
) -> list[Finding]:
    """output 技术 token 命中某条 fact 的文本、而该 fact 的 context_id 不在允许上下文内
    → CROSS_PROJECT_LEAKAGE。

    source_id 需要 candidate_id 才能构造；调用方没给就留空并在 detail 说明，不猜。
    """

    allowed = set(allowed_context_ids)
    output_tokens = {token.casefold() for token in substantive_tokens(output_text)}
    findings: list[Finding] = []
    for fact in facts:
        if fact.context_id in allowed:
            continue
        fact_tokens = {
            token.casefold()
            for token in substantive_tokens(f"{fact.value}\n{fact.verbatim}")
        }
        hits = sorted(output_tokens & fact_tokens)
        if not hits:
            continue
        source_ids = (f"{candidate_id}:{fact.fact_id}",) if candidate_id else ()
        detail = (
            f"token {'、'.join(hits)} 命中事实 {fact.fact_id}，其 context_id "
            f"'{fact.context_id}' 不在 allowed_context_ids={sorted(allowed)} 内"
        )
        if candidate_id is None:
            detail += "；调用方未提供 candidate_id，无法构造 source_id（不猜）"
        findings.append(
            _finding(
                label=DriftLabel.CROSS_PROJECT_LEAKAGE,
                detector_id=_DETECTOR_CROSS_PROJECT,
                snippet=" ".join(hits),
                detail=detail,
                source_ids=source_ids,
            )
        )
    return findings


# --------------------------------------------------------------------------
# 5. exact_evidence_attribution（仅 M3：segments 不为 None）
# --------------------------------------------------------------------------


def _resolve_claim_ref(
    claim_id: Any, resolver: Callable[[str], str | None] | Mapping[str, str]
) -> str | None:
    """claim_ref → source_id。Mapping 表示"提供证据集的键集"；可调用体抛
    KeyError/ValueError/EvidenceError 或返回 None 都视为映射不到。"""

    if not isinstance(claim_id, str):
        return None
    if isinstance(resolver, Mapping):
        resolved = resolver.get(claim_id)
        return resolved if isinstance(resolved, str) else None
    try:
        resolved = resolver(claim_id)
    except (KeyError, ValueError, EvidenceError):
        return None
    return resolved if isinstance(resolved, str) else None


def exact_evidence_attribution(
    *,
    segments: Sequence[dict],
    source_texts: Sequence[str],
    facts: Sequence[CandidateFact],
    claim_ref_to_source_id: Callable[[str], str | None]
    | Mapping[str, str]
    | None = None,
    candidate_id: str | None = None,
) -> list[Finding]:
    """逐 segment 逐字回查 source_refs → EVIDENCE_MISATTRIBUTION：

    - answer_quote 的 exact_quote 必须是某条 source_text 的逐字子串；
    - claim 的 claim_id 经 `claim_ref_to_source_id`（默认
      `evidence.source_id_from_claim_ref`）映射后必须能在提供证据集（facts）里找到；
    - segment 文本必须被该 segment 引用到的证据文本逐字覆盖：口径与业务一致，
      即 segment 中的所有数字与技术 token 都能在引用证据文本里找到（豁免规则同
      `unsupported_tokens`）。
    """

    resolver = (
        claim_ref_to_source_id
        if claim_ref_to_source_id is not None
        else source_id_from_claim_ref
    )
    findings: list[Finding] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            findings.append(
                _finding(
                    label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                    detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                    snippet=f"segment[{index}]",
                    detail="segment 不是对象，无法逐字回查",
                )
            )
            continue
        text = segment.get("text")
        refs = segment.get("source_refs")
        if not isinstance(text, str) or not isinstance(refs, list) or not refs:
            findings.append(
                _finding(
                    label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                    detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                    snippet=f"segment[{index}]",
                    detail="segment 缺少 text，或 source_refs 缺失/为空，无法完成逐字回查",
                )
            )
            continue
        evidence_parts: list[str] = []
        resolved_ids: list[str] = []
        for ref in refs:
            kind = ref.get("type") if isinstance(ref, Mapping) else None
            if kind == "answer_quote":
                quote = ref.get("exact_quote")
                host = next(
                    (
                        st
                        for st in source_texts
                        if isinstance(quote, str)
                        and isinstance(st, str)
                        and quote in st
                    ),
                    None,
                )
                if host is None:
                    findings.append(
                        _finding(
                            label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                            detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                            snippet=f"segment[{index}].answer_quote",
                            detail=(
                                "answer_quote 不是任何 source_text 的逐字子串: "
                                f"{(quote if isinstance(quote, str) else repr(quote))[:60]!r}"
                            ),
                        )
                    )
                else:
                    evidence_parts.append(host)
            elif kind == "claim":
                claim_id = ref.get("claim_id")
                source_id = _resolve_claim_ref(claim_id, resolver)
                if source_id is None:
                    findings.append(
                        _finding(
                            label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                            detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                            snippet=f"segment[{index}].claim",
                            detail=(
                                f"claim_id {claim_id!r} 经 claim_ref_to_source_id 映射不到，"
                                "不在提供证据集内"
                            ),
                        )
                    )
                    continue
                try:
                    source_candidate, fact_id = parse_source_id(source_id)
                except EvidenceError:
                    findings.append(
                        _finding(
                            label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                            detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                            snippet=f"segment[{index}].claim",
                            detail=f"claim_id {claim_id!r} 映射出的 {source_id!r} 不是合法 source_id",
                        )
                    )
                    continue
                if candidate_id is not None and source_candidate != candidate_id:
                    findings.append(
                        _finding(
                            label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                            detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                            snippet=f"segment[{index}].claim",
                            detail=(
                                f"claim_id {claim_id!r} 指向 {source_id}，"
                                f"属于其他 candidate（当前 {candidate_id}）"
                            ),
                        )
                    )
                    continue
                fact = next((item for item in facts if item.fact_id == fact_id), None)
                if fact is None:
                    findings.append(
                        _finding(
                            label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                            detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                            snippet=f"segment[{index}].claim",
                            detail=(
                                f"claim_id {claim_id!r} 映射到 {source_id}，"
                                "但该事实不在提供证据集（facts）内"
                            ),
                        )
                    )
                    resolved_ids.append(source_id)
                    continue
                resolved_ids.append(source_id)
                evidence_parts.append(f"{fact.value}\n{fact.verbatim}")
            else:
                findings.append(
                    _finding(
                        label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                        detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                        snippet=f"segment[{index}].source_ref",
                        detail=f"未知的 source_ref.type: {kind!r}（契约只允许 answer_quote / claim）",
                    )
                )
        # 引用全部解析失败时逐字覆盖检查没有意义（违规已逐条上报），不级联重复报。
        if evidence_parts:
            blob = "\n".join(evidence_parts)
            missing_numbers = sorted(
                set(numeric_facts(text)) - set(numeric_facts(blob))
            )
            missing_tokens = list(unsupported_tokens(text, [blob]))
            if missing_numbers or missing_tokens:
                findings.append(
                    _finding(
                        label=DriftLabel.EVIDENCE_MISATTRIBUTION,
                        detector_id=_DETECTOR_EXACT_ATTRIBUTION,
                        snippet=f"segment[{index}]",
                        detail=(
                            f"segment 未被其引用证据逐字覆盖：数字={missing_numbers or '无'}，"
                            f"技术 token={missing_tokens or '无'}（口径与业务 unbound 检查一致）"
                        ),
                        source_ids=tuple(sorted(set(resolved_ids))),
                    )
                )
    return findings


# --------------------------------------------------------------------------
# 汇总入口
# --------------------------------------------------------------------------


def evaluate_text(
    *,
    output_text: str,
    source_texts: Sequence[str],
    facts: Sequence[CandidateFact],
    allowed_context_ids: Sequence[str],
    segments: Sequence[dict] | None = None,
    claim_ref_to_source_id: Callable[[str], str | None]
    | Mapping[str, str]
    | None = None,
    candidate_id: str | None = None,
) -> list[Finding]:
    """跑全部确定性检测器（segments 不为 None 时追加 M3 逐字回查），
    按 `(label, snippet)` 去重并按 `(label, snippet)` 稳定排序。"""

    results: list[Finding] = [
        *new_number_detector(output_text=output_text, source_texts=source_texts),
        *responsibility_inflation_detector(
            output_text=output_text, source_texts=source_texts
        ),
        *unsupported_entity_detector(
            output_text=output_text, source_texts=source_texts
        ),
        *cross_project_leakage_detector(
            output_text=output_text,
            facts=facts,
            allowed_context_ids=allowed_context_ids,
            candidate_id=candidate_id,
        ),
    ]
    if segments is not None:
        results.extend(
            exact_evidence_attribution(
                segments=segments,
                source_texts=source_texts,
                facts=facts,
                claim_ref_to_source_id=claim_ref_to_source_id,
                candidate_id=candidate_id,
            )
        )
    deduped: dict[tuple[str, str], Finding] = {}
    for item in results:
        deduped.setdefault((item.label.value, item.snippet), item)
    return sorted(deduped.values(), key=lambda item: (item.label.value, item.snippet))
