#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
TMUX_SOCKET="${CLA_TMUX_SOCKET:-default}"
SESSION="${CLA_TMUX_SESSION:-cla}"
WORKSPACE_ROOT="${CLA_LOCAL_WORKSPACE_DIR:-/private/tmp/cla-local-workspace/web-sqli-auth}"
TEMPLATE_DIR="$ROOT/runtime/sessiond/workspace-template/web-sqli-auth"
PYTHON_BIN="${CLA_PYTHON_BIN:-$ROOT/.venv/bin/python}"
GO_BIN="${CLA_GO_BIN:-/tmp/cla-go/go/bin/go}"
PNPM_BIN="${CLA_PNPM_BIN:-/Users/fisherder/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "找不到 Python：$PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -x "$GO_BIN" ]]; then
  if command -v go >/dev/null 2>&1; then
    GO_BIN="$(command -v go)"
  else
    echo "找不到 Go：$GO_BIN，也没有可用的 go 命令" >&2
    exit 1
  fi
fi

if [[ ! -x "$PNPM_BIN" ]]; then
  echo "找不到 pnpm：$PNPM_BIN" >&2
  exit 1
fi

if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo "找不到工作区模板：$TEMPLATE_DIR" >&2
  exit 1
fi

tmux_cmd() {
  if [[ "$TMUX_SOCKET" == "default" ]]; then
    tmux "$@"
  else
    tmux -L "$TMUX_SOCKET" "$@"
  fi
}

rm -rf "$WORKSPACE_ROOT"
mkdir -p "$WORKSPACE_ROOT"
cp -R "$TEMPLATE_DIR/." "$WORKSPACE_ROOT/"

rm -rf "$ROOT/apps/web/.next"

tmux_cmd kill-session -t "$SESSION" 2>/dev/null || true

tmux_cmd new-session -d -s "$SESSION" -n target -c "$ROOT" \
  "env TARGET_PORT=18080 TARGET_SESSION_KEY=dev-session-key '$PYTHON_BIN' content/challenges/web-sqli-auth/target/server.py"

tmux_cmd new-window -t "$SESSION" -n sessiond -c "$ROOT/runtime/sessiond" \
  "env CLA_SESSIOND_ADDR=127.0.0.1:7777 CLA_WORKSPACE_SHELL=/bin/bash CLA_WORKSPACE_DIR='$WORKSPACE_ROOT' TARGET_BASE_URL=http://127.0.0.1:18080 '$GO_BIN' run ./cmd/sessiond"

tmux_cmd new-window -t "$SESSION" -n api -c "$ROOT" \
  "env PYTHONPATH=services/api/src CLA_DATABASE_URL=sqlite:///./cla-dev.db CLA_DEV_MODE=true CLA_LOCAL_AUTH_ENABLED=true CLA_INTERNAL_SERVICE_TOKEN=change-me-internal CLA_GATEWAY_URL=ws://127.0.0.1:8081/ws/terminal CLA_SESSIOND_ENDPOINT=127.0.0.1:7777 CLA_REMOTE_DESKTOP_ENABLED=false CLA_SIMULATED_WORKSPACE_ENABLED=false .venv/bin/uvicorn cla.main:app --host 127.0.0.1 --port 8000 --app-dir services/api/src"

tmux_cmd new-window -t "$SESSION" -n gateway -c "$ROOT/services/terminal-gateway" \
  "env CLA_API_URL=http://127.0.0.1:8000 CLA_INTERNAL_SERVICE_TOKEN=change-me-internal CLA_GATEWAY_ADDR=127.0.0.1:8081 '$GO_BIN' run ./cmd/gateway"

tmux_cmd new-window -t "$SESSION" -n web -c "$ROOT" \
  "env NEXT_PUBLIC_CLA_API_BASE= CLA_API_INTERNAL_BASE=http://127.0.0.1:8000 PORT=3000 HOSTNAME=127.0.0.1 '$PNPM_BIN' --dir apps/web dev"

cat <<EOF
CLA 本地服务已在 tmux 中启动。

访问地址：
  Web:      http://127.0.0.1:3000
  登录页:   http://127.0.0.1:3000/login
  API:      http://127.0.0.1:8000
  Gateway:  http://127.0.0.1:8081/healthz
  Target:   http://127.0.0.1:18080/healthz

学生终端工作区：
  $WORKSPACE_ROOT

进入 tmux：
  tmux attach -t $SESSION
  或：tmux a -t $SESSION
EOF
