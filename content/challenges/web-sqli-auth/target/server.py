from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import json
import os


AUTH_BYPASS_OBSERVED = False
TARGET_SESSION_KEY = os.environ.get("TARGET_SESSION_KEY", "dev-session-key")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/login"}:
            self._html(login_page())
            return
        if parsed.path == "/healthz":
            self._json({"ok": True})
            return
        if parsed.path == "/oracle/state":
            key = parse_qs(parsed.query).get("key", [""])[0]
            self._json(
                {
                    "auth_bypass_observed": key == TARGET_SESSION_KEY and AUTH_BYPASS_OBSERVED,
                }
            )
            return
        self._json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        global AUTH_BYPASS_OBSERVED
        if self.path != "/login":
            self._json({"error": "not_found"}, status=404)
            return
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode()
        fields = parse_qs(body)
        username = fields.get("username", [""])[0]
        password = fields.get("password", [""])[0]
        query = f"SELECT id FROM users WHERE username = '{username}' AND password = '{password}'"
        if "' OR '1'='1" in query or '" OR "1"="1' in query:
            AUTH_BYPASS_OBSERVED = True
            self._json({"ok": True, "role": "admin"})
            return
        self._json({"ok": False}, status=401)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, value: dict, status: int = 200) -> None:
        encoded = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _html(self, value: str, status: int = 200) -> None:
        encoded = value.encode()
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def login_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CLA Web SQLi Auth 实验目标</title>
  <style>
    :root{color-scheme:light dark;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#f4f7fb;color:#172033}
    body{margin:0;min-height:100vh;display:grid;place-items:center;padding:32px}
    main{width:min(760px,100%);background:#fff;border:1px solid #d9e0ea;border-radius:12px;padding:28px;box-shadow:0 18px 45px rgba(23,32,51,.10)}
    h1{margin:0 0 10px;font-size:28px}
    p{color:#5f6b7c;line-height:1.7}
    form{display:grid;gap:12px;margin:22px 0}
    label{display:grid;gap:6px;font-weight:700}
    input{font:inherit;padding:11px 12px;border:1px solid #cbd5e1;border-radius:8px}
    button{font:inherit;border:0;border-radius:8px;padding:11px 14px;background:#2357d8;color:white;font-weight:800;cursor:pointer}
    code,pre{font-family:"SFMono-Regular",Consolas,monospace}
    pre{background:#0b1220;color:#e8eef9;padding:14px;border-radius:10px;overflow:auto}
    #result{min-height:34px;padding:10px 12px;border-radius:8px;background:#edf2f8}
  </style>
</head>
<body>
<main>
  <h1>Web 登录认证调试页</h1>
  <p>这是本题的目标网站入口。你可以先用浏览器测试普通登录，再回到 CLA 终端用 curl 构造请求、观察响应并解释认证逻辑的问题。</p>
  <form id="login-form">
    <label>用户名 <input name="username" autocomplete="username" value="alice" /></label>
    <label>密码 <input name="password" autocomplete="current-password" value="wrong" /></label>
    <button type="submit">发送登录请求</button>
  </form>
  <div id="result">等待请求。</div>
  <p>终端中可以从这些命令开始：</p>
  <pre>curl -i "$TARGET_BASE_URL/healthz"
curl -i -X POST "$TARGET_BASE_URL/login" -d "username=alice&password=wrong"</pre>
</main>
<script>
document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const body = new URLSearchParams(form);
  const response = await fetch("/login", {
    method: "POST",
    headers: {"content-type": "application/x-www-form-urlencoded"},
    body
  });
  const text = await response.text();
  document.getElementById("result").textContent = response.status + " " + text;
});
</script>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("TARGET_PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
