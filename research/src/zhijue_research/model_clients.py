"""模型客户端：live 臂复用 R1 抽出的共享 transport，scripted 臂零网络。

两臂实现同一个 `ModelClient` 协议，因此 runner/Workflow/trace 代码路径完全相同；
差异只在"谁产生文本"，不在"怎么产生"。这正是实验公平性的要求（I5）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from zhijue.application.answer_workflow import AnalysisResult

from zhijue_research.config import ModelParams


class ModelClient(Protocol):
    """`method_id` 只服务 scripted 臂的查表；live 臂忽略它，参数保持同形。"""

    async def complete(
        self, *, system_prompt: str, user_payload: dict[str, Any], method_id: str = ""
    ) -> AnalysisResult: ...


def user_message(payload: dict[str, Any]) -> str:
    """与生产同构：user content 是一条排序稳定的 JSON，业务数据永远是数据不是指令。"""

    return json.dumps(
        {
            "data_classification": "untrusted_research_candidate_data",
            "requested_output": "interview_answer_rewrite",
            **payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class TransportModelClient:
    """真实调用：只允许在 `allow_paid_calls=true` 且显式 live 驱动下被构造。"""

    def __init__(self, *, transport, model: ModelParams) -> None:
        self._transport = transport
        self._model = model
        self.calls = 0

    @property
    def call_count(self) -> int:
        return self.calls

    driver_kind = "live"

    async def complete(
        self, *, system_prompt: str, user_payload: dict[str, Any], method_id: str = ""
    ) -> AnalysisResult:
        del method_id
        self.calls += 1
        return await self._transport.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message(user_payload)},
            ],
            response_format={"type": "json_object"},
            temperature=self._model.temperature,
            max_tokens=self._model.max_tokens,
        )


@dataclass(slots=True)
class ScriptedModelClient:
    """离线脚本模型：`responder(method_id, payload) -> 文本`。

    它不是"更聪明的模拟器"，只是可控输入，用来验证 harness、trace 与 evaluator 的
    正确性。任何 scripted 结果都不得被描述成真实模型结果；缺预置输出时直接抛错，
    绝不现编一段话让实验"看起来跑通了"。
    """

    responder: Any
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        """实际调用次数；I3「每 cell 一次」由它证明，不是配置自我声明。"""

        return len(self.calls)

    driver_kind = "scripted"

    async def complete(
        self, *, system_prompt: str, user_payload: dict[str, Any], method_id: str = ""
    ) -> AnalysisResult:
        content = self.responder(method_id, user_payload)
        if content is None:
            raise KeyError(f"scripted 模型缺少 {method_id} 的预置输出；不允许静默编造")
        self.calls.append(
            {
                "method_id": method_id,
                "system_prompt": system_prompt,
                "payload": user_payload,
            }
        )
        return AnalysisResult(
            content=content,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            finish_reason="stop",
        )


class RaisingModelClient:
    """失败注入：验证"模型没返回文本"时 trace 仍然完整且不调用第二次。"""

    #: schema 的 model_driver 只允许 live/scripted/fixture；失败注入属于 fixture 类驱动。
    driver_kind = "fixture"

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls = 0

    @property
    def call_count(self) -> int:
        return self.calls

    async def complete(
        self, *, system_prompt: str, user_payload: dict[str, Any], method_id: str = ""
    ) -> AnalysisResult:
        del system_prompt, user_payload, method_id
        self.calls += 1
        raise self._error


@dataclass(slots=True)
class PromptBoundGenerator:
    """业务 Workflow 的 `ContentGenerator` 适配器：一个 cell 一个实例。

    Workflow 负责编排与 SemanticValidation；本对象只把方法自己的 system prompt 与
    payload 交给 ModelClient。方法差异全部留在 Strategy 层。
    """

    method_id: str
    system_prompt: str
    client: Any

    async def generate(self, *, task: str, payload: dict[str, Any]) -> AnalysisResult:
        del task
        return await self.client.complete(
            system_prompt=self.system_prompt,
            user_payload=payload,
            method_id=self.method_id,
        )
