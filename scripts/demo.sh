#!/usr/bin/env bash
# 演示启动（docs/11-runbook.md）：fixture 与 live 使用不同 runtime/数据库目录。
# - fixture：合成演示实例（zhijue.api.demo_fixture），子进程显式剥离模型/嵌入
#   env 配置，绝不触发真实模型调用。
# - live：只接受显式导出的私密 env 文件路径；启动后不自动发送任何测试请求。
# shell 持有生命周期；退出只清理自己创建的前后端进程组。
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
require_cmd setsid

# 必须在子进程切换目录之前，按调用者 cwd 解析路径；不读取密钥内容。
absolute_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
}

STARTUP_TIMEOUT="${ZHIJUE_DEMO_STARTUP_TIMEOUT:-30}"
if [[ ! "$STARTUP_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
  echo "ZHIJUE_DEMO_STARTUP_TIMEOUT 必须是正整数秒。" >&2
  exit 2
fi

port_free() {
  python3 - "$1" <<'PY'
import socket, sys
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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

RUNTIME_DIR="$(absolute_path "${ZHIJUE_RUNTIME_DIR:-$ROOT/runtime/demo-$MODE}")"
mkdir -p "$RUNTIME_DIR"
export ZHIJUE_RUNTIME_DIR="$RUNTIME_DIR"
export ZHIJUE_DATABASE_URL="sqlite:///$RUNTIME_DIR/business.db"
# demo 的业务库与索引始终同属选定 runtime，覆盖宿主遗留的库/索引配置。
export ZHIJUE_MILVUS_URI="$RUNTIME_DIR/knowledge.db"
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
  export ZHIJUE_MODEL_ENV_FILE="$(absolute_path "$ZHIJUE_MODEL_ENV_FILE")"
  export ZHIJUE_EMBEDDING_ENV_FILE="$(absolute_path "$ZHIJUE_EMBEDDING_ENV_FILE")"
  if [[ ! -f "$ZHIJUE_MODEL_ENV_FILE" || ! -r "$ZHIJUE_MODEL_ENV_FILE" ||
        ! -f "$ZHIJUE_EMBEDDING_ENV_FILE" || ! -r "$ZHIJUE_EMBEDDING_ENV_FILE" ]]; then
    echo "live 模式的私密 env 文件必须存在且可读（路径按调用者 cwd 解析）。" >&2
    exit 1
  fi
  export ZHIJUE_RUN_MODE=live
  API_MODULE="zhijue"
  echo "live 模式：只启动服务，不自动发送任何模型测试请求。"
fi

API_PID=""
WEB_PID=""
cleanup() {
  trap '' INT TERM
  local pid pending deadline=$((SECONDS + 5))
  for pid in "$WEB_PID" "$API_PID"; do
    if [[ -n "$pid" ]]; then
      # 信号也可能在 setsid 尚未建立进程组时到达。
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  while (( SECONDS < deadline )); do
    pending=0
    for pid in "$WEB_PID" "$API_PID"; do
      if [[ -n "$pid" ]] && kill -0 -- "-$pid" 2>/dev/null; then
        pending=1
      fi
    done
    (( pending )) || break
    sleep 0.1
  done
  for pid in "$WEB_PID" "$API_PID"; do
    if [[ -n "$pid" ]]; then
      kill -KILL -- "-$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# setsid 隔离进程组，避免 Ctrl-C/清理误伤调用者与既有用户进程。
# exec 只在子 shell 中使用，launcher 自身必须保留 EXIT trap。
(cd "$ROOT/services/api" && exec setsid env PYTHONPATH=src .venv/bin/python -m "$API_MODULE") &
API_PID=$!

healthy=0
deadline=$((SECONDS + STARTUP_TIMEOUT))
while (( SECONDS < deadline )); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "后端启动失败（见上方日志）。" >&2
    exit 1
  fi
  if curl --connect-timeout 1 --max-time 1 -fsS \
      "http://127.0.0.1:$API_PORT/api/v1/health/live" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 0.2
done
if (( ! healthy )); then
  echo "后端健康检查超时（${STARTUP_TIMEOUT}s）；停止本次启动的进程。" >&2
  exit 1
fi

echo "后端存活: http://127.0.0.1:$API_PORT （$MODE 模式，runtime=$RUNTIME_DIR；业务 readiness 请查看 /api/v1/health/ready）"
export VITE_PROXY_TARGET="http://127.0.0.1:$API_PORT"
(cd "$ROOT/apps/web" && exec setsid node node_modules/vite/bin/vite.js --port "$WEB_PORT" --strictPort) &
WEB_PID=$!

# 任一服务退出（包括正常退出）都结束这一组服务，让端口可直接重启。
status=0
wait -n "$API_PID" "$WEB_PID" || status=$?
exit "$status"
