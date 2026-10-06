"""Exercise the real launcher with disposable stdlib HTTP child processes.

No project service, model, private env file, or existing runtime is used.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[3]
CHILD = r"""
import json
import os
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

role = ROLE
root = Path(os.environ["HARNESS_STATE"])
port = int(os.environ["ZHIJUE_API_PORT"] if role == "api" else sys.argv[-2])
if os.environ.get("FAIL_START") == role:
    sys.exit(19)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])

def stop(*_):
    child.terminate()
    child.wait(timeout=2)
    sys.exit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
(root / (role + ".json")).write_text(json.dumps({
    "pid": os.getpid(), "child": child.pid, "cwd": os.getcwd(),
    "env": {k: v for k, v in os.environ.items() if k.startswith("ZHIJUE_")},
}))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if os.environ.get("HANG_HEALTH") == "1":
            time.sleep(30)
        self.send_response(200)
        self.end_headers()
    def log_message(self, *_):
        pass

try:
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 0.1
    while not (root / (role + ".exit")).exists():
        server.handle_request()
    code = int((root / (role + ".exit")).read_text())
    server.server_close()
    child.terminate()
    child.wait(timeout=2)
    sys.exit(code)
finally:
    if child.poll() is None:
        child.terminate()
        child.wait(timeout=2)
