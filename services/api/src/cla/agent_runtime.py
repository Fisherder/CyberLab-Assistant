from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
import urllib.error
import urllib.request

from cla.settings import Settings


BRIEF_PARSER_PROMPT_VERSION = "cla-brief-parser/0.2.0"
VERSION_DRAFTER_PROMPT_VERSION = "cla-version-drafter/0.2.0"
SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)(\S+)"),
]


class AgentRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentModelResult:
    output: dict[str, Any]
    usage: dict[str, Any]


def parse_course_intent_with_model(
    settings: Settings,
    *,
    brief: str,
    constraints: dict[str, Any],
) -> AgentModelResult:
    _require_model_settings(settings)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 CyberLab Assistant 的出题 Brief 解析器。"
                "只输出 JSON 对象，不输出解释文字。"
                "不得生成最终 payload、动态秘密、教师解法或任何可直接越权的命令。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "把教师自然语言需求解析为 CourseIntent。",
                    "requiredSchema": {
                        "category": "WEB|PWN|CRYPTO|REVERSE|FORENSICS|UNKNOWN",
                        "target": "短大写标识",
                        "difficulty": "1 到 5 的整数",
                        "expectedMinutes": "正整数",
                        "workspaceType": "TERMINAL|REMOTE_DESKTOP|SIMULATED",
                        "isolationTier": "1 到 5 的整数",
                        "allowedTools": ["工具名称"],
                        "learningObjectives": ["学习目标标识"],
                        "uncertainFields": ["低置信字段"],
                        "confidence": "0 到 1 的数字",
                    },
                    "hardRules": [
                        "一期默认 workspaceType 为 TERMINAL。",
                        "REMOTE_DESKTOP 和 SIMULATED 只能在教师明确要求时出现。",
                        "allowedTools 只能列终端工具，例如 curl、python、gdb、objdump、readelf、strings、pwntools；不要列浏览器、IDA Pro、Ghidra、Burp Suite 等 GUI 或未启用工具。",
                        "不确定字段必须写入 uncertainFields，不能假装高置信。",
                    ],
                    "brief": _redact_sensitive_text(brief),
                    "constraints": _redact_sensitive_values(constraints),
                },
                ensure_ascii=False,
            ),
        },
    ]
    return _chat_completion_json(settings, messages, prompt_version=BRIEF_PARSER_PROMPT_VERSION)


def draft_challenge_version_with_model(
    settings: Settings,
    *,
    brief: str,
    intent: dict[str, Any],
    candidate_manifest: dict[str, Any],
    candidate_rubric: dict[str, Any],
) -> AgentModelResult:
    _require_model_settings(settings)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 CyberLab Assistant 的题目版本草稿助手。"
                "你只能基于已通过验证的候选题包提出 manifest 说明、rubric 草稿和教学备注。"
                "你不能发布题目，不能要求执行 Shell/Docker/Kubernetes/SQL/HTTP 工具，不能泄露最终 payload。"
                "只输出 JSON 对象。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "生成一个教师可审核的题目版本草稿。",
                    "outputSchema": {
                        "title": "中文题目标题",
                        "summary": "中文教学摘要",
                        "manifestNotes": ["对 manifest 的审核备注"],
                        "rubricDraft": {
                            "criteria": [
                                {
                                    "id": "标准标识",
                                    "title": "中文评分项",
                                    "graderType": "DETERMINISTIC_ORACLE|EVENT_PATTERN|LLM_RUBRIC",
                                    "maxScore": "数字",
                                    "evidencePolicy": {"requiredEventTypes": ["事件类型"]},
                                }
                            ]
                        },
                        "teacherReviewChecklist": ["教师发布前检查项"],
                        "confidence": "0 到 1 的数字",
                    },
                    "brief": _redact_sensitive_text(brief),
                    "courseIntent": _redact_sensitive_values(intent),
                    "candidateManifest": _public_manifest_projection(candidate_manifest),
                    "candidateRubric": _public_rubric_projection(candidate_rubric),
                },
                ensure_ascii=False,
            ),
        },
    ]
    return _chat_completion_json(settings, messages, prompt_version=VERSION_DRAFTER_PROMPT_VERSION)


