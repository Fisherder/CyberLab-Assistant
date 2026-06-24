package cla.agent.capabilities

default allow := false

allowed_tools := {
  "content.search",
  "schema.validate",
  "rubric.draft",
  "hint.generate",
  "answer.evaluate"
}

forbidden_tools := {
  "docker.run",
  "docker.exec",
  "kubernetes.apply",
  "kubernetes.exec",
  "host.shell",
  "sql.raw",
  "http.any",
  "cloud.admin"
}

allow if {
  input.tool in allowed_tools
  not input.tool in forbidden_tools
  input.tenant_id == input.scope.tenant_id
}

deny_reason := "forbidden infrastructure or unscoped tool" if {
  input.tool in forbidden_tools
}

