#!/usr/bin/env bash
set -euo pipefail

TMUX_SOCKET="${CLA_TMUX_SOCKET:-cla-dev}"
SESSION="${CLA_TMUX_SESSION:-cla}"

tmux -L "$TMUX_SOCKET" kill-session -t "$SESSION" 2>/dev/null || true
echo "CLA 本地 tmux 服务已停止：$SESSION"
