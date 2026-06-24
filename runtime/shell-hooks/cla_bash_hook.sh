# 尽力采集语义命令事件；Shell 输出和命令只能作为弱证据。
__cla_last_command_started_at=0

__cla_preexec() {
  __cla_last_command_started_at=$(date +%s%3N)
  export __CLA_COMMAND_TEXT="$BASH_COMMAND"
}

__cla_precmd() {
  local exit_code=$?
  local ended_at
  ended_at=$(date +%s%3N)
  local duration=$((ended_at - __cla_last_command_started_at))
  if [ -n "${CLA_HOOK_ENDPOINT:-}" ] && [ -n "${__CLA_COMMAND_TEXT:-}" ]; then
    python3 - <<'PY'
import hashlib, json, os, time, urllib.request
cmd = os.environ.get("__CLA_COMMAND_TEXT", "")
payload = {
    "type": "terminal.command.completed",
    "source": {"service": "cla-shell-hook", "version": "0.1.0"},
    "payload": {
        "command_redacted": "[redacted]",
        "command_fingerprint": "sha256:" + hashlib.sha256(cmd.encode()).hexdigest(),
        "cwd": os.getcwd(),
        "exit_code": int(os.environ.get("CLA_LAST_EXIT", "0")),
        "duration_ms": int(os.environ.get("CLA_LAST_DURATION", "0")),
    },
    "occurred_at": int(time.time())
}
req = urllib.request.Request(os.environ["CLA_HOOK_ENDPOINT"], data=json.dumps(payload).encode(), method="POST")
req.add_header("Content-Type", "application/json")
try:
    urllib.request.urlopen(req, timeout=0.3).read()
except Exception:
    pass
PY
  fi
  export CLA_LAST_EXIT="$exit_code"
  export CLA_LAST_DURATION="$duration"
}

trap '__cla_preexec' DEBUG
PROMPT_COMMAND="__cla_precmd${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
