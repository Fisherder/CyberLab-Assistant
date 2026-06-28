from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
import yaml

from cla import models
from cla.challenge_assets import store_generated_challenge_package
from cla.ids import new_id
from cla.settings import Settings


REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_PATH = REPO_ROOT / "content" / "challenge-blueprints" / "authoritative-catalog.yaml"
CUSTOM_CANDIDATE_ID = "custom-agent-scaffold"
CUSTOM_VALIDATION_REPORT_REF = "content/validation/generated-custom-scaffold.validation.json"
BLUEPRINT_VALIDATION_REPORT_REF = "content/validation/authoritative-blueprint.validation.json"
BLUEPRINT_SEMVER = "0.1.0-blueprint"


def load_blueprint_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    catalog = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(catalog, dict):
        raise ValueError("Blueprint catalog must be an object")
    return catalog


def catalog_counts(catalog: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in catalog_entries(catalog):
        category = str(entry.get("category", "UNKNOWN"))
        counts[category] = counts.get(category, 0) + 1
    return counts


def catalog_entries(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    entries = catalog.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("Blueprint catalog entries must be a list")
    return [entry for entry in entries if isinstance(entry, dict)]


def validate_blueprint_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    entries = catalog_entries(catalog)
    ids = [str(entry.get("id", "")) for entry in entries]
    duplicates = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    counts = catalog_counts(catalog)
    minimum = catalog.get("qualityGate", {}).get("minimumPerCategory", {})
    missing = {
        category: int(required)
        for category, required in minimum.items()
        if counts.get(category, 0) < int(required)
    }
    bad_entries = [
        str(entry.get("id", "<missing>"))
        for entry in entries
        if not entry.get("sourceRefs")
        or not entry.get("generator", {}).get("template")
        or str(entry.get("workspaceType")) != "TERMINAL"
    ]
    return {
        "valid": not duplicates and not missing and not bad_entries,
        "total": len(entries),
        "counts": counts,
        "duplicates": duplicates,
        "missingMinimums": missing,
        "badEntries": bad_entries,
    }


def import_authoritative_blueprints(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str,
    catalog_path: Path = CATALOG_PATH,
) -> dict[str, Any]:
    catalog = load_blueprint_catalog(catalog_path)
    validation = validate_blueprint_catalog(catalog)
    if not validation["valid"]:
        return {
            "imported": [],
            "skipped": [
                {
                    "path": str(catalog_path.relative_to(REPO_ROOT)),
                    "code": "BLUEPRINT_CATALOG_INVALID",
                    "message": json.dumps(validation, ensure_ascii=False, sort_keys=True),
                }
            ],
            "summary": validation,
        }

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in catalog_entries(catalog):
        try:
            view = _upsert_blueprint_entry(db, tenant_id=tenant_id, actor_id=actor_id, entry=entry, catalog=catalog)
            imported.append(view)
        except Exception as exc:
            skipped.append(
                {
                    "path": f"{catalog_path.relative_to(REPO_ROOT)}#{entry.get('id')}",
                    "code": exc.__class__.__name__,
                    "message": str(exc),
                }
            )
    return {"imported": imported, "skipped": skipped, "summary": validation}


def blueprint_manifest(entry: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    category = str(entry["category"])
    slug = str(entry["id"])
    return {
        "apiVersion": "cla.edu/v1",
        "kind": "CyberChallenge",
        "metadata": {
            "id": slug,
            "version": BLUEPRINT_SEMVER,
            "title": str(entry["title"]),
            "license": "source-backed-blueprint",
        },
        "spec": {
            "category": category,
            "modality": "REAL_LAB",
            "workspace": {
                "type": "TERMINAL",
                "image": f"cla/workspace-{category.lower()}:blueprint",
                "shell": "/bin/bash",
                "user": "student",
                "capabilities": entry.get("workspaceCapabilities", []),
                "fileTransfer": "CONTROLLED",
            },
            "learningObjectives": entry.get("learningObjectives", []),
            "difficulty": int(entry.get("difficulty", 3)),
            "expectedMinutes": int(entry.get("expectedMinutes", 90)),
            "prerequisites": entry.get("prerequisites", []),
            "runtime": {
                "isolationTier": int(entry.get("isolationTier", 1)),
                "cpu": "500m",
                "memory": "768Mi",
                "ephemeralStorage": "1Gi",
                "ttlMinutes": max(60, int(entry.get("expectedMinutes", 90)) + 15),
                "maxResets": 2,
                "egressPolicy": "DENY_ALL",
            },
            "successOracle": {
                "type": "BLUEPRINT_EXTERNAL_ORACLE",
                "notes": entry.get("components", {}).get("oracle", "待生成具体外部 Oracle"),
            },
            "rubricRef": "rubric.yaml",
            "futureCapabilities": {"remoteDesktop": False, "simulatedWorkspace": False},
            "catalogBlueprint": {
                "catalogVersion": catalog.get("catalogVersion"),
                "sourcePolicy": catalog.get("qualityGate", {}).get("copyPolicy"),
                **entry,
            },
        },
    }


def composition_plan_for_candidates(
    intent: dict[str, Any],
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    *,
    max_items: int = 4,
) -> dict[str, Any]:
    if not candidates:
        return {
            "mode": "custom-agent-scaffold",
            "candidateIds": [CUSTOM_CANDIDATE_ID],
            "coverage": {
                "category": intent.get("category"),
                "learningObjectives": [],
                "reason": "没有满足硬约束的候选题，建议生成定制靶场代码包草稿。",
            },
            "notes": [
                "Agent 只能生成草稿和代码资产，不能直接部署或发布。",
                "生成后必须经过内容验证、教师审核和发布门禁。",
            ],
            "rejectedCount": len(rejected),
        }
    selected = [candidates[0]]
    groups = {_candidate_group(candidates[0])}
    compatible = set(_candidate_compatible_groups(candidates[0]))
    for candidate in candidates[1:]:
        group = _candidate_group(candidate)
        if len(selected) >= max_items:
            break
        if group and group not in groups and (not compatible or group in compatible):
            selected.append(candidate)
            groups.add(group)
            compatible.update(_candidate_compatible_groups(candidate))
    objectives = sorted(
        {
            objective
            for candidate in selected
            for objective in _candidate_learning_objectives(candidate)
        }
    )
    return {
        "mode": "compose-existing-blueprints" if len(selected) > 1 else "single-best-candidate",
        "candidateIds": [candidate["candidateId"] for candidate in selected],
        "coverage": {
            "category": intent.get("category"),
            "learningObjectives": objectives[:12],
            "groupCount": len(groups),
        },
        "notes": [
            "优先组合满足硬约束的蓝图或完整题目版本。",
            "组合计划只产生教师可审核的出题方案，不自动部署或发布。",
        ],
        "rejectedCount": len(rejected),
    }


def generate_custom_challenge_package(
    db: Session,
    settings: Settings,
    *,
    tenant_id: str,
    actor_id: str,
    draft: models.ChallengeDraft,
) -> tuple[models.ChallengeVersion, models.ValidationRun, dict[str, Any]]:
    intent = draft.intent_json
    category = str(intent.get("category") or "WEB").upper()
    if category not in {"WEB", "REVERSE", "PWN", "CRYPTO", "FORENSICS", "MISC"}:
        category = "MISC"
    slug = f"custom-{category.lower()}-{draft.id.split('_')[-1][:8]}"
    semver = f"0.1.0+custom.{draft.id.split('_')[-1][:8]}"
    files = _custom_package_files(slug, semver, draft.brief_text, intent, category)
    stored = store_generated_challenge_package(
        settings,
        tenant_id=tenant_id,
        slug=slug,
        semver=semver,
        files=files,
    )
    challenge_title = _custom_title(intent, category)
    challenge = models.Challenge(
        id=new_id("chal"),
        tenant_id=tenant_id,
        slug=slug,
        title=challenge_title,
        category=category,
        owner_id=actor_id,
    )
    manifest = yaml.safe_load(files["manifest.yaml"]) or {}
    manifest["authoring"] = {
        "sourceCandidateId": CUSTOM_CANDIDATE_ID,
        "generatedBy": "agent-scaffold",
        "courseIntent": intent,
        "brief": draft.brief_text,
        "generatedFiles": sorted(files),
    }
    version = models.ChallengeVersion(
        id=new_id("cv"),
        challenge_id=challenge.id,
        semver=semver,
        status="PENDING_APPROVAL",
        manifest_json=manifest,
        artifact_digest=stored.sha256,
        risk_tier=int(intent.get("isolationTier", 1)),
        created_by=actor_id,
    )
    validation_run = models.ValidationRun(
        id=new_id("vr"),
        version_id=version.id,
        workflow_id=f"publish/{draft.id}/custom-scaffold",
        status="WARN",
        report_ref=CUSTOM_VALIDATION_REPORT_REF,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
    )
    db.add_all([challenge, version, validation_run])
    db.flush()
    db.add(
        models.ChallengeArtifact(
            id=new_id("casset"),
            tenant_id=tenant_id,
            challenge_id=challenge.id,
            version_id=version.id,
            artifact_type="generated-challenge-package",
            object_ref=stored.object_ref,
            sha256=stored.sha256,
            byte_count=stored.byte_count,
            metadata_json=stored.metadata,
        )
    )
    draft.status = "GENERATED_CUSTOM"
    draft.selected_version_id = version.id
    constraints = dict(draft.constraints_json)
    constraints["selectedCandidateId"] = CUSTOM_CANDIDATE_ID
    constraints["customPackage"] = True
    draft.constraints_json = constraints
    payload = {
        "generatedBy": "agent-scaffold",
        "draft": {
            "title": challenge.title,
            "summary": "未找到足够匹配的现有题目组合，已生成定制靶场代码包草稿。",
            "artifactRef": stored.object_ref,
            "artifactSha256": stored.sha256,
            "generatedFiles": sorted(files),
            "teacherReviewChecklist": [
                "运行内容验证和参考求解，确认没有 BLOCK 项。",
                "检查生成代码不包含动态秘密、真实 token、教师解法或最终 payload。",
                "确认 Dockerfile、Oracle、Rubric 和资源限制符合课程要求。",
            ],
            "confidence": 0.58,
        },
    }
    return version, validation_run, payload


def _upsert_blueprint_entry(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str,
    entry: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    slug = str(entry["id"])
    challenge_id = _stable_id("chalbp", slug)
    version_id = _stable_id("cvbp", slug)
    validation_id = _stable_id("vrbp", slug)
    manifest = blueprint_manifest(entry, catalog)
    digest = _digest_json(manifest)
    challenge = db.get(models.Challenge, challenge_id)
    created = False
    if challenge is None:
        challenge = models.Challenge(
            id=challenge_id,
            tenant_id=tenant_id,
            slug=slug,
            title=str(entry["title"]),
            category=str(entry["category"]),
            owner_id=actor_id,
        )
        db.add(challenge)
        created = True
    else:
        challenge.title = str(entry["title"])
        challenge.category = str(entry["category"])
    version = db.get(models.ChallengeVersion, version_id)
    if version is None:
        version = models.ChallengeVersion(
            id=version_id,
            challenge_id=challenge.id,
            semver=BLUEPRINT_SEMVER,
            status="BLUEPRINT",
            manifest_json=manifest,
            artifact_digest=digest,
            risk_tier=int(entry.get("isolationTier", 1)),
            created_by=actor_id,
        )
        db.add(version)
        created = True
    else:
        version.manifest_json = manifest
        version.artifact_digest = digest
        version.risk_tier = int(entry.get("isolationTier", 1))
    db.flush()
    run = db.get(models.ValidationRun, validation_id)
    if run is None:
        run = models.ValidationRun(
            id=validation_id,
            version_id=version.id,
            workflow_id=f"blueprint-catalog/{slug}",
            status="BLUEPRINT",
            report_ref=BLUEPRINT_VALIDATION_REPORT_REF,
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )
        db.add(run)
    else:
        run.status = "BLUEPRINT"
        run.report_ref = BLUEPRINT_VALIDATION_REPORT_REF
        run.ended_at = datetime.now(timezone.utc)
    artifact = db.scalar(
        select(models.ChallengeArtifact)
        .where(models.ChallengeArtifact.version_id == version.id)
        .where(models.ChallengeArtifact.artifact_type == "blueprint-catalog-entry")
    )
    if artifact is None:
        db.add(
            models.ChallengeArtifact(
                id=new_id("casset"),
                tenant_id=tenant_id,
                challenge_id=challenge.id,
                version_id=version.id,
                artifact_type="blueprint-catalog-entry",
                object_ref=f"catalog://authoritative-blueprints/{slug}",
                sha256=digest,
                byte_count=len(json.dumps(entry, ensure_ascii=False).encode("utf-8")),
                metadata_json={
                    "artifactKind": "blueprint-catalog-entry",
                    "sourceRefs": entry.get("sourceRefs", []),
                    "generator": entry.get("generator", {}),
                },
            )
        )
    return _registry_view(db, version, challenge, created=created)


def _registry_view(
    db: Session,
    version: models.ChallengeVersion,
    challenge: models.Challenge,
    *,
    created: bool,
) -> dict[str, Any]:
    manifest = version.manifest_json
    spec = manifest.get("spec", {})
    artifacts = db.scalars(
        select(models.ChallengeArtifact)
        .where(models.ChallengeArtifact.version_id == version.id)
        .order_by(models.ChallengeArtifact.created_at.desc(), models.ChallengeArtifact.id.desc())
    ).all()
    return {
        "challengeId": challenge.id,
        "challengeVersionId": version.id,
        "slug": challenge.slug,
        "title": challenge.title,
        "category": challenge.category,
        "semver": version.semver,
        "status": version.status,
        "workspaceType": spec.get("workspace", {}).get("type", "TERMINAL"),
        "difficulty": int(spec.get("difficulty", 0) or 0),
        "expectedMinutes": int(spec.get("expectedMinutes", 0) or 0),
        "riskTier": version.risk_tier,
        "artifactDigest": version.artifact_digest,
        "validationStatus": "BLUEPRINT",
        "searchScore": 0.0,
        "created": created,
        "artifactCount": len(artifacts),
        "latestArtifactRef": artifacts[0].object_ref if artifacts else None,
        "approvalUrl": f"/api/v1/challenge-versions/{version.id}/approve",
        "validationUrl": f"/api/v1/challenge-versions/{version.id}/validation",
    }


def _candidate_group(candidate: dict[str, Any]) -> str:
    return str(candidate.get("retrievalSignals", {}).get("compositionGroup", ""))


def _candidate_compatible_groups(candidate: dict[str, Any]) -> list[str]:
    values = candidate.get("retrievalSignals", {}).get("compatibleGroups", [])
    return [str(value) for value in values] if isinstance(values, list) else []


def _candidate_learning_objectives(candidate: dict[str, Any]) -> list[str]:
    values = candidate.get("retrievalSignals", {}).get("learningObjectives", [])
    return [str(value) for value in values] if isinstance(values, list) else []


def _custom_package_files(slug: str, semver: str, brief: str, intent: dict[str, Any], category: str) -> dict[str, str]:
    manifest = _custom_manifest(slug, semver, intent, category)
    files = {
        "manifest.yaml": yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        "README.md": _custom_readme(slug, brief, category),
        "rubric.yaml": _custom_rubric(category),
        "topology.yaml": _custom_topology(category),
        "workspace/Dockerfile": "FROM debian:bookworm-slim\nRUN apt-get update && apt-get install -y curl python3 gdb binutils && rm -rf /var/lib/apt/lists/*\nUSER 1000\nWORKDIR /home/student\n",
        "oracle/validator.py": _custom_oracle(category),
    }
    if category == "WEB":
        files["target/Dockerfile"] = "FROM python:3.12-slim\nWORKDIR /app\nCOPY server.py /app/server.py\nCMD [\"python\", \"/app/server.py\"]\n"
        files["target/server.py"] = _custom_web_target(intent)
    elif category == "REVERSE":
        files["target/Dockerfile"] = "FROM debian:bookworm-slim\nWORKDIR /challenge\nCOPY challenge.c /challenge/challenge.c\nRUN apt-get update && apt-get install -y gcc && gcc -O1 -o challenge challenge.c && rm -rf /var/lib/apt/lists/*\nCMD [\"/bin/sleep\", \"infinity\"]\n"
        files["target/challenge.c"] = _custom_reverse_target()
    elif category == "PWN":
        files["target/Dockerfile"] = "FROM debian:bookworm-slim\nWORKDIR /challenge\nCOPY vuln.c /challenge/vuln.c\nRUN apt-get update && apt-get install -y gcc socat && gcc -fno-stack-protector -no-pie -o vuln vuln.c && rm -rf /var/lib/apt/lists/*\nCMD [\"socat\", \"TCP-LISTEN:31337,reuseaddr,fork\", \"EXEC:/challenge/vuln\"]\n"
        files["target/vuln.c"] = _custom_pwn_target(intent)
    else:
        files["target/Dockerfile"] = "FROM python:3.12-slim\nWORKDIR /challenge\nCOPY task.py /challenge/task.py\nCMD [\"python\", \"/challenge/task.py\"]\n"
        files["target/task.py"] = _custom_terminal_task(category)
    return files


def _custom_manifest(slug: str, semver: str, intent: dict[str, Any], category: str) -> dict[str, Any]:
    return {
        "apiVersion": "cla.edu/v1",
        "kind": "CyberChallenge",
        "metadata": {"id": slug, "version": semver, "title": _custom_title(intent, category), "license": "internal-generated"},
        "spec": {
            "category": category,
            "modality": "REAL_LAB",
            "workspace": {
                "type": "TERMINAL",
                "image": f"cla/workspace-{category.lower()}:generated",
                "shell": "/bin/bash",
                "user": "student",
                "capabilities": intent.get("allowedTools", ["curl", "python"]),
                "fileTransfer": "CONTROLLED",
            },
            "studentAccess": _custom_student_access(category),
            "learningObjectives": intent.get("learningObjectives", []),
            "difficulty": int(intent.get("difficulty", 3)),
            "expectedMinutes": int(intent.get("expectedMinutes", 90)),
            "prerequisites": ["由 Agent 根据教师 Brief 生成后人工确认"],
            "runtime": {
                "isolationTier": int(intent.get("isolationTier", 1)),
                "cpu": "500m",
                "memory": "768Mi",
                "ephemeralStorage": "1Gi",
                "ttlMinutes": max(60, int(intent.get("expectedMinutes", 90)) + 15),
                "maxResets": 2,
                "egressPolicy": "DENY_ALL",
            },
            "topologyRef": "topology.yaml",
            "successOracle": {"type": "GENERATED_EXTERNAL_VALIDATOR", "validatorRef": "oracle/validator.py"},
            "rubricRef": "rubric.yaml",
            "futureCapabilities": {"remoteDesktop": False, "simulatedWorkspace": False},
        },
    }


def _custom_student_access(category: str) -> dict[str, Any]:
    if category == "WEB":
        return {
            "kind": "WEB_HTTP",
            "label": "目标网站",
            "entryPath": "/",
            "actionLabel": "在浏览器中打开目标网站",
            "description": "这是 Web 类实践题。目标服务必须提供可浏览的入口页，学生可以先用浏览器做初步探索。",
            "guidance": "建议先打开目标网站观察交互，再进入终端用 curl 或 Python 复现请求。",
            "commands": [
                'curl -i "$TARGET_BASE_URL/"',
                'curl -i "$TARGET_BASE_URL/healthz"',
            ],
        }
    if category == "REVERSE":
        return {
            "kind": "DOWNLOAD_FILE",
            "label": "目标文件",
            "downloadPath": "target/challenge.c",
            "actionLabel": "下载目标文件",
            "description": "这是逆向工程实践题，不依赖目标网站。学生应下载目标文件并使用命令行工具分析。",
            "guidance": "下载后可使用 file、strings、objdump、readelf、gdb 等工具分析。",
            "commands": ["file ./challenge", "strings ./challenge | head", "objdump -d ./challenge | less"],
        }
    if category == "CRYPTO":
        return {
            "kind": "DOWNLOAD_FILE",
            "label": "密码材料",
            "downloadPath": "target/task.py",
            "actionLabel": "下载密码材料",
            "description": "这是密码学实践题。学生应在终端中分析编码、密文、参数或脚本逻辑。",
            "guidance": "建议先查看题目材料，再用 Python、openssl 或 sage 编写最小验证脚本。",
            "commands": ["python3 target/task.py", "python3 solve.py"],
        }
    if category == "FORENSICS":
        return {
            "kind": "DOWNLOAD_FILE",
            "label": "取证材料",
            "downloadPath": "target/task.py",
            "actionLabel": "下载取证材料",
            "description": "这是数字取证实践题。学生应提取文件、流量、日志或元数据证据。",
            "guidance": "建议先确认文件类型，再用 file、strings、tshark、exiftool 或脚本提取证据。",
            "commands": ["file target/task.py", "strings target/task.py | head"],
        }
    if category == "MISC":
        return {
            "kind": "TERMINAL_ONLY",
            "label": "终端任务",
            "actionLabel": "进入终端",
            "description": "这是 CTF 通用技能实践题。学生应使用命令行工具完成可复现的数据处理或交互任务。",
            "guidance": "建议记录关键命令、输入输出和文件变化。",
            "commands": ["ls -la", "python3 target/task.py"],
        }
    return {
        "kind": "TERMINAL_ONLY",
        "label": "终端目标",
        "actionLabel": "进入终端",
        "description": "这是终端交互类实践题，通常通过命令行连接目标进程或运行脚本完成。",
        "guidance": "请先获取容器并进入终端，根据题面使用 nc、python、gdb 等工具与目标交互。",
        "commands": ['nc "$TARGET_HOST" "${TARGET_PORT:-31337}"', "python3 solve.py"],
    }


def _custom_readme(slug: str, brief: str, category: str) -> str:
    return f"""# {slug}

本目录是 CLA 根据教师需求生成的 {category} 定制靶场草稿。该目录面向教师审核和内容验证，不应直接作为学生题面发布。

## 资产组成

- `manifest.yaml`：题目版本、工作区、运行时、Oracle 与 Rubric 引用。
- `workspace/Dockerfile`：学生终端工作区基础镜像。
- `target/`：目标服务或目标程序源码。
- `oracle/validator.py`：外部验证器草稿。
- `rubric.yaml`：评分标准草稿。
- `topology.yaml`：工作区与目标服务的网络拓扑草稿。

## 审核要求

1. 运行内容验证、参考求解和负例测试。
2. 检查目标服务、数据库初始化、评分标准和资源限制是否符合课程目标。
3. 确认题面、提示和日志不包含动态秘密、教师解法或最终 payload。
4. 通过教师审批后再发布不可变题目版本。
"""


def _custom_rubric(category: str) -> str:
    return f"""version: 1.0.0
criteria:
  - id: objective-evidence
    title: 客观验证
    type: DETERMINISTIC_ORACLE
    maxScore: 60
  - id: root-cause
    title: 根因解释
    type: LLM_RUBRIC
    maxScore: 25
  - id: remediation
    title: 修复建议
    type: LLM_RUBRIC
    maxScore: 15
notes:
  category: {category}
  status: generated-scaffold
"""


def _custom_topology(category: str) -> str:
    return f"""services:
  workspace:
    role: WORKSPACE
  target:
    role: TARGET
    category: {category}
network:
  egress: DENY_ALL
"""


def _custom_oracle(category: str) -> str:
    return f"""from __future__ import annotations

def validate(observation: dict) -> dict:
    return {{
        "passed": bool(observation.get("generated_success")),
        "category": "{category}",
        "evidence": observation,
    }}
"""


def _custom_web_target(intent: dict[str, Any]) -> str:
    if _custom_is_xss(intent):
        return _custom_xss_target()
    return """from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from urllib.parse import parse_qs

SUCCESS = False
DB_PATH = "/tmp/cla_target.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT NOT NULL)")
        conn.execute("DELETE FROM users")
        conn.executemany(
            "INSERT INTO users(username, password, role) VALUES (?, ?, ?)",
            [
                ("alice", "alice-password", "student"),
                ("admin", "admin-password", "admin"),
            ],
        )


def login_with_vulnerable_query(username, password):
    query = "SELECT username, role FROM users WHERE username = '%s' AND password = '%s'" % (username, password)
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(query).fetchone()
    if row is None:
        return None
    return {"username": row[0], "role": row[1]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/", "/login"}:
            self.html()
            return
        if self.path == "/healthz":
            self.reply({"ok": True})
            return
        self.reply({"error": "not_found"}, 404)

    def do_POST(self):
        global SUCCESS
        length = int(self.headers.get("content-length", "0"))
        fields = parse_qs(self.rfile.read(length).decode())
        username = fields.get("username", [""])[0]
        password = fields.get("password", [""])[0]
        user = login_with_vulnerable_query(username, password)
        if user is None:
            self.reply({"ok": False, "message": "invalid credentials"}, 401)
            return
        SUCCESS = user.get("role") == "admin"
        self.reply({"ok": True, "user": user, "auth_bypass_observed": SUCCESS})

    def reply(self, body, status=200):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def html(self):
        data = '''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>CLA Web Target</title></head>
<body>
<main>
  <h1>CLA Web 登录调试页</h1>
  <p>这是生成的 Web 目标入口。先用普通账号建立失败基线，再在终端中用 curl 复现登录请求并比较响应。</p>
  <form method="post" action="/login">
    <label>用户名 <input name="username" value="alice"></label>
    <label>密码 <input name="password" value="wrong"></label>
    <button>登录</button>
  </form>
</main>
</body>
</html>'''.encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__":
    init_db()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""


def _custom_title(intent: dict[str, Any], category: str) -> str:
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    if category == "WEB" and _custom_is_xss(intent):
        return "定制 XSS 脚本注入靶场"
    if category == "WEB" and (
        "SQLI" in target
        or "INPUT_TRUST_BOUNDARY" in target
        or "identify-input-trust-boundary" in objectives
    ):
        return "定制 SQL 注入认证绕过靶场"
    if category == "WEB":
        return "定制 Web 安全靶场草稿"
    if category == "REVERSE":
        return "定制逆向工程靶场草稿"
    if category == "PWN" and _custom_is_integer_overflow(intent):
        return "定制 Pwn 整数溢出靶场"
    if category == "PWN":
        return "定制 Pwn 靶场草稿"
    if category == "CRYPTO":
        return "定制密码学分析靶场草稿"
    if category == "FORENSICS":
        return "定制数字取证靶场草稿"
    if category == "MISC":
        return "定制 CTF 通用技能靶场草稿"
    return f"定制 {category} 靶场草稿"


def _custom_xss_target() -> str:
    return """from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import sqlite3
from urllib.parse import parse_qs, urlparse

DB_PATH = "/tmp/cla_xss_target.db"
OBSERVED = False


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL)")
        conn.execute("DELETE FROM messages")
        conn.execute("INSERT INTO messages(content) VALUES (?)", ("hello from cla",))


def list_messages():
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute("SELECT content FROM messages ORDER BY id DESC LIMIT 10")]


def add_message(content):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO messages(content) VALUES (?)", (content,))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global OBSERVED
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.reply({"ok": True})
            return
        if parsed.path == "/oracle":
            self.reply({"generated_success": OBSERVED})
            return
        if parsed.path not in {"/", "/message"}:
            self.reply({"error": "not_found"}, 404)
            return
        params = parse_qs(parsed.query)
        probe = params.get("probe", [""])[0]
        if probe:
            add_message(probe)
            OBSERVED = "<script" in probe.lower() or "onerror" in probe.lower()
        self.html()

    def do_POST(self):
        global OBSERVED
        length = int(self.headers.get("content-length", "0"))
        fields = parse_qs(self.rfile.read(length).decode())
        content = fields.get("message", [""])[0]
        add_message(content)
        OBSERVED = "<script" in content.lower() or "onerror" in content.lower()
        self.reply({"ok": True, "stored": content, "xss_probe_observed": OBSERVED})

    def reply(self, body, status=200):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def html(self):
        rows = "".join(f"<li>{item}</li>" for item in list_messages())
        safe_example = html.escape("普通文本")
        data = f'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>CLA XSS Target</title></head>
<body>
<main>
  <h1>CLA XSS 留言调试页</h1>
  <p>普通文本示例：{safe_example}</p>
  <form method="post" action="/message">
    <label>留言 <input name="message" value="hello"></label>
    <button>提交</button>
  </form>
  <ul>{rows}</ul>
</main>
</body>
</html>'''.encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    init_db()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""


def _custom_reverse_target() -> str:
    return """#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    const char *expected = "cla-proof";
    if (argc == 2 && strcmp(argv[1], expected) == 0) {
        puts("accepted");
        return 0;
    }
    puts("try again");
    return 1;
}
"""


def _custom_terminal_task(category: str) -> str:
    prompt = {
        "CRYPTO": "分析给定编码或密码材料，编写脚本验证恢复过程。",
        "FORENSICS": "检查给定取证材料，提取可复核证据并说明结论。",
        "MISC": "使用终端工具完成文件、文本或数据处理任务。",
    }.get(category, "完成终端安全实践任务。")
    return f"""from pathlib import Path

WORKDIR = Path("/challenge")


def main():
    (WORKDIR / "README.task.txt").write_text(
        "{prompt}\\n提交时需要说明命令、输入输出和判断依据。\\n",
        encoding="utf-8",
    )
    print("CLA generated terminal task scaffold")
    print("category: {category}")
    print("proof marker: cla-proof")


if __name__ == "__main__":
    main()
"""


def _custom_pwn_target(intent: dict[str, Any]) -> str:
    if _custom_is_integer_overflow(intent):
        return """#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    unsigned int count = 0;
    puts("item count:");
    if (scanf("%u", &count) != 1) {
        puts("bad input");
        return 1;
    }
    unsigned int bytes = count * 16;
    if (bytes < count) {
        puts("integer boundary crossed");
        puts("cla-proof");
        return 0;
    }
    printf("allocating %u bytes\\n", bytes);
    void *buffer = malloc(bytes);
    if (!buffer) {
        puts("allocation failed");
        return 1;
    }
    free(buffer);
    puts("done");
    return 0;
}
"""
    return """#include <stdio.h>
#include <unistd.h>

void win(void) {
    puts("cla-proof");
}

int main(void) {
    char buf[64];
    puts("input:");
    read(0, buf, 160);
    puts("done");
    return 0;
}
"""


def _custom_is_xss(intent: dict[str, Any]) -> bool:
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    return (
        "XSS" in target
        or "validate-cross-site-scripting-impact" in objectives
        or "explain-output-encoding" in objectives
    )


def _custom_is_integer_overflow(intent: dict[str, Any]) -> bool:
    target = str(intent.get("target") or "").upper()
    objectives = {str(item) for item in intent.get("learningObjectives", [])}
    return "INTEGER_OVERFLOW" in target or "analyze-integer-overflow" in objectives


def _stable_id(prefix: str, slug: str) -> str:
    value = slug.replace("-", "_")
    candidate = f"{prefix}_{value}"
    if len(candidate) <= 64:
        return candidate
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{value[:48]}_{digest}"


def _digest_json(value: dict[str, Any]) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"
