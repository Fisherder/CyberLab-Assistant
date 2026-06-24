from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import warnings

from jsonschema import Draft202012Validator
import yaml

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from jsonschema import RefResolver


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CHALLENGE_DIR = REPO_ROOT / "content/challenges/web-sqli-auth"
DEFAULT_CONTRACTS_DIR = REPO_ROOT / "packages/contracts/json-schema"
DEFAULT_OUTPUT = REPO_ROOT / "content/validation/web-sqli-auth-001-1.3.0.validation.json"
DEFAULT_CHALLENGE_VERSION_ID = "cv_web_sqli_auth_1_3_0"
DEFAULT_ARTIFACT_DIGEST = "sha256:dev-fixture-web-sqli-auth"
FORBIDDEN_DISCLOSURES = ["final_payload", "dynamic_secret", "teacher_solution"]
FORBIDDEN_PHRASES = ["final payload", "dynamic secret", "teacher solution", "authorization"]


def validate_challenge(
    challenge_dir: Path = DEFAULT_CHALLENGE_DIR,
    contracts_dir: Path = DEFAULT_CONTRACTS_DIR,
    *,
    challenge_version_id: str = DEFAULT_CHALLENGE_VERSION_ID,
    artifact_digest: str = DEFAULT_ARTIFACT_DIGEST,
) -> dict[str, Any]:
    challenge_dir = challenge_dir.resolve()
    contracts_dir = contracts_dir.resolve()
    manifest = _read_yaml(challenge_dir / "manifest.yaml")
    rubric = _read_yaml(challenge_dir / "rubric.yaml")
    topology = _read_yaml(challenge_dir / "topology.yaml")
    network_policy = _read_yaml(challenge_dir / "policy/network.yaml")

    reference_ok, negative_ok = _run_oracle_smoke(challenge_dir)
    checks = [
        _check(
            "schema-lint",
            "SCHEMA",
            _schema_lint(manifest, rubric, contracts_dir)
            and _required_package_files_exist(challenge_dir),
            "Manifest、topology、rubric、milestone 和 policy 文件校验通过",
            ["challenge.schema.json", "rubric.schema.json", "policy/network.yaml"],
        ),
        _check(
            "fixed-dependency-build",
            "BUILD",
            _dockerfile_contexts_are_bounded(challenge_dir),
            "Workspace 与 target 镜像只从受限本地 fixture 上下文构建",
            ["workspace/Dockerfile", "target/Dockerfile"],
        ),
        _scan_check(manifest, challenge_dir),
        _check(
            "isolated-startup",
            "RUNTIME",
            _terminal_topology_is_isolated(manifest, topology, network_policy),
            "终端拓扑声明 workspace、target、默认拒绝网络和资源上限",
            ["topology.yaml", "policy/network.yaml"],
        ),
        _check(
            "reference-solve",
            "SOLVE",
            reference_ok,
            "参考路径能够到达外部可观测的认证绕过状态",
            ["oracle/validator.py", "target/server.py", "rubric.yaml"],
        ),
        _check(
            "negative-controls",
            "ORACLE",
            negative_ok,
            "负例观测不能满足外部 Oracle 谓词",
            ["oracle/validator.py", "target/server.py"],
        ),
        _check(
            "resource-budget",
            "RESOURCE",
            _resource_budget_fits_tier_one(manifest),
            "声明的 CPU、内存、存储和 TTL 符合一级终端实践限制",
            ["manifest.yaml:spec.runtime"],
        ),
        _check(
            "hint-leakage",
            "TUTOR",
            _hint_policy_blocks_disclosures(manifest, challenge_dir),
            "L1-L3 提示策略会阻断配置中的禁泄露类别",
            ["manifest.yaml:spec.tutorPolicy", "rubric.yaml"],
        ),
        _check(
            "phase-one-workspace-boundary",
            "WORKSPACE",
            _phase_one_workspace_boundary(manifest),
            "REMOTE_DESKTOP 和 SIMULATED 能力在一期被显式禁用",
            ["manifest.yaml:spec.futureCapabilities"],
        ),
    ]
    summary = {
        "passed": sum(1 for check in checks if check["status"] == "PASS"),
        "warnings": sum(1 for check in checks if check["status"] == "WARN"),
        "blocked": sum(1 for check in checks if check["status"] == "BLOCK"),
    }
    return {
        "schemaVersion": "cla.validation-report/0.1",
        "challengeVersionId": challenge_version_id,
        "artifactDigest": artifact_digest,
        "overallStatus": "BLOCK" if summary["blocked"] else "PASS",
        "summary": summary,
        "checks": checks,
        "forbiddenDisclosuresChecked": list(FORBIDDEN_DISCLOSURES),
    }


