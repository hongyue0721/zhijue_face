"""Deployment deadlines use transport facts, never provider-speed estimates."""

from __future__ import annotations

import pytest

from zhijue.adapters.model import (
    ModelSettings,
    OpenAICompatibleAnswerAnalyzer,
    OpenAICompatibleContentGenerator,
)
from zhijue.api.app import AppConfig, resolve_model_workflow_timeout


def _settings(timeout):
    return ModelSettings(
        model_provider="fixture",
        model_name="fixture",
        api_base="https://model.example",
        api_key="fixture-secret",
        model_timeout=timeout,
        model_max_retries=0,
    )


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_global_policy_remains_unset_until_adapters_are_constructed(raw):
    env = {} if raw is None else {"ZHIJUE_MODEL_WORKFLOW_TIMEOUT_SECONDS": raw}
    config = AppConfig.from_env(env)
    assert config.model_workflow_timeout_seconds is None
    assert resolve_model_workflow_timeout(config, None) == 60.0


@pytest.mark.parametrize("raw", ["0", "-1", "nan", "inf", "-inf", "bad"])
def test_invalid_environment_deadline_is_rejected(raw):
    with pytest.raises(ValueError, match="finite positive number"):
        AppConfig.from_env({"ZHIJUE_MODEL_WORKFLOW_TIMEOUT_SECONDS": raw})


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "270"])
def test_invalid_constructor_deadline_is_rejected(value):
    with pytest.raises(ValueError, match="finite positive number"):
        AppConfig(model_workflow_timeout_seconds=value)


@pytest.mark.parametrize("timeout, expected", [(5, 60.0), (45, 75.0), (240, 270.0)])
@pytest.mark.parametrize(
    "adapter_class", [OpenAICompatibleAnswerAnalyzer, OpenAICompatibleContentGenerator]
)
def test_default_deadline_is_actual_adapter_request_budget_plus_margin(
    timeout, expected, adapter_class
):
    adapter = adapter_class(_settings(timeout))
    assert adapter.request_timeout_seconds == timeout
    assert resolve_model_workflow_timeout(AppConfig(), adapter) == expected


def test_analyzer_and_generator_defaults_are_resolved_independently():
    config = AppConfig()
    analyzer = OpenAICompatibleAnswerAnalyzer(_settings(45))
    generator = OpenAICompatibleContentGenerator(_settings(240))
    assert resolve_model_workflow_timeout(config, analyzer) == 75.0
    assert resolve_model_workflow_timeout(config, generator) == 270.0


@pytest.mark.parametrize("timeout", [0.25, 270.0])
def test_explicit_policy_overrides_transport_derived_deadlines_without_rejection(
    timeout,
):
    config = AppConfig.from_env({"ZHIJUE_MODEL_WORKFLOW_TIMEOUT_SECONDS": str(timeout)})
    analyzer = OpenAICompatibleAnswerAnalyzer(_settings(240))
    generator = OpenAICompatibleContentGenerator(_settings(45))
    assert config.model_workflow_timeout_seconds == timeout
    assert resolve_model_workflow_timeout(config, analyzer) == timeout
    assert resolve_model_workflow_timeout(config, generator) == timeout
    assert resolve_model_workflow_timeout(config, None) == timeout