"""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def eventually(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("child process condition did not become true")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(WORKSPACE / "scripts" / "demo.sh", scripts / "demo.sh")
    api = root / "services/api/.venv/bin"
    api.mkdir(parents=True)
    (root / "apps/web").mkdir(parents=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for path, role in ((api / "python", "api"), (binaries / "node", "web")):
        path.write_text(f"#!{sys.executable}\n" + CHILD.replace("ROLE", repr(role)))
        path.chmod(0o755)
    caller = tmp_path / "caller"
    caller.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("ZHIJUE_")}
    env.update(
        PATH=f"{binaries}:{os.environ['PATH']}",
        HARNESS_STATE=str(state),
        ZHIJUE_DEMO_API_PORT=str(free_port()),
        ZHIJUE_DEMO_WEB_PORT=str(free_port()),
        ZHIJUE_DEMO_STARTUP_TIMEOUT="3",
        ZHIJUE_RUNTIME_DIR="isolated runtime",
    )
    while env["ZHIJUE_DEMO_API_PORT"] == env["ZHIJUE_DEMO_WEB_PORT"]:
        env["ZHIJUE_DEMO_WEB_PORT"] = str(free_port())
    processes = []

    def start(mode="fixture", **overrides):
        process = subprocess.Popen(
            ["bash", str(scripts / "demo.sh"), mode],
            cwd=caller,
            env={**env, **overrides},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        processes.append(process)
        return process

    yield start, state, caller, env
    for process in processes:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=12)
    # Only harness-owned children; ensure failed assertions cannot leak processes.
    for record in state.glob("*.json"):
        data = json.loads(record.read_text())
        for pid in (data["pid"], data["child"]):
            if alive(pid):
                os.kill(pid, signal.SIGKILL)


def child_record(state, role):
    path = state / f"{role}.json"
    eventually(path.exists)
    eventually(lambda: bool(path.read_text()))
    return json.loads(path.read_text())


def assert_stopped(records, env):
    for record in records:
        eventually(lambda record=record: not alive(record["pid"]))
        eventually(lambda record=record: not alive(record["child"]))
    for key in ("ZHIJUE_DEMO_API_PORT", "ZHIJUE_DEMO_WEB_PORT"):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", int(env[key])))


@pytest.mark.parametrize("sig,code", [(signal.SIGTERM, 143), (signal.SIGINT, 130)])
def test_signal_reaps_both_process_trees_and_allows_restart(launcher, sig, code):
    start, state, _, env = launcher
    for _ in range(2):
        for record in state.glob("*.json"):
            record.unlink()
        process = start()
        records = [child_record(state, role) for role in ("api", "web")]
        process.send_signal(sig)
        output, _ = process.communicate(timeout=12)
        assert process.returncode == code, output
        assert_stopped(records, env)


@pytest.mark.parametrize("role,code", [("web", 19), ("web", 0), ("api", 17)])
def test_child_exit_stops_other_service(launcher, role, code):
    start, state, _, env = launcher
    process = start()
    records = [child_record(state, name) for name in ("api", "web")]
    (state / f"{role}.exit").write_text(str(code))
    output, _ = process.communicate(timeout=12)
    assert process.returncode == code, output
    assert_stopped(records, env)


@pytest.mark.parametrize("role", ["api", "web"])
def test_start_failure_cleans_up_without_false_ready(launcher, role):
    start, state, _, env = launcher
    process = start(FAIL_START=role)
    output, _ = process.communicate(timeout=12)
    assert process.returncode != 0
    if role == "api":
        assert "后端存活" not in output
        assert not (state / "web.json").exists()
    else:
        assert_stopped([child_record(state, "api")], env)


def test_hanging_health_request_times_out_and_cleans_up(launcher):
    start, state, _, env = launcher
    process = start(HANG_HEALTH="1", ZHIJUE_DEMO_STARTUP_TIMEOUT="1")
    output, _ = process.communicate(timeout=10)
    assert process.returncode != 0
    assert "健康检查超时" in output
    assert "后端存活" not in output
    assert not (state / "web.json").exists()
    assert_stopped([child_record(state, "api")], env)


def test_live_paths_resolve_from_caller_and_storage_is_isolated(launcher):
    start, state, caller, _ = launcher
    (caller / "model.env").touch()
    (caller / "embedding.env").touch()
    process = start(
        "live",
        ZHIJUE_MODEL_ENV_FILE="model.env",
        ZHIJUE_EMBEDDING_ENV_FILE="embedding.env",
        ZHIJUE_DATABASE_URL="sqlite:////do-not-touch/business.db",
        ZHIJUE_MILVUS_URI="/do-not-touch/knowledge.db",
    )
    record = child_record(state, "api")
    child_record(state, "web")
    runtime = caller / "isolated runtime"
    child_env = record["env"]
    assert child_env["ZHIJUE_MODEL_ENV_FILE"] == str(caller / "model.env")
    assert child_env["ZHIJUE_EMBEDDING_ENV_FILE"] == str(caller / "embedding.env")
    assert child_env["ZHIJUE_RUNTIME_DIR"] == str(runtime)
    assert child_env["ZHIJUE_DATABASE_URL"] == f"sqlite:///{runtime}/business.db"
    assert child_env["ZHIJUE_MILVUS_URI"] == str(runtime / "knowledge.db")
    process.terminate()
    process.communicate(timeout=12)


def test_fixture_strips_private_env_paths(launcher):
    start, state, _, _ = launcher
    process = start(
        ZHIJUE_MODEL_ENV_FILE="nonexistent-private-model.env",
        ZHIJUE_EMBEDDING_ENV_FILE="nonexistent-private-embedding.env",
    )
    env = child_record(state, "api")["env"]
    assert "ZHIJUE_MODEL_ENV_FILE" not in env
    assert "ZHIJUE_EMBEDDING_ENV_FILE" not in env
    assert env["ZHIJUE_RUN_MODE"] == "fixture"
    assert env["ZHIJUE_DATA_MODE"] == "synthetic"
    process.terminate()
    process.communicate(timeout=12)


def test_occupied_port_does_not_kill_existing_owner(launcher):
    start, state, _, _ = launcher
    with socket.socket() as owner:
        owner.bind(("127.0.0.1", 0))
        owner.listen()
        port = owner.getsockname()[1]
        process = start(ZHIJUE_DEMO_API_PORT=str(port))
        output, _ = process.communicate(timeout=8)
        assert process.returncode != 0
        assert "已被占用" in output
        assert owner.getsockname()[1] == port
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
        assert not list(state.glob("*.json"))


def test_missing_live_env_fails_before_children_start(launcher):
    start, state, _, _ = launcher
    process = start(
        "live", ZHIJUE_MODEL_ENV_FILE="absent", ZHIJUE_EMBEDDING_ENV_FILE="absent"
    )
    output, _ = process.communicate(timeout=8)
    assert process.returncode != 0
    assert "必须存在且可读" in output
    assert not list(state.glob("*.json"))