def write_validation_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def _schema_lint(
    manifest: dict[str, Any], rubric: dict[str, Any], contracts_dir: Path
) -> bool:
    challenge_schema = json.loads((contracts_dir / "challenge.schema.json").read_text())
    workspace_type_schema = json.loads((contracts_dir / "workspace-type.schema.json").read_text())
    rubric_schema = json.loads((contracts_dir / "rubric.schema.json").read_text())
    resolver = RefResolver.from_schema(
        challenge_schema,
        store={
            "workspace-type.schema.json": workspace_type_schema,
            workspace_type_schema.get("$id", ""): workspace_type_schema,
        },
    )
    Draft202012Validator(challenge_schema, resolver=resolver).validate(manifest)
    Draft202012Validator(rubric_schema).validate(rubric)
    return True


def _required_package_files_exist(challenge_dir: Path) -> bool:
    required = [
        "manifest.yaml",
        "rubric.yaml",
        "topology.yaml",
        "milestones.yaml",
        "policy/network.yaml",
        "policy/retention.yaml",
        "oracle/validator.py",
        "target/server.py",
        "target/Dockerfile",
        "workspace/Dockerfile",
    ]
    return all((challenge_dir / relative).is_file() for relative in required)


def _dockerfile_contexts_are_bounded(challenge_dir: Path) -> bool:
    for relative in ["target/Dockerfile", "workspace/Dockerfile"]:
        text = (challenge_dir / relative).read_text(encoding="utf-8")
        if "USER " not in text:
            return False
        if "COPY /" in text or "../" in text:
            return False
    return True


def _scan_check(manifest: dict[str, Any], challenge_dir: Path) -> dict[str, Any]:
    image_refs = [
        str(manifest.get("spec", {}).get("workspace", {}).get("image", "")),
        *_dockerfile_base_images(challenge_dir),
    ]
    has_dev_or_unpinned_image = any(
        image.endswith(":dev") or ("@" not in image and ":" in image) for image in image_refs if image
    )
    return {
        "id": "supply-chain-scan",
        "category": "SCAN",
        "status": "WARN" if has_dev_or_unpinned_image else "PASS",
        "title": "开发标签镜像引用仅允许用于本地验证"
        if has_dev_or_unpinned_image
        else "Image references are fixed to immutable digests",
        "evidenceRefs": ["artifact:sbom:web-sqli-auth-001@1.3.0"],
    }


def _dockerfile_base_images(challenge_dir: Path) -> list[str]:
    images: list[str] = []
    for relative in ["target/Dockerfile", "workspace/Dockerfile"]:
        for line in (challenge_dir / relative).read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0].upper() == "FROM":
                images.append(parts[1])
    return images


def _terminal_topology_is_isolated(
    manifest: dict[str, Any], topology: dict[str, Any], network_policy: dict[str, Any]
) -> bool:
    spec = manifest.get("spec", {})
    nodes = {node.get("id") for node in topology.get("nodes", []) if isinstance(node, dict)}
    network_policies = {
        network.get("policy") for network in topology.get("networks", []) if isinstance(network, dict)
    }
    forbidden = network_policy.get("forbidden", {})
    return (
        spec.get("workspace", {}).get("type") == "TERMINAL"
        and spec.get("runtime", {}).get("egressPolicy") == "DENY_ALL"
        and {"workspace", "target"} <= nodes
        and "DENY_ALL_EXCEPT_TOPOLOGY" in network_policies
        and all(forbidden.get(key) is True for key in [
            "privileged",
            "hostPath",
            "hostNetwork",
            "hostPID",
            "automountServiceAccountToken",
        ])
    )


