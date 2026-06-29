from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cla import models


DEV_IDS = {
    "tenant": "tenant_dev",
    "teacher": "user_teacher",
    "student": "user_student",
    "other_student": "user_other_student",
    "course": "course_websec",
    "challenge": "chal_web_sqli_auth",
    "challenge_version": "cv_web_sqli_auth_1_3_0",
    "validation_run": "vr_web_sqli_auth_1_3_0",
    "assignment": "asg_web_sqli_auth",
}

DEV_VALIDATION_REPORT_REF = "content/validation/web-sqli-auth-001-1.3.0.validation.json"
DEV_SUCCESS_ORACLE = {
    "type": "EXTERNAL_HTTP_PREDICATE",
    "validatorRef": "oracle/validator.py",
    "timeoutSeconds": 10,
}


def seed_dev_data(db: Session) -> None:
    if db.scalar(select(models.Tenant).where(models.Tenant.id == DEV_IDS["tenant"])):
        _ensure_dev_validation_run(db)
        return
    tenant = models.Tenant(id=DEV_IDS["tenant"], slug="dev", name="CLA Dev Tenant")
    teacher = models.User(
        id=DEV_IDS["teacher"],
        tenant_id=tenant.id,
        oidc_subject="teacher@example.edu",
        display_name="Teacher",
        email="teacher@example.edu",
    )
    student = models.User(
        id=DEV_IDS["student"],
        tenant_id=tenant.id,
        oidc_subject="student@example.edu",
        display_name="Student",
        email="student@example.edu",
    )
    other_student = models.User(
        id=DEV_IDS["other_student"],
        tenant_id=tenant.id,
        oidc_subject="other@example.edu",
        display_name="Other Student",
        email="other@example.edu",
    )
    course = models.Course(
        id=DEV_IDS["course"],
        tenant_id=tenant.id,
        code="WEBSEC-101",
        title="Web Security Practice",
        term="2026-S",
        owner_id=teacher.id,
    )
    challenge = models.Challenge(
        id=DEV_IDS["challenge"],
        tenant_id=tenant.id,
        slug="web-sqli-auth-001",
        title="登录逻辑与输入信任边界",
        category="WEB",
        owner_id=teacher.id,
    )
    version = models.ChallengeVersion(
        id=DEV_IDS["challenge_version"],
        challenge_id=challenge.id,
        semver="1.3.0",
        status="PUBLISHED",
        manifest_json={
            "id": "web-sqli-auth-001",
            "version": "1.3.0",
            "category": "WEB",
            "workspaceType": "TERMINAL",
            "studentAccess": {
                "kind": "WEB_HTTP",
                "label": "目标网站",
                "entryPath": "/",
                "actionLabel": "在浏览器中打开目标网站",
                "description": "这是 Web 登录认证实践题。获取容器后，目标网站会显示可交互的登录调试页面，学生可以先用浏览器观察页面行为，再回到终端构造请求。",
                "guidance": "建议先打开目标网站进行初步探索，再在终端中使用 curl 复现登录请求、观察状态码和响应内容。",
                "commands": [
                    'curl -i "$TARGET_BASE_URL/"',
                    'curl -i "$TARGET_BASE_URL/healthz"',
                    'curl -i -X POST "$TARGET_BASE_URL/login" -d "username=alice&password=wrong"',
                ],
            },
            "successOracle": DEV_SUCCESS_ORACLE,
            "futureCapabilities": {"remoteDesktop": False, "simulatedWorkspace": False},
        },
        artifact_digest="sha256:dev-fixture-web-sqli-auth",
        risk_tier=1,
        created_by=teacher.id,
    )
    assignment = models.Assignment(
        id=DEV_IDS["assignment"],
        course_id=course.id,
        challenge_version_id=version.id,
        title="Web SQLi Auth Practice",
        attempt_policy_json={"maxAttempts": 1, "maxResets": 2},
    )
    validation_run = models.ValidationRun(
        id=DEV_IDS["validation_run"],
        version_id=version.id,
        workflow_id="validation/web-sqli-auth-001/1.3.0",
        status="PASS",
        report_ref=DEV_VALIDATION_REPORT_REF,
        started_at=datetime(2026, 6, 24, 8, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 24, 8, 4, tzinfo=timezone.utc),
    )
    db.add_all(
        [
            tenant,
            teacher,
            student,
            other_student,
            course,
            models.CourseMember(course_id=course.id, user_id=teacher.id, role="TEACHER"),
            models.CourseMember(course_id=course.id, user_id=student.id, role="STUDENT"),
            models.CourseMember(course_id=course.id, user_id=other_student.id, role="STUDENT"),
            challenge,
            version,
            validation_run,
            assignment,
        ]
    )
    db.commit()


def _ensure_dev_validation_run(db: Session) -> None:
    _ensure_dev_challenge_version_metadata(db)
    if db.get(models.ValidationRun, DEV_IDS["validation_run"]) is not None:
        return
    if db.get(models.ChallengeVersion, DEV_IDS["challenge_version"]) is None:
        return
    db.add(
        models.ValidationRun(
            id=DEV_IDS["validation_run"],
            version_id=DEV_IDS["challenge_version"],
            workflow_id="validation/web-sqli-auth-001/1.3.0",
            status="PASS",
            report_ref=DEV_VALIDATION_REPORT_REF,
            started_at=datetime(2026, 6, 24, 8, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 6, 24, 8, 4, tzinfo=timezone.utc),
        )
    )
    db.commit()


def _ensure_dev_challenge_version_metadata(db: Session) -> None:
    version = db.get(models.ChallengeVersion, DEV_IDS["challenge_version"])
    if version is None:
        return
    manifest = dict(version.manifest_json or {})
    changed = False
    if not isinstance(manifest.get("successOracle"), dict):
        manifest["successOracle"] = DEV_SUCCESS_ORACLE
        changed = True
    if changed:
        version.manifest_json = manifest
        db.commit()