def _require_model_settings(settings: Settings) -> None:
    if not settings.agent_runtime_enabled:
        raise AgentRuntimeError("AGENT_RUNTIME_DISABLED", "Agent runtime is disabled")
    if settings.model_provider != "openai-compatible":
        raise AgentRuntimeError("MODEL_PROVIDER_UNSUPPORTED", "Only openai-compatible provider is supported")
    if not settings.model_base_url or not settings.model_name:
        raise AgentRuntimeError("MODEL_CONFIG_INCOMPLETE", "Model base URL and model name are required")


def _chat_completion_json(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    prompt_version: str,
) -> AgentModelResult:
    request_body = {
        "model": settings.model_name,
        "messages": messages,
        "temperature": settings.model_temperature,
        "max_tokens": settings.model_max_tokens,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _chat_completions_url(settings.model_base_url),
        data=body,
        method="POST",
        headers=_model_headers(settings),
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.model_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AgentRuntimeError("MODEL_HTTP_ERROR", f"Model endpoint returned {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AgentRuntimeError("MODEL_UNAVAILABLE", "Model endpoint is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise AgentRuntimeError("MODEL_RESPONSE_INVALID", "Model endpoint returned invalid JSON") from exc

    content = _extract_message_content(payload)
    try:
        output = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise AgentRuntimeError("MODEL_OUTPUT_NOT_JSON", "Model output is not a JSON object") from exc
    if not isinstance(output, dict):
        raise AgentRuntimeError("MODEL_OUTPUT_NOT_OBJECT", "Model output must be a JSON object")
    usage = payload.get("usage") if isinstance(payload, dict) else {}
    return AgentModelResult(
        output=output,
        usage={
            "provider": settings.model_provider,
            "model": settings.model_name,
            "promptVersion": prompt_version,
            "rawUsage": usage if isinstance(usage, dict) else {},
        },
    )


def _chat_completions_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def _model_headers(settings: Settings) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if settings.model_api_key:
        headers["authorization"] = f"Bearer {settings.model_api_key}"
    return headers


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise AgentRuntimeError("MODEL_RESPONSE_INVALID", "Model response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise AgentRuntimeError("MODEL_RESPONSE_INVALID", "Model response has no message content")
    return content


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _redact_sensitive_text(value: str) -> str:
    text = value
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub(r"\1[已脱敏]", text)
    return text


def _redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if re.search(r"(?i)(api[_-]?key|token|password|secret|authorization)", key_text):
                result[key_text] = "[已脱敏]"
            else:
                result[key_text] = _redact_sensitive_values(item)
        return result
    return value


def _public_manifest_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    metadata = manifest.get("metadata", {})
    spec = manifest.get("spec", {})
    return {
        "metadata": metadata,
        "category": spec.get("category"),
        "workspace": spec.get("workspace"),
        "learningObjectives": spec.get("learningObjectives", []),
        "difficulty": spec.get("difficulty"),
        "expectedMinutes": spec.get("expectedMinutes"),
        "runtime": spec.get("runtime"),
        "successOracle": {
            "type": spec.get("successOracle", {}).get("type")
            if isinstance(spec.get("successOracle"), dict)
            else None
        },
        "tutorPolicy": spec.get("tutorPolicy"),
        "futureCapabilities": spec.get("futureCapabilities"),
    }


def _public_rubric_projection(rubric: dict[str, Any]) -> dict[str, Any]:
    return {
        "rubricVersion": rubric.get("rubricVersion"),
        "criteria": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "graderType": item.get("graderType"),
                "maxScore": item.get("maxScore"),
                "evidencePolicy": item.get("evidencePolicy"),
            }
            for item in rubric.get("criteria", [])
            if isinstance(item, dict)
        ],
    }
