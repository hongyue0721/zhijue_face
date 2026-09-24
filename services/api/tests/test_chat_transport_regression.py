"""R1 回归：模型 transport 抽取后，线上请求与响应语义必须与 d91023a 逐字节一致。

基线由未改造前的适配器抓取（tests/fixtures/chat_transport_baseline.json），
包含 URL、header 名集、Accept、鉴权形态、**请求体原始字节（含键顺序）**、
解析后的 AnalysisResult，以及 reasoning_effort / retries 变体。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from zhijue.adapters.chat_transport import OpenAICompatibleChatTransport
from zhijue.adapters.model import (
    ModelSettings,
    OpenAICompatibleAnswerAnalyzer,
    OpenAICompatibleContentGenerator,
)
from zhijue.application.answer_workflow import AnalysisResult

BASELINE = json.loads(
    (Path(__file__).parent / "fixtures" / "chat_transport_baseline.json").read_text(
        encoding="utf-8"
    )
)

_SSE_OK = (
    b"".join(
        b"data: " + json.dumps(chunk).encode() + b"\n\n"
        for chunk in (
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]},
            {"choices": [{"index": 0, "delta": {"content": '{"ok":true}'}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )
    )
    + b"data: [DONE]\n\n"
)


def _settings(**overrides: Any) -> ModelSettings:
    base: dict[str, Any] = {
        "model_provider": "fixture-provider",
        "model_name": "fixture-model",
        "api_base": "https://model.example",
        "api_key": "fixture-secret",
        "model_timeout": 30,
        "model_max_retries": 2,
    }
    base.update(overrides)
    return ModelSettings(**base)


def _replay(settings: ModelSettings) -> dict[str, Any]:
    """Run the same call sequence the baseline capture used."""

    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "url": str(request.url),
                "header_names": sorted(request.headers.keys()),
                "accept": request.headers.get("accept"),
                "auth_shape": (
                    "bearer"
                    if request.headers.get("authorization", "").startswith("Bearer ")
                    else "other"
                ),
                "body": json.loads(request.content.decode("utf-8")),
                "body_text": request.content.decode("utf-8"),
                "body_raw_prefix": request.content.decode("utf-8")[:80],
            }
        )
        return httpx.Response(
            200, content=_SSE_OK, headers={"content-type": "text/event-stream"}
        )

    out: dict[str, Any] = {}
    with httpx.MockTransport(handler) as transport:
        client = httpx.AsyncClient(transport=transport)

        async def go() -> None:
            analyzer = OpenAICompatibleAnswerAnalyzer(settings, client=client)
            result = await analyzer.analyze(
                observation_id="obs_1",
                answer_id="ans_1",
                question_id="q_1",
                root_question_id="root_1",
                question_text="请描述一次串口错帧排查。",
                answer_text="我先记录复现条件，再对照 UART 日志。",
                rubric_snapshot={"level": "demo"},
                reference_material=None,
            )
            out["analyzer"] = seen[-1]
            out["analyzer_result"] = {
                "content": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "cost": result.cost,
                "usage": result.usage(),
            }
            generator = OpenAICompatibleContentGenerator(settings, client=client)
            for task in ("extract_claims", "coach_answers", "compose_resume"):
                await generator.generate(task=task, payload={"k": "v", "中文": 1})
                out[f"generator:{task}"] = seen[-1]
            out["max_total_attempts"] = generator.max_total_attempts
            out["public_summary"] = generator.public_summary()

        asyncio.run(go())
    return out


_WIRE_KEYS = ("method", "url", "header_names", "accept", "auth_shape", "body_text")


@pytest.mark.parametrize(
    "call",
    [
        "analyzer",
        "generator:extract_claims",
        "generator:coach_answers",
        "generator:compose_resume",
    ],
)
def test_request_wire_bytes_match_pre_refactor_baseline(call: str) -> None:
    recorded = _replay(_settings())[call]
    expected = BASELINE["default"][call]
    for key in _WIRE_KEYS:
        assert recorded[key] == expected[key], f"{call}.{key} 线上形态漂移"
    # 默认请求体不得出现 max_tokens：生产 payload 键集与基线一致。
    assert "max_tokens" not in recorded["body"]


def test_parsed_result_and_usage_facts_match_baseline() -> None:
    assert (
        _replay(_settings())["analyzer_result"]
        == BASELINE["default"]["analyzer_result"]
    )


@pytest.mark.parametrize("variant", sorted(BASELINE["variants"]))
def test_reasoning_effort_and_retry_varities_match_baseline(variant: str) -> None:
    settings_by_variant = {
        "no_retries": _settings(model_max_retries=0),
        "reasoning_high": _settings(model_reasoning_effort="high"),
        "reasoning_none": _settings(model_reasoning_effort="none"),
    }
    recorded = _replay(settings_by_variant[variant])
    expected = BASELINE["variants"][variant]
    for call in ("analyzer", "generator:coach_answers"):
        assert recorded[call]["body_text"] == expected[call]["body_text"]
    assert recorded["max_total_attempts"] == expected["max_total_attempts"]
    assert recorded["public_summary"] == expected["public_summary"]


def test_transport_is_shared_by_analyzer_and_generator() -> None:
    settings = _settings()
    analyzer = OpenAICompatibleAnswerAnalyzer(settings)
    generator = OpenAICompatibleContentGenerator(settings)
    assert isinstance(analyzer._transport, OpenAICompatibleChatTransport)
    assert isinstance(generator._transport, OpenAICompatibleChatTransport)
    # 复用同一实现：两条链路的 URL 组装与预算属性一致，不各写一套 HTTP。
    assert analyzer._transport._settings is settings
    assert generator._transport._settings is settings


def test_finish_reason_is_reported_when_provider_sends_it() -> None:
    result = _replay(_settings())
    assert (
        result["analyzer_result"]["usage"]
        == BASELINE["default"]["analyzer_result"]["usage"]
    )

    async def go() -> AnalysisResult:
        with httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=_SSE_OK,
                headers={"content-type": "text/event-stream"},
            )
        ) as transport:
            client = httpx.AsyncClient(transport=transport)
            return await OpenAICompatibleChatTransport(
                _settings(), client=client
            ).complete(messages=[{"role": "user", "content": "hi"}])

    assert asyncio.run(go()).finish_reason == "stop"


def test_finish_reason_stays_null_when_provider_omits_it() -> None:
    body = (
        b'data: {"choices":[{"index":0,"delta":{"content":"{\\"ok\\":1}"}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    async def go() -> AnalysisResult:
        with httpx.MockTransport(
            lambda request: httpx.Response(200, content=body)
        ) as transport:
            client = httpx.AsyncClient(transport=transport)
            return await OpenAICompatibleChatTransport(
                _settings(), client=client
            ).complete(messages=[{"role": "user", "content": "hi"}])

    result = asyncio.run(go())
    assert result.finish_reason is None
    # provider 未给 usage 时只能是 null，不得填 0。
    assert result.usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost": None,
    }


def test_explicit_max_tokens_and_sampling_params_are_the_only_payload_delta() -> None:
    payload_without = OpenAICompatibleChatTransport(_settings()).build_payload(
        messages=[{"role": "user", "content": "x"}]
    )
    payload_with = OpenAICompatibleChatTransport(_settings()).build_payload(
        messages=[{"role": "user", "content": "x"}], max_tokens=4096, temperature=0
    )
    assert list(payload_with) == [
        "model",
        "temperature",
        "reasoning_effort",
        "max_tokens",
        "response_format",
        "messages",
    ]
    assert payload_with.pop("max_tokens") == 4096
    assert payload_with == payload_without


def test_response_format_can_be_disabled_without_changing_other_keys() -> None:
    payload = OpenAICompatibleChatTransport(_settings()).build_payload(
        messages=[{"role": "user", "content": "x"}], response_format=None
    )
    assert "response_format" not in payload
    assert list(payload) == ["model", "temperature", "reasoning_effort", "messages"]