def _run_oracle_smoke(challenge_dir: Path) -> tuple[bool, bool]:
    port = _free_local_port()
    session_key = "validation-session-key"
    env = {
        **os.environ,
        "TARGET_SESSION_KEY": session_key,
        "TARGET_PORT": str(port),
    }
    target = subprocess.Popen(
        [sys.executable, str(challenge_dir / "target/server.py")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if not _wait_for_health(base_url):
            return False, False
        before = _run_oracle_validator(challenge_dir, base_url, session_key)
        _reference_login(base_url)
        positive = _run_oracle_validator(challenge_dir, base_url, session_key)
        wrong_key = _run_oracle_validator(challenge_dir, base_url, "wrong-session-key")
        reference_ok = positive[0] == 0 and positive[1].get("passed") is True
        negative_ok = (
            before[0] != 0
            and before[1].get("passed") is False
            and wrong_key[0] != 0
            and wrong_key[1].get("passed") is False
        )
        return reference_ok, negative_ok
    finally:
        target.terminate()
        try:
            target.wait(timeout=3)
        except subprocess.TimeoutExpired:
            target.kill()
            target.wait(timeout=3)


def _run_oracle_validator(
    challenge_dir: Path, base_url: str, session_key: str
) -> tuple[int, dict[str, Any]]:
    env = {
        **os.environ,
        "ORACLE_TARGET_BASE_URL": base_url,
        "ORACLE_TARGET_SESSION_KEY": session_key,
    }
    result = subprocess.run(
        [sys.executable, str(challenge_dir / "oracle/validator.py")],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=10,
    )
    try:
        body = json.loads(result.stdout)
    except json.JSONDecodeError:
        body = {}
    return result.returncode, body if isinstance(body, dict) else {}


def _reference_login(base_url: str) -> None:
    body = urllib.parse.urlencode(
        {"username": "student' OR '1'='1", "password": "irrelevant"}
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/login",
        data=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=0.4) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.05)
    return False


def _resource_budget_fits_tier_one(manifest: dict[str, Any]) -> bool:
    runtime = manifest.get("spec", {}).get("runtime", {})
    return (
        runtime.get("isolationTier") == 1
        and _parse_cpu_millicores(str(runtime.get("cpu", "0"))) <= 1000
        and _parse_quantity_mib(str(runtime.get("memory", "0"))) <= 2048
        and _parse_quantity_mib(str(runtime.get("ephemeralStorage", "0"))) <= 4096
        and int(runtime.get("ttlMinutes", 0)) <= 120
        and int(runtime.get("maxResets", 0)) <= 5
    )


def _parse_cpu_millicores(value: str) -> int:
    if value.endswith("m"):
        return int(value[:-1])
    return int(float(value) * 1000)


def _parse_quantity_mib(value: str) -> int:
    if value.endswith("Gi"):
        return int(float(value[:-2]) * 1024)
    if value.endswith("Mi"):
        return int(float(value[:-2]))
    return int(float(value) / (1024 * 1024))


def _hint_policy_blocks_disclosures(manifest: dict[str, Any], challenge_dir: Path) -> bool:
    tutor_policy = manifest.get("spec", {}).get("tutorPolicy", {})
    configured = set(tutor_policy.get("forbiddenDisclosures", []))
    if not set(FORBIDDEN_DISCLOSURES) <= configured:
        return False
    if int(tutor_policy.get("maxHintLevel", 0)) != 3:
        return False
    for relative in ["rubric.yaml", "milestones.yaml"]:
        text = (challenge_dir / relative).read_text(encoding="utf-8").lower()
        if any(phrase in text for phrase in FORBIDDEN_PHRASES):
            return False
    return True


def _phase_one_workspace_boundary(manifest: dict[str, Any]) -> bool:
    future = manifest.get("spec", {}).get("futureCapabilities", {})
    return future == {"remoteDesktop": False, "simulatedWorkspace": False}


def _check(
    check_id: str,
    category: str,
    passed: bool,
    title: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "category": category,
        "status": "PASS" if passed else "BLOCK",
        "title": title,
        "evidenceRefs": evidence_refs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic CLA content validation")
    parser.add_argument("--challenge-dir", type=Path, default=DEFAULT_CHALLENGE_DIR)
    parser.add_argument("--contracts-dir", type=Path, default=DEFAULT_CONTRACTS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--challenge-version-id", default=DEFAULT_CHALLENGE_VERSION_ID)
    parser.add_argument("--artifact-digest", default=DEFAULT_ARTIFACT_DIGEST)
    args = parser.parse_args(argv)
    report = validate_challenge(
        args.challenge_dir,
        args.contracts_dir,
        challenge_version_id=args.challenge_version_id,
        artifact_digest=args.artifact_digest,
    )
    write_validation_report(report, args.output)
    print(json.dumps({"output": str(args.output), "summary": report["summary"]}))
    return 1 if report["overallStatus"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
