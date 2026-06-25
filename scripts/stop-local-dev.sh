#!/usr/bin/env bash
set -euo pipefail

TMUX_SOCKET="${CLA_TMUX_SOCKET:-default}"
SESSION="${CLA_TMUX_SESSION:-cla}"

tmux_cmd() {
  if [[ "$TMUX_SOCKET" == "default" ]]; then
    tmux "$@"
  else
    tmux -L "$TMUX_SOCKET" "$@"
  fi
}

tmux_cmd kill-session -t "$SESSION" 2>/dev/null || true
echo "CLA 本地 tmux 服务已停止：$SESSION"
