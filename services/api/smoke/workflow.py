"""M0-02: real openJiuwen execution on synthetic text, without an LLM."""

import argparse
import asyncio
import hashlib
import inspect
import json
import math
import platform
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from openjiuwen.core.application.workflow_agent import (
    WorkflowAgent,
    WorkflowAgentConfig,
)
from openjiuwen.core.common.task_manager import get_task_manager
from openjiuwen.core.session.workflow import create_workflow_session
from openjiuwen.core.workflow import (
    End,
    EndConfig,
    Start,
    Workflow,
    WorkflowCard,
    WorkflowComponent,
    WorkflowExecutionState,
    WorkflowOutput,
)


class TransformText(WorkflowComponent):
    """A deterministic smoke node, not a model or a domain evaluator."""

    async def invoke(self, inputs, session, context):
        return {"text": inputs["text"].upper() + "|tagged"}


def validate_input(text: str, timeout_seconds: float) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be a finite positive number")


def build_workflow(component: WorkflowComponent | None = None) -> Workflow:
    card = WorkflowCard(
        id=f"m0_smoke_{uuid4().hex}",
        name="synthetic_text_smoke",
        version="1.0.0",
        input_params={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    workflow = Workflow(card=card)
    workflow.set_start_comp("start", Start(), inputs_schema={"text": "${text}"})
    workflow.add_workflow_comp(
        "transform",
        TransformText() if component is None else component,
        inputs_schema={"text": "${start.text}"},
    )
    # End returns `response`; remapping a nonexistent `text` would hide a broken result.
    workflow.set_end_comp(
        "end",
        End(EndConfig(response_template="R={{text}}")),
        inputs_schema={"text": "${transform.text}"},
    )
    workflow.add_connection("start", "transform")
    workflow.add_connection("transform", "end")
    return workflow


def checked_output(output: WorkflowOutput, text: str) -> dict:
    if not isinstance(output, WorkflowOutput):
        raise TypeError("SDK did not return WorkflowOutput")
    if output.state != WorkflowExecutionState.COMPLETED:
        raise RuntimeError(f"SDK workflow did not complete: {output.state}")
    expected = {"response": f"R={text.upper()}|tagged"}
    if output.result != expected:
        raise RuntimeError("SDK workflow output does not match the smoke contract")
    return output.result


async def invoke_bounded(invocation, timeout_seconds: float):
    # Agent streaming starts SDK background tasks. Own their scope so timeout cannot
    # leave a node running after the probe has already reported failure.
    error = None
    async with get_task_manager().task_group() as group:
        try:
            return await asyncio.wait_for(invocation, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - original error re-raised after cleanup
            # Re-raise the original SDK failure after structured cleanup, not a
            # misleading success or an unrelated task-group wrapper exception.
            error = exc
        finally:
            group.cancel_scope.cancel()
    raise error


async def run_workflow(
    text: str,
    *,
    component: WorkflowComponent | None = None,
    timeout_seconds: float = 10,
) -> dict:
    validate_input(text, timeout_seconds)
    workflow = build_workflow(component)
    session = create_workflow_session(session_id=uuid4().hex)
    output = await invoke_bounded(
        workflow.invoke({"text": text}, session), timeout_seconds
    )
    return checked_output(output, text)


async def run_agent(
    text: str,
    *,
    component: WorkflowComponent | None = None,
    timeout_seconds: float = 10,
) -> dict:
    validate_input(text, timeout_seconds)
    workflow = build_workflow(component)
    agent = WorkflowAgent(
        WorkflowAgentConfig(
            id=f"m0_agent_{uuid4().hex}",
            version="1.0.0",
            description="Synthetic SDK smoke",
        )
    )
    # Only one workflow: the official controller bypasses LLM intent detection.
    agent.add_workflows([workflow])
    output = await invoke_bounded(
        agent.invoke({"query": text, "conversation_id": uuid4().hex}),
        timeout_seconds,
    )
    if not isinstance(output, dict) or output.get("result_type") != "answer":
        raise RuntimeError("SDK agent did not return an answer")
    return checked_output(output.get("output"), text)


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sdk_sources() -> dict:
    sources = {}
    bases = tuple(
        base
        for base in WorkflowAgent.__mro__
        if base.__module__.startswith("openjiuwen.")
    )
    entries = (Workflow, *bases, WorkflowAgentConfig, Start, End)
    for entry in entries:
        source = Path(inspect.getfile(entry)).resolve()
        sources[entry.__name__] = {
            "module": entry.__module__,
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    return sources


async def collect_evidence() -> dict:
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    text = "hello"
    outputs = {
        "workflow": await run_workflow(text),
        "workflow_agent": await run_agent(text),
    }
    return {
        "task_id": "M0-02",
        "smoke_version": "1.0.0",
        "status": "passed",
        "run_mode": "live",
        "execution_scope": "local_framework_only",
        "synthetic": True,
        "input": {"text": text},
        "outputs": outputs,
        "output_sha256": canonical_hash(outputs),
        "sdk_sources": sdk_sources(),
        "agent_mro": [
            f"{entry.__module__}.{entry.__name__}" for entry in WorkflowAgent.__mro__
        ],
        "versions": {
            "python": platform.python_version(),
            "openjiuwen": version("openjiuwen"),
        },
        "platform": platform.platform(),
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "llm": {
            "status": "NOT_RUN",
            "provider": None,
            "model": None,
            "calls": 0,
            "tokens": None,
            "cost": None,
            "prompt_version": None,
            "seed_version": None,
            "rubric_version": None,
        },
        "knowledge_status": "NOT_RUN",
        "mocked_sdk": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New JSON evidence path; existing evidence is never overwritten",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new evidence path")
    evidence = asyncio.run(collect_evidence())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(evidence, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(f"M0-02 passed; output_sha256={evidence['output_sha256']}")


if __name__ == "__main__":
    main()
