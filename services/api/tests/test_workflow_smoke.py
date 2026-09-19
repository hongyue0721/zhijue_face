"""Real SDK tests; fault nodes are synthetic, framework entry points are not mocked."""

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from openjiuwen.core.workflow import WorkflowComponent

from smoke.workflow import checked_output, run_agent, run_workflow


class FailingNode(WorkflowComponent):
    async def invoke(self, inputs, session, context):
        raise RuntimeError("synthetic_node_failure")


class WaitingNode(WorkflowComponent):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def invoke(self, inputs, session, context):
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


@pytest.mark.parametrize("runner", [run_workflow, run_agent])
def test_real_sdk_output_and_repeat(runner):
    async def scenario():
        first = await runner("hello")
        second = await runner("hello")
        other = await runner("职觉 demo")
        assert first == second == {"response": "R=HELLO|tagged"}
        assert other == {"response": "R=职觉 DEMO|tagged"}

    asyncio.run(scenario())


@pytest.mark.parametrize("runner", [run_workflow, run_agent])
@pytest.mark.parametrize("text", [None, 123, "", " \t\n"])
def test_invalid_input_is_not_coerced(runner, text):
    with pytest.raises(ValueError, match="non-empty string"):
        asyncio.run(runner(text))


@pytest.mark.parametrize("runner", [run_workflow, run_agent])
def test_node_failure_then_fresh_execution(runner):
    async def scenario():
        with pytest.raises(Exception, match="synthetic_node_failure"):
            await runner("hello", component=FailingNode())
        assert await runner("hello") == {"response": "R=HELLO|tagged"}

    asyncio.run(scenario())


@pytest.mark.parametrize("runner", [run_workflow, run_agent])
def test_timeout_cancels_node_and_fresh_execution_recovers(runner):
    async def scenario():
        node = WaitingNode()
        with pytest.raises(TimeoutError):
            await runner("hello", component=node, timeout_seconds=0.5)
        assert node.started.is_set(), "deadline must exercise the running SDK node"
        await asyncio.wait_for(node.cancelled.wait(), timeout=2)
        assert await runner("hello") == {"response": "R=HELLO|tagged"}

    asyncio.run(scenario())


def test_cli_evidence_hash_and_no_overwrite(tmp_path):
    output = tmp_path / "evidence.json"
    command = [sys.executable, "-m", "smoke.workflow", "--output", str(output)]
    first = subprocess.run(
        command, capture_output=True, text=True, timeout=60, check=False
    )
    assert first.returncode == 0, first.stderr
    evidence = json.loads(output.read_text())
    assert evidence["run_mode"] == "live"
    assert evidence["synthetic"] is True
    assert evidence["versions"]["openjiuwen"] == "0.1.18"
    assert evidence["llm"]["status"] == "NOT_RUN"
    assert evidence["outputs"] == {
        "workflow": {"response": "R=HELLO|tagged"},
        "workflow_agent": {"response": "R=HELLO|tagged"},
    }
    canonical = json.dumps(
        evidence["outputs"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert evidence["output_sha256"] == hashlib.sha256(canonical).hexdigest()
    for source in evidence["sdk_sources"].values():
        assert "site-packages/openjiuwen/" in source["path"]
        assert (
            hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()
            == source["sha256"]
        )
    original = output.read_bytes()
    second = subprocess.run(
        command, capture_output=True, text=True, timeout=60, check=False
    )
    assert second.returncode != 0
    assert output.read_bytes() == original


@pytest.mark.parametrize("runner", [run_workflow, run_agent])
@pytest.mark.parametrize(
    "timeout", [0, -1, True, None, "10", float("inf"), float("nan")]
)
def test_invalid_timeout_is_not_defaulted(runner, timeout):
    with pytest.raises(ValueError, match="finite positive number"):
        asyncio.run(runner("hello", timeout_seconds=timeout))


@pytest.mark.parametrize("result", [None, {}, {"text": None}, {"response": "wrong"}])
def test_completed_status_cannot_hide_missing_or_wrong_output(result):
    from openjiuwen.core.workflow import WorkflowExecutionState, WorkflowOutput

    output = WorkflowOutput(state=WorkflowExecutionState.COMPLETED, result=result)
    with pytest.raises(RuntimeError, match="does not match"):
        checked_output(output, "hello")


def test_error_state_cannot_be_reported_as_success():
    from openjiuwen.core.workflow import WorkflowExecutionState, WorkflowOutput

    output = WorkflowOutput(
        state=WorkflowExecutionState.ERROR, result={"response": "R=HELLO|tagged"}
    )
    with pytest.raises(RuntimeError, match="did not complete"):
        checked_output(output, "hello")
