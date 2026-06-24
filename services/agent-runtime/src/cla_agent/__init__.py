"""轻量 Agent Harness 边界。

P0/P1 切片默认关闭 Agent Runtime。后续适配器只能调用确定性、
有作用域限制的能力；这里不提供 Docker、Kubernetes、宿主 Shell、
任意 SQL 或任意 HTTP 凭据。
"""

ALLOWED_TOOLS = {
    "content.search",
    "schema.validate",
    "rubric.draft",
    "hint.generate",
    "answer.evaluate",
}

FORBIDDEN_TOOLS = {
    "docker.run",
    "docker.exec",
    "kubernetes.apply",
    "kubernetes.exec",
    "host.shell",
    "sql.raw",
    "http.any",
    "cloud.admin",
}


def assert_tool_allowed(tool_name: str) -> None:
    if tool_name in FORBIDDEN_TOOLS or tool_name not in ALLOWED_TOOLS:
        raise PermissionError(f"Agent 工具未被允许：{tool_name}")
