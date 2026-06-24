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
            "workspaceType": "TERMINAL",
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
            challenge,
            version,
            validation_run,
            assignment,
        ]
    )
    db.commit()


def _ensure_dev_validation_run(db: Session) -> None:
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
