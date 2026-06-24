from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_compose_terminal_vertical_slice_services_are_wired() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose/docker-compose.yml").read_text())
    services = compose["services"]
    for name in ["postgres", "redis", "minio", "api", "terminal-gateway", "sessiond", "target"]:
        assert name in services
    api_env = services["api"]["environment"]
    gateway_env = services["terminal-gateway"]["environment"]
    sessiond_env = services["sessiond"]["environment"]
    assert api_env["CLA_DATABASE_URL"].startswith("postgresql+psycopg://")
    assert api_env["CLA_SESSIOND_ENDPOINT"] == "sessiond:7777"
    assert api_env["CLA_TRANSCRIPT_STORAGE_BACKEND"] == "local"
    assert api_env["CLA_TRANSCRIPT_OBJECT_ROOT"] == "/tmp/cla-transcript-objects"
    assert api_env["CLA_TRANSCRIPT_S3_BUCKET"] == "cla-transcript-raw"
    assert api_env["CLA_TRANSCRIPT_S3_PREFIX"] == "terminal-transcripts"
    assert api_env["CLA_TRANSCRIPT_S3_ENDPOINT_URL"] == "http://minio:9000"
    assert api_env["CLA_TRANSCRIPT_S3_FORCE_PATH_STYLE"] == "true"
    assert api_env["CLA_TRANSCRIPT_ENCRYPTION_KEY"]
    assert api_env["CLA_REMOTE_DESKTOP_ENABLED"] == "false"
    assert api_env["CLA_SIMULATED_WORKSPACE_ENABLED"] == "false"
    assert gateway_env["CLA_API_URL"] == "http://api:8000"
    assert gateway_env["CLA_REDIS_ADDR"] == "redis:6379"
    assert gateway_env["CLA_RECORDING_QUEUE_SIZE"] == "1024"
    assert sessiond_env["CLA_SESSIOND_ADDR"] == "0.0.0.0:7777"
    assert services["terminal-gateway"]["build"]["context"] == "../.."
    assert services["terminal-gateway"]["build"]["dockerfile"] == (
        "services/terminal-gateway/Dockerfile"
    )
    assert services["sessiond"]["build"]["context"] == "../.."
    assert services["sessiond"]["build"]["dockerfile"] == "runtime/sessiond/Dockerfile"


def test_compose_does_not_enable_forbidden_lab_privileges() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose/docker-compose.yml").read_text())
    forbidden_keys = {
        "privileged",
        "network_mode",
        "pid",
        "ipc",
        "cap_add",
        "devices",
    }
    offenders: list[str] = []
    for service_name, service in compose["services"].items():
        for key in forbidden_keys:
            if key in service:
                offenders.append(f"{service_name}.{key}")
        for volume in service.get("volumes", []) or []:
            if isinstance(volume, str) and volume.startswith("/"):
                offenders.append(f"{service_name}.host-volume:{volume}")
    assert offenders == []


def test_go_dockerfiles_include_shared_sessionwire_module() -> None:
    gateway_dockerfile = (ROOT / "services/terminal-gateway/Dockerfile").read_text()
    sessiond_dockerfile = (ROOT / "runtime/sessiond/Dockerfile").read_text()
    for dockerfile in [gateway_dockerfile, sessiond_dockerfile]:
        assert "ENV GOWORK=off" in dockerfile
        assert "COPY packages/sessionwire/go.mod packages/sessionwire/go.mod" in dockerfile
        assert "COPY packages/sessionwire packages/sessionwire" in dockerfile
        assert "COPY go.work ./" in dockerfile


