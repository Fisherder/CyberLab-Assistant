from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_web_sqli_manifest_is_terminal_only() -> None:
    manifest = yaml.safe_load(
        (ROOT / "content/challenges/web-sqli-auth/manifest.yaml").read_text()
    )
    assert manifest["spec"]["workspace"]["type"] == "TERMINAL"
    assert manifest["spec"]["futureCapabilities"] == {
        "remoteDesktop": False,
        "simulatedWorkspace": False,
    }
    assert manifest["spec"]["runtime"]["egressPolicy"] == "DENY_ALL"


def test_no_gui_runtime_dependencies_enter_phase_one_code() -> None:
    forbidden = {
        "guacd",
        "guacamole",
        "xrdp",
        "tigervnc",
        "novnc",
        "vncserver",
        "at-spi",
        "uiautomation",
        "burpsuite",
        "ida-pro",
    }
    checked_roots = ["apps", "services", "runtime", "deploy", "content", "packages"]
    offenders: list[str] = []
    for root_name in checked_roots:
        for path in (ROOT / root_name).rglob("*"):
            if any(
                excluded in path.parts
                    for excluded in {"tests", "__pycache__", "node_modules", ".next", ".next-dev", "dist", "build"}
            ):
                continue
            if path.is_file() and path.suffix not in {".png", ".jpg", ".jpeg", ".gif", ".ico"}:
                text = path.read_text(errors="ignore").lower()
                hits = sorted(token for token in forbidden if token in text)
                if hits:
                    offenders.append(f"{path.relative_to(ROOT)}: {','.join(hits)}")
    assert offenders == []


def test_agent_policy_names_forbidden_infrastructure_tools() -> None:
    policy = (ROOT / "packages/policy-bundles/agent-capabilities.rego").read_text()
    for tool in [
        "docker.run",
        "kubernetes.exec",
        "host.shell",
        "sql.raw",
        "http.any",
        "cloud.admin",
    ]:
        assert tool in policy


def test_labsession_crd_status_tracks_namespace_components_and_conditions() -> None:
    crd = yaml.safe_load((ROOT / "deploy/crd/labsession-crd.yaml").read_text())
    status = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["status"]
    properties = status["properties"]
    assert {"phase", "namespaceName", "routeReady", "components", "expiresAt", "conditions"} <= set(
        properties
    )
    assert properties["phase"]["enum"] == [
        "Pending",
        "Provisioning",
        "Ready",
        "Failed",
        "Expired",
        "Terminating",
    ]
    assert properties["components"]["additionalProperties"]["enum"] == [
        "Pending",
        "Ready",
        "Failed",
    ]
    condition = properties["conditions"]["items"]
    assert condition["required"] == ["type", "status"]


def test_internal_terminal_route_contract_keeps_endpoint_nested() -> None:
    spec = yaml.safe_load((ROOT / "packages/contracts/openapi/cla-api.yaml").read_text())
    route_schema = spec["components"]["schemas"]["InternalTerminalRoute"]
    assert "sessionRoute" in route_schema["required"]
    assert "endpoint" not in route_schema["properties"]
    assert "routeRef" not in route_schema["properties"]
    session_route = route_schema["properties"]["sessionRoute"]
    assert session_route["required"] == ["routeRef", "endpoint", "protocol"]
    assert session_route["properties"]["protocol"]["enum"] == ["tcp-sessionwire"]


def test_transcript_contract_uses_internal_token_and_excludes_route_fields() -> None:
    spec = yaml.safe_load((ROOT / "packages/contracts/openapi/cla-api.yaml").read_text())
    paths = spec["paths"]
    schemas = spec["components"]["schemas"]

    index_path = paths["/internal/attempts/{attemptId}/transcript-segments"]["post"]
    upload_path = paths["/internal/attempts/{attemptId}/transcript-segments/upload"]["post"]
    verify_path = paths[
        "/internal/attempts/{attemptId}/transcript-segments/verify-restore"
    ]["post"]
    retention_path = paths["/internal/transcript-segments/apply-retention"]["post"]
    for operation in [index_path, upload_path, verify_path, retention_path]:
        assert operation["security"] == [{"serviceToken": []}]
        schema_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        schema_name = schema_ref.removeprefix("#/components/schemas/")
        schema = schemas[schema_name]
        assert schema["additionalProperties"] is False
        assert not {"routeRef", "endpoint", "rawText", "plaintext"} & set(
            schema["properties"]
        )

    index_schema = schemas["TranscriptSegmentIndexRequest"]
    assert index_schema["required"] == [
        "sessionEpoch",
        "direction",
        "seqFrom",
        "seqTo",
        "objectRef",
        "sha256",
    ]
    assert index_schema["properties"]["direction"]["$ref"].endswith(
        "/TranscriptDirection"
    )

    upload_schema = schemas["TranscriptSegmentUploadRequest"]
    assert upload_schema["required"] == [
        "sessionEpoch",
        "direction",
        "seqFrom",
        "seqTo",
        "segmentBase64",
    ]
    assert upload_schema["properties"]["segmentBase64"]["contentEncoding"] == "base64"

    response_schema = schemas["TranscriptSegmentUploadResponse"]
    assert response_schema["additionalProperties"] is False
    assert "objectRef" in response_schema["required"]
    assert not {"routeRef", "endpoint"} & set(response_schema["properties"])

    verify_response = schemas["TranscriptRestoreVerifyResponse"]
    assert verify_response["additionalProperties"] is False
    assert verify_response["required"] == [
        "attemptId",
        "checked",
        "passed",
        "failed",
        "restorable",
        "results",
    ]
    verify_result = verify_response["properties"]["results"]["items"]
    assert not {"rawText", "plaintext", "plaintextSha256", "endpoint", "routeRef"} & set(
        verify_result["properties"]
    )

    retention_response = schemas["TranscriptRetentionApplyResponse"]
    assert retention_response["additionalProperties"] is False
    retention_request = schemas["TranscriptRetentionApplyRequest"]
    assert retention_request["properties"]["olderThanDays"]["type"] == ["integer", "null"]
    retention_result = retention_response["properties"]["results"]["items"]
    assert "retentionDays" in retention_result["required"]
    assert "policyRef" in retention_result["required"]
    assert not {"rawText", "plaintext", "plaintextSha256", "endpoint", "routeRef"} & set(
        retention_result["properties"]
    )
