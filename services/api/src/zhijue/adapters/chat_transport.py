"""Shared OpenAI-compatible chat/completions transport.

职责边界（唯一 HTTP 实现，避免不同调用方因 transport 差异形成混杂变量）：
组装一次 chat/completions 请求（messages / model / temperature / reasoning_effort /
response_format / max_tokens）、以 SSE 流式发送、解析 content 与 usage，返回
`AnalysisResult`。

不在本模块：system prompt 语义、业务 payload 字段、Observation/Candidate 解析、
重试编排（重试是父链 Operation 的职责，不做隐藏重发）。

安全约束与 d91023a 逐字保持：HTTPS-only 基址、`follow_redirects=False`、
`trust_env=False`、`MODEL_TIMEOUT` 为单请求总预算、块间静默取
`min(MODEL_STREAM_STALL_SECONDS, MODEL_TIMEOUT)`、`reasoning_content` 永不进入
业务结果、缺 `[DONE]` 或空 content 视为失败。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

import httpx

from zhijue.application.answer_workflow import (
    AnalysisResult,
    ModelRequestError,
    ModelRequestTimeoutError,
)

JSON_OBJECT_RESPONSE_FORMAT: dict[str, Any] = {"type": "json_object"}


class ChatTransportSettings(Protocol):
    """`ModelSettings` 的结构化子集；避免与配置模块形成导入环。"""

    @property
    def model_name(self) -> str: ...

    @property
    def api_base(self) -> str: ...

    @property
    def api_key(self) -> Any: ...

    @property
    def model_timeout(self) -> float: ...

    @property
    def model_stream_stall_seconds(self) -> float: ...

    @property
    def model_reasoning_effort(self) -> str: ...

    @property
    def total_attempts(self) -> int: ...


class OpenAICompatibleChatTransport:
    """One streamed chat/completions request per call; never re-sends silently."""

    def __init__(
        self,
        settings: ChatTransportSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    @property
    def max_total_attempts(self) -> int:
        """Shared model-call budget enforced by parent-linked operations."""

        return self._settings.total_attempts

    @property
    def client(self) -> httpx.AsyncClient | None:
        """Exposed so adapters can inject a test transport without private access."""

        return self._client

    def build_payload(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = JSON_OBJECT_RESPONSE_FORMAT,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Key order is part of the frozen wire contract; do not reorder.

        `max_tokens` 只在显式给出时出现：默认（None）请求体与 d91023a 逐字节相同。
        """

        payload: dict[str, Any] = {
            "model": self._settings.model_name,
            "temperature": temperature,
            "reasoning_effort": self._settings.model_reasoning_effort,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if response_format is not None:
            payload["response_format"] = response_format
        payload["messages"] = messages
        return payload

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = JSON_OBJECT_RESPONSE_FORMAT,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> AnalysisResult:
        payload = self.build_payload(
            messages=messages,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if self._client is not None:
            response_data = await self._post_once(self._client, payload)
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.model_timeout),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response_data = await self._post_once(client, payload)
        return self._parse_response(response_data)

    async def _post_once(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Issue one billable request as a streamed completion.

        Streaming keeps the connection observably active while the provider
        thinks and writes JSON: MODEL_TIMEOUT stays the total per-request
        budget, while the stall budget catches a dead stream early. Retries
        remain explicit parent-linked operations, never hidden re-sends.
        """

        url = f"{self._settings.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        request_payload = {
            **payload,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        timeout = httpx.Timeout(
            connect=min(10.0, self._settings.model_timeout),
            read=min(
                self._settings.model_stream_stall_seconds,
                self._settings.model_timeout,
            ),
            write=self._settings.model_timeout,
            pool=self._settings.model_timeout,
        )
        try:
            async with asyncio.timeout(self._settings.model_timeout):
                async with client.stream(
                    "POST",
                    url,
                    json=request_payload,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        await response.aread()
                        raise ModelRequestError(
                            f"model request failed with HTTP {response.status_code}"
                        )
                    return await self._collect_stream(response)
        except TimeoutError as exc:
            raise ModelRequestTimeoutError("model request timed out") from exc
        except httpx.TimeoutException as exc:
            raise ModelRequestTimeoutError("model request timed out") from exc
        except httpx.NetworkError as exc:
            raise ModelRequestError("model request failed") from exc

    @staticmethod
    async def _collect_stream(response: httpx.Response) -> dict[str, Any]:
        """Assemble SSE content deltas into the existing one-choice shape.

        ``reasoning_content`` deltas are deliberately dropped: chain-of-thought
        text is never business content and must not leak into candidates.
        """

        content_parts: list[str] = []
        usage: dict[str, Any] = {}
        finish_reason: Any = None
        done = False
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                done = True
                break
            try:
                chunk = json.loads(body)
            except ValueError as exc:
                raise ModelRequestError(
                    "model stream returned a malformed SSE chunk"
                ) from exc
            if not isinstance(chunk, dict):
                raise ModelRequestError("model stream chunk must be an object")
            chunk_usage = chunk.get("usage")
            if isinstance(chunk_usage, dict):
                usage = chunk_usage
            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            first = choices[0]
            if not isinstance(first, dict):
                continue
            if first.get("finish_reason") is not None:
                finish_reason = first["finish_reason"]
            delta = first.get("delta")
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str) and content:
                content_parts.append(content)
        if not done:
            raise ModelRequestError("model stream ended without [DONE]")
        content = "".join(content_parts)
        if not content.strip():
            raise ModelRequestError("model response choice has no JSON content")
        return {
            "choices": [
                {"message": {"content": content}, "finish_reason": finish_reason}
            ],
            "usage": usage,
        }

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> AnalysisResult:
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ModelRequestError("model response must contain exactly one choice")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ModelRequestError("model response choice has no JSON content")
        finish_reason = (
            choice.get("finish_reason") if isinstance(choice, dict) else None
        )

        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}

        def optional_token(field: str) -> int | None:
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
            return None

        return AnalysisResult(
            content=content,
            input_tokens=optional_token("prompt_tokens"),
            output_tokens=optional_token("completion_tokens"),
            total_tokens=optional_token("total_tokens"),
            cost=None,
            finish_reason=(finish_reason if isinstance(finish_reason, str) else None),
        )
