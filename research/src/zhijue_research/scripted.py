"""Scripted 响应构造器（fixture，不是模型结果）。

用途只有一个：在没有真实模型参与的情况下，把 `case → retrieval → 四臂 → trace →
evaluator` 整条链路跑通，并证明"被 validator 拒绝的原始输出仍然保留"。

任何由本文件产生的数字都不得写进论文结论，也不得描述成真实模型表现。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from zhijue_research.methods.base import root_id_for


def open_envelope(payload: Mapping[str, Any], *, drift: bool = False) -> str:
    """M0/M1/M2 的最小 JSON 信封。

    `drift=True` 会故意引入来源里没有的数字与技术名，用来验证
    "无硬校验的臂会把捏造内容一路放行"这一 harness 事实（不是模型行为）。
    """

    root_id = str(payload["root_question_id"])
    answer = _first_answer(payload)
    rewritten = answer if answer else "我先复现问题，再定位边界。"
    if drift:
        rewritten = f"{rewritten}最终把错误率降低了 30%，并引入 Modbus 网关。"
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "case_id": payload.get("case_id"),
            "items": [{"root_question_id": root_id, "rewritten_answer": rewritten}],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def bound_envelope(payload: Mapping[str, Any], *, drift: bool = False) -> str:
    """M3 输出：逐 segment 绑定来源，复用生产 coaching-result 结构。

    `drift=True` 时故意引用快照外的 claim_id 或加入无来源数字，让确定性 validator
    拒绝——用于验证"拒绝也留痕、且不重调模型"。
    """

    root_id = str(payload["root_question_id"])
    answers: dict[str, str] = payload["answers_by_root"][root_id]
    answer_id, answer_text = min(answers.items())
    claims: dict[str, str] = payload.get("allowed_claims") or {}
    if drift:
        return json.dumps(
            {
                "schema_version": "1.0.0",
                "report_id": payload["report_id"],
                "items": [
                    {
                        "root_question_id": root_id,
                        "rewritten_answer": f"{answer_text}错误率降低 30%。",
                        "segments": [
                            {
                                "text": f"{answer_text}错误率降低 30%。",
                                "source_refs": [
                                    {
                                        "type": "answer_quote",
                                        "answer_id": answer_id,
                                        "exact_quote": answer_text,
                                    }
                                ],
                            }
                        ],
                        "used_claim_ids": [],
                        "changes": ["保留原证据范围"],
                        "missing_facts": [],
                        "cautions": [],
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    if claims:
        claim_ref, claim_text = min(claims.items())
        text = claim_text
        refs = [{"type": "claim", "claim_id": claim_ref}]
        used = [claim_ref]
    else:
        text = answer_text
        refs = [
            {"type": "answer_quote", "answer_id": answer_id, "exact_quote": answer_text}
        ]
        used = []
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "report_id": payload["report_id"],
            "items": [
                {
                    "root_question_id": root_id,
                    "rewritten_answer": text,
                    "segments": [{"text": text, "source_refs": refs}],
                    "used_claim_ids": used,
                    "changes": ["按来源重排表达"],
                    "missing_facts": [],
                    "cautions": [],
                }
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def responder(
    *, override: Mapping[str, str] | None = None, drift_methods: tuple[str, ...] = ()
) -> Callable[[str, dict[str, Any]], str | None]:
    """`ScriptedModelClient` 的 responder。

    `override[method_id]` 提供逐字文本（测试用）；否则按方法生成信封。
    `drift_methods` 列出要故意捏造的臂。
    """

    def answer(method_id: str, payload: dict[str, Any]) -> str | None:
        if override and method_id in override:
            return override[method_id]
        drift = method_id in drift_methods
        if method_id == "evidence_bound":
            return bound_envelope(payload, drift=drift)
        if method_id in {"vanilla", "prompt_constraint", "rag_context"}:
            return open_envelope(payload, drift=drift)
        return None

    return answer


def _first_answer(payload: Mapping[str, Any]) -> str:
    turns = payload.get("answer_turns") or []
    for turn in turns:
        text = str(turn.get("text", ""))
        if text:
            return text
    by_root = payload.get("answers_by_root") or {}
    for answers in by_root.values():
        for text in answers.values():
            if text:
                return str(text)
    return ""


__all__ = ["bound_envelope", "open_envelope", "responder", "root_id_for"]
