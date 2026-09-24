"""四个实验臂。

共同点（I5，runner 强制）：同一 case、同一 model、同一 temperature/reasoning_effort/
max_tokens/timeout、同一 transport、同一 JSON 信封要求、每 cell 一次生成。
唯一差别就是这里定义的事实约束强度。

- M0 vanilla            ：只给题面 + 原始回答，让它"优化"。
- M1 prompt_constraint  ：同输入 + 自然语言反编造禁令。
- M2 rag_context        ：M1 + 检索到的候选人事实上下文（不要求引用）。
- M3 evidence_bound     ：M2 的同一份有序证据 + 逐 segment 来源绑定 + 确定性硬校验。

约束：方法层永远拿不到 ground truth、trap claims 与 evaluator 标签；构造请求时会把
这些文本当作禁词扫一遍（结构上丢弃 + 出口扫描双保险）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from zhijue_research.dataset.models import GeneratorCaseView
from zhijue_research.evidence import EvidenceSet
from zhijue_research.methods.base import (
    TASK_ANSWER_ONLY,
    TASK_ANSWER_WITH_EVIDENCE,
    TASK_EVIDENCE_BOUND,
    MethodError,
    MethodItem,
    MethodRequest,
    allowed_claims_from,
    answers_by_root,
    evidence_block,
    normalize_evidence_bound,
    normalize_open_envelope,
    report_id_for,
    root_id_for,
    root_questions,
)
from zhijue_research.prompts import Prompt

#: 真值/标签的结构键名；出现在请求体里即说明投影失败。
LABEL_MARKERS = (
    "ground_truth",
    "trap_id",
    "expected_labels",
    "injected_drift",
    "provenance",
)

#: 生成侧禁止出现的文本（trap 错误说法 + evaluator 标签），由 runner 从数据集注入。
#: 空集合是显式事实：该 candidate 没有登记任何 trap。
EMPTY_FORBIDDEN: tuple[str, ...] = ()


class BaseMethod:
    """共享输入组装与出口泄漏守卫；子类只改 prompt 与输出契约。"""

    method_id = ""
    task = TASK_ANSWER_ONLY
    requires_evidence = False
    hard_validation = False

    def build_request(
        self,
        *,
        case: GeneratorCaseView,
        evidence: EvidenceSet | None,
        prompt: Prompt,
        forbidden_values: Sequence[str] = EMPTY_FORBIDDEN,
    ) -> MethodRequest:
        if prompt.method_id != self.method_id:
            raise MethodError(
                f"prompt 注册到了 {prompt.method_id}，不是 {self.method_id}"
            )
        if self.requires_evidence and evidence is None:
            raise MethodError(f"{self.method_id} 需要检索证据，但 evidence=None")
        if (
            not self.requires_evidence
            and evidence is not None
            and self.task != TASK_ANSWER_ONLY
        ):
            raise MethodError(f"{self.method_id} 不应接收证据")
        payload = self._payload(case=case, evidence=evidence)
        self._assert_no_ground_truth(payload, forbidden_values)
        return MethodRequest(
            system_prompt=prompt.text,
            payload=payload,
            evidence=evidence,
            hard_validation=self.hard_validation,
        )

    def _payload(
        self, *, case: GeneratorCaseView, evidence: EvidenceSet | None
    ) -> dict[str, Any]:
        raise NotImplementedError

    def normalize(self, candidate: dict[str, Any]) -> tuple[MethodItem, ...]:
        return normalize_open_envelope(candidate)

    @staticmethod
    def base_input(case: GeneratorCaseView) -> dict[str, Any]:
        """四臂共用的输入块：只有题面与候选人自己说的话。"""

        return {
            "task": "rewrite_interview_answer",
            "case_id": case.case_id,
            "root_question_id": root_id_for(case),
            "question": case.question_wording,
            "answer_turns": [
                {"answer_id": answer_id, "kind": kind, "text": text}
                for answer_id, kind, text in case.turns
            ],
        }

    def _assert_no_ground_truth(
        self, payload: Any, forbidden_values: Sequence[str]
    ) -> None:
        """出口守卫：真值/trap 文本与标签结构键都不允许出现在送给模型的请求里。"""

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for needle in {
            str(value) for value in forbidden_values if len(str(value)) >= 8
        }:
            if needle in serialized:
                raise MethodError(
                    f"LEAKAGE_BLOCKED：{self.method_id} 请求体含真值/trap 片段 {needle[:24]}…"
                )
        for marker in LABEL_MARKERS:
            if f'"{marker}"' in serialized:
                raise MethodError(
                    f"LEAKAGE_BLOCKED：{self.method_id} 请求体出现标签结构键 {marker}"
                )


class VanillaMethod(BaseMethod):
    method_id = "vanilla"
    task = TASK_ANSWER_ONLY
    requires_evidence = False
    hard_validation = False

    def _payload(
        self, *, case: GeneratorCaseView, evidence: EvidenceSet | None
    ) -> dict[str, Any]:
        del evidence
        return self.base_input(case)


class PromptConstraintMethod(BaseMethod):
    method_id = "prompt_constraint"
    task = TASK_ANSWER_ONLY
    requires_evidence = False
    hard_validation = False

    def _payload(
        self, *, case: GeneratorCaseView, evidence: EvidenceSet | None
    ) -> dict[str, Any]:
        del evidence
        return self.base_input(case)


class RagContextMethod(BaseMethod):
    method_id = "rag_context"
    task = TASK_ANSWER_WITH_EVIDENCE
    requires_evidence = True
    hard_validation = False

    def _payload(
        self, *, case: GeneratorCaseView, evidence: EvidenceSet | None
    ) -> dict[str, Any]:
        payload = self.base_input(case)
        payload["candidate_facts"] = evidence_block(_require(evidence))
        return payload


class EvidenceBoundMethod(BaseMethod):
    """复用生产 `validate_coaching_candidate`：payload 字段名与 M4-02 完全一致。"""

    method_id = "evidence_bound"
    task = TASK_EVIDENCE_BOUND
    requires_evidence = True
    hard_validation = True

    def _payload(
        self, *, case: GeneratorCaseView, evidence: EvidenceSet | None
    ) -> dict[str, Any]:
        bound = _require(evidence)
        payload = self.base_input(case)
        payload.update(
            {
                "report_id": report_id_for(case),
                "answers_by_root": answers_by_root(case),
                "root_questions": root_questions(case),
                "allowed_claims": allowed_claims_from(bound),
                "candidate_facts": evidence_block(bound),
            }
        )
        return payload

    def normalize(self, candidate: dict[str, Any]) -> tuple[MethodItem, ...]:
        return normalize_evidence_bound(candidate)


def _require(evidence: EvidenceSet | None) -> EvidenceSet:
    if evidence is None:
        raise MethodError("EVIDENCE_REQUIRED")
    return evidence


#: runner 按配置顺序实例化；顺序即论文表格的列顺序。
ALL_METHODS: tuple[BaseMethod, ...] = (
    VanillaMethod(),
    PromptConstraintMethod(),
    RagContextMethod(),
    EvidenceBoundMethod(),
)

METHOD_BY_ID: dict[str, BaseMethod] = {
    method.method_id: method for method in ALL_METHODS
}
