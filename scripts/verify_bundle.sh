#!/usr/bin/env bash
# 在干净目录复验发行包：完整性 → 锁定安装 → 离线回归 → fixture HTTP 纵切面。
# 不读取原工作区 runtime/env；不调用真实模型或 embedding。
set -euo pipefail

BUNDLE="${1:?用法: scripts/verify_bundle.sh <bundle.zip>}"
command -v python3 >/dev/null 2>&1 || { echo "缺少 python3" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "缺少 git" >&2; exit 1; }
for command in uv node pnpm make curl setsid; do
  command -v "$command" >/dev/null 2>&1 || { echo "缺少 $command" >&2; exit 1; }
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/zhijue-verify-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

python3 - "$BUNDLE" "$WORK" <<'PY'
import hashlib, json, sys, zipfile
from pathlib import Path

bundle, work = Path(sys.argv[1]), Path(sys.argv[2])
archive = zipfile.ZipFile(bundle)
for name in archive.namelist():
    target = Path(name)
    # 解压只接受本发行物的根目录与普通相对路径。
    if target.is_absolute() or ".." in target.parts or target.parts[0] != "zhijue_face":
        raise SystemExit(f"包内路径不安全: {name}")
    archive.extract(name, work)
manifest = json.loads(
    (work / "zhijue_face" / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8")
)
bad = []
for entry in manifest["files"]:
    path = work / "zhijue_face" / entry["path"]
    if not path.is_file():
        bad.append(entry["path"] + " (missing)")
        continue
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        bad.append(entry["path"])
if bad:
    print(f"逐文件校验失败 {len(bad)} 项: {bad[:5]}", file=sys.stderr)
    raise SystemExit(1)
print(f"manifest ok: {manifest['file_count']} files")
PY

cd "$WORK/zhijue_face"
for private in .git .env.local .env.embedding.local runtime services/api/.venv apps/web/node_modules; do
  [[ ! -e "$private" ]] || { echo "发行包夹带非源码资产: $private" >&2; exit 1; }
done
# doctor 依赖 git 清单口径（ls-files / check-ignore）：解包目录先建临时索引，
# 模拟“干净检出”，不改动包内容本身。
git init -q
git add -A
python3 scripts/doctor.py --profile bundle
make setup
make check
(cd apps/web && pnpm test && pnpm build)

services/api/.venv/bin/python - <<'PY'
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx


def free_ports():
    sockets = [socket.socket(), socket.socket()]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def await_operation(client, accepted):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        operation = client.get("/operations/" + accepted["operation_id"])
        operation.raise_for_status()
        view = operation.json()["data"]
        if view["status"] == "succeeded":
            return
        if view["status"] not in {"queued", "running"}:
            raise RuntimeError(f"fixture operation failed: {view['error']}")
        time.sleep(0.1)
    raise RuntimeError("fixture operation timed out")


api_port, web_port = free_ports()
runtime = Path("runtime/bundle-verification").resolve()
runtime.mkdir(parents=True)
environment = {
    **os.environ,
    "ZHIJUE_RUNTIME_DIR": str(runtime),
    "ZHIJUE_DEMO_API_PORT": str(api_port),
    "ZHIJUE_DEMO_WEB_PORT": str(web_port),
}
with (runtime / "launcher.log").open("w") as log:
    launcher = subprocess.Popen(
        ["bash", "scripts/demo.sh", "fixture"],
        env=environment, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{web_port}/api/v1",
            timeout=5, trust_env=False,
        ) as client:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if launcher.poll() is not None:
                    raise RuntimeError("fixture launcher exited; see launcher.log")
                try:
                    ready = client.get("/health/ready")
                    if ready.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("fixture readiness timed out")
            details = ready.json()["data"]
            assert details["run_mode"] == "fixture"
            assert details["data_mode"] == "synthetic"
            assert details["content_generation"] == "absent"
            page = client.get(f"http://127.0.0.1:{web_port}/start")
            page.raise_for_status()
            assert 'id="root"' in page.text

            def get(path):
                response = client.get(path)
                response.raise_for_status()
                return response.json()["data"]

            def post(path, body):
                response = client.post(
                    path, json=body,
                    headers={"Idempotency-Key": "bundle-" + uuid4().hex},
                )
                response.raise_for_status()
                return response.json()["data"]

            packs = get("/knowledge-packs")
            release = next(p for p in packs["items"] if p["selectable"])
            profile = post("/profiles", {"display_name": "发行验证合成资料", "synthetic": True})
            path = "/profiles/" + profile["id"]
            post(path + "/facts", {
                "expected_revision": profile["revision"],
                "items": [{
                    "section": "project",
                    "text": "合成资料：在 STM32 课程项目中使用 UART、FreeRTOS，并记录串口日志定位缓冲区边界问题。",
                }],
            })
            profile = get(path)
            accepted = post(path + "/confirm", {
                "expected_revision": profile["revision"],
                "decisions": [
                    {"claim_id": c["id"], "action": "accept"}
                    for c in profile["proposed_claims"]
                ],
            })
            await_operation(client, accepted)
            profile = get(path)
            assert profile["snapshot_activation"]["status"] == "ready"
            plan = post("/interviews", {
                "profile_id": profile["id"], "profile_revision": profile["revision"],
                "pack_release_id": release["pack_release_id"],
            })
            await_operation(client, plan)
            interview_path = "/interviews/" + plan["resource_id"]
            view = get(interview_path)
            assert view["knowledge_pack"]["content_digest"] == release["content_digest"]
            await_operation(client, post(
                interview_path + "/start", {"expected_revision": view["revision"]},
            ))
            for turn in range(5):
                view = get(interview_path)
                question = view["current_question"]
                assert "rubric_snapshot" not in question and "reference_points" not in question
                accepted = post(interview_path + "/answers", {
                    "expected_revision": view["revision"], "question_id": question["id"],
                    "client_turn_id": "bundle-" + str(turn),
                    "answer_text": "合成回答：我记录输入和日志，逐项检查错误标志与缓冲区边界，仅报告亲自观察到的结果。",
                })
                await_operation(client, accepted)
            report = get(interview_path + "/report")
            assert report["completion"] == "complete"
            assert report["coverage"]["answered_root_count"] == 5
            print(json.dumps({
                "fixture_http": "PASS", "run_mode": details["run_mode"],
                "frontend_proxy": "PASS", "pack_digest": release["content_digest"],
                "report_completion": report["completion"], "answered_roots": 5,
                "model_calls": 0, "embedding_calls": 0,
            }, ensure_ascii=False))
    finally:
        launcher.send_signal(signal.SIGTERM)
        launcher.wait(timeout=15)
PY
echo "verify-bundle PASS (安装、离线回归、前端构建、fixture HTTP): $BUNDLE"
