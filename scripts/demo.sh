#!/usr/bin/env bash
# 演示启动（docs/11-runbook.md）：fixture 与 live 使用不同 runtime/数据库目录。
# - fixture：合成演示实例（zhijue.api.demo_fixture），子进程显式剥离模型/嵌入
#   env 配置，绝不触发真实模型调用。
# - live：只接受显式导出的私密 env 文件路径；启动后不自动发送任何测试请求。
# 端口占用时友好失败；退出只清理本脚本自己拉起的后端子进程。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-}"
if [[ "$MODE" != "fixture" && "$MODE" != "live" ]]; then
  echo "用法: scripts/demo.sh fixture|live" >&2
  exit 2
fi

API_PORT="${ZHIJUE_DEMO_API_PORT:-8000}"
WEB_PORT="${ZHIJUE_DEMO_WEB_PORT:-5199}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "缺少命令：$1（请先安装或使用 make setup）" >&2; exit 1; }
}
require_cmd python3
require_cmd node
require_cmd curl

port_free() {
  python3 - "$1" <<'PY'
import socket, sys
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}
for port in "$API_PORT" "$WEB_PORT"; do
  if ! port_free "$port"; then
    echo "端口 $port 已被占用；本脚本不会杀已有进程。可用 ZHIJUE_DEMO_API_PORT/ZHIJUE_DEMO_WEB_PORT 选择其它端口。" >&2
    exit 1
  fi
done

RUNTIME_DIR="$ROOT/runtime/demo-$MODE"
mkdir -p "$RUNTIME_DIR"
export ZHIJUE_RUNTIME_DIR="$RUNTIME_DIR"
export ZHIJUE_DATABASE_URL="sqlite:///$RUNTIME_DIR/business.db"
export ZHIJUE_API_HOST=127.0.0.1
export ZHIJUE_API_PORT="$API_PORT"

if [[ "$MODE" == "fixture" ]]; then
  # 关键隔离：fixture 子进程不继承可能触发真实调用的模型配置。
  unset ZHIJUE_MODEL_ENV_FILE ZHIJUE_EMBEDDING_ENV_FILE || true
  export ZHIJUE_RUN_MODE=fixture
  export ZHIJUE_DATA_MODE=synthetic
  API_MODULE="zhijue.api.demo_fixture"
else
  if [[ -z "${ZHIJUE_MODEL_ENV_FILE:-}" || -z "${ZHIJUE_EMBEDDING_ENV_FILE:-}" ]]; then
    echo "live 模式需要显式导出 ZHIJUE_MODEL_ENV_FILE 与 ZHIJUE_EMBEDDING_ENV_FILE（私密文件路径，本脚本不打印其内容）。" >&2
    exit 1
  fi
  export ZHIJUE_RUN_MODE=live
  API_MODULE="zhijue"
  echo "live 模式：只启动服务，不自动发送任何模型测试请求。"
fi

API_PID=""
cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

(cd "$ROOT/services/api" && PYTHONPATH=src .venv/bin/python -m "$API_MODULE") &
API_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/v1/health/live" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "后端启动失败（见上方日志）。" >&2
    exit 1
  fi
  sleep 0.5
done

echo "后端就绪: http://127.0.0.1:$API_PORT （$MODE 模式，runtime=$RUNTIME_DIR）"
cd "$ROOT/apps/web"
export VITE_PROXY_TARGET="http://127.0.0.1:$API_PORT"
exec node node_modules/vite/bin/vite.js --port "$WEB_PORT" --strictPort