def test_environment_controller_deployment_boundary_is_declared() -> None:
    dockerfile = (ROOT / "services/environment-controller/Dockerfile").read_text()
    assert "ENV GOWORK=off" in dockerfile
    assert "go build -o /out/environment-controller ./cmd/controller" in dockerfile
    assert "USER nonroot:nonroot" in dockerfile

    values = yaml.safe_load((ROOT / "deploy/helm/cla/values.yaml").read_text())
    assert values["environmentController"]["image"] == "cla/environment-controller:dev"
    assert values["environmentController"]["apiURL"] == "http://cla-api:8000"
    assert values["environmentController"]["orphanScanInterval"] == "5m"
    assert values["environmentController"]["orphanGracePeriod"] == "10m"

    deployment = (
        ROOT / "deploy/helm/cla/templates/environment-controller-deployment.yaml"
    ).read_text()
    assert "name: cla-environment-controller" in deployment
    assert "serviceAccountName:" in deployment
    assert "automountServiceAccountToken: true" in deployment
    assert "CLA_API_URL" in deployment
    assert "CLA_ORPHAN_SCAN_INTERVAL" in deployment
    assert "CLA_ORPHAN_GRACE_PERIOD" in deployment
    assert "CLA_INTERNAL_SERVICE_TOKEN" in deployment
    assert "secretKeyRef" in deployment
    assert "CLA_TARGET_SESSION_KEY" in deployment
    assert "readOnlyRootFilesystem: true" in deployment
    assert "allowPrivilegeEscalation: false" in deployment
    assert 'drop: ["ALL"]' in deployment

    rbac = (ROOT / "deploy/helm/cla/templates/environment-controller-rbac.yaml").read_text()
    assert "kind: ClusterRole" in rbac
    assert "labsessions/status" in rbac
    assert "networkpolicies" in rbac
    assert "deployments" in rbac
    assert "resourcequotas" in rbac
    assert "hostPath" not in deployment + rbac
    assert "privileged" not in deployment + rbac


def test_api_deployment_declares_transcript_object_storage_boundary() -> None:
    values = yaml.safe_load((ROOT / "deploy/helm/cla/values.yaml").read_text())
    storage = values["api"]["transcriptStorage"]
    assert storage["backend"] == "s3"
    assert storage["s3Bucket"] == "cla-transcript-raw"
    assert storage["s3Prefix"] == "terminal-transcripts"
    assert storage["encryptionKeySecretName"] == "cla-transcript-encryption"

    deployment = (ROOT / "deploy/helm/cla/templates/api-deployment.yaml").read_text()
    for env_name in [
        "CLA_TRANSCRIPT_STORAGE_BACKEND",
        "CLA_TRANSCRIPT_OBJECT_ROOT",
        "CLA_TRANSCRIPT_S3_BUCKET",
        "CLA_TRANSCRIPT_S3_PREFIX",
        "CLA_TRANSCRIPT_S3_ENDPOINT_URL",
        "CLA_TRANSCRIPT_S3_REGION",
        "CLA_TRANSCRIPT_S3_FORCE_PATH_STYLE",
        "CLA_TRANSCRIPT_ENCRYPTION_KEY",
    ]:
        assert env_name in deployment
    assert "secretKeyRef" in deployment
    assert "encryption-key" in deployment
    assert "AWS_SECRET_ACCESS_KEY" not in deployment
    assert "automountServiceAccountToken: false" in deployment
    assert "readOnlyRootFilesystem: true" in deployment


def test_gateway_deployment_boundary_and_recording_config_are_declared() -> None:
    values = yaml.safe_load((ROOT / "deploy/helm/cla/values.yaml").read_text())
    assert values["gateway"]["image"] == "cla/terminal-gateway:dev"
    assert values["gateway"]["apiURL"] == "http://cla-api:8000"
    assert values["gateway"]["recordingQueueSize"] == 1024
    assert values["gateway"]["internalServiceTokenSecretName"] == "cla-internal-service"

    deployment = (ROOT / "deploy/helm/cla/templates/gateway-deployment.yaml").read_text()
    assert "automountServiceAccountToken: false" in deployment
    assert "CLA_API_URL" in deployment
    assert "CLA_INTERNAL_SERVICE_TOKEN" in deployment
    assert "secretKeyRef" in deployment
    assert "CLA_RECORDING_QUEUE_SIZE" in deployment
    assert "readOnlyRootFilesystem: true" in deployment
    assert "allowPrivilegeEscalation: false" in deployment
    assert 'drop: ["ALL"]' in deployment
    assert "hostPath" not in deployment
    assert "privileged" not in deployment
