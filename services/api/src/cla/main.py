from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets

from fastapi import Depends, FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import yaml

from cla import models
from cla.authoring import (
    DEFAULT_CHALLENGE_DIR,
    DEFAULT_VALIDATION_REPORT_REF,
    challenge_manifest,
    generate_model_assisted_version,
    import_local_challenge_packages,
    list_challenge_registry,
    parse_course_intent_for_draft,
    search_challenge_candidates,
    validate_selected_challenge_package,
)
from cla.challenge_catalog import (
    CUSTOM_CANDIDATE_ID,
    generate_custom_challenge_package,
    import_authoritative_blueprints,
)
from cla.database import init_db, make_engine, make_session_factory, session_scope
from cla.events import append_event, latest_session_epoch
from cla.grading import publish_grade_revision
from cla.ids import new_id
from cla.oracle import verify_oracle_signature
from cla.schemas import (
    AppealRequest,
    AppendBatchRequest,
    AssignmentLiveView,
    AssignmentView,
    AuthTokenResponse,
    AttemptResponse,
    AttemptView,
    ChallengeApprovalView,
    ChallengeCandidateSearchView,
    ChallengeDraftView,
    ChallengeGeneratedVersionView,
    ChallengeImportView,
    ChallengeMaterializeView,
    ChallengeRegistryListView,
    ChallengeValidationView,
    ConsumeTicketRequest,
    CriterionOverrideRequest,
    CourseMemberView,
    CourseView,
    CreateAssignmentRequest,
    CreateChallengeBankItemRequest,
    CreateChallengeDraftRequest,
    CreateAttemptRequest,
    CreateCourseRequest,
    DestroyChallengeBankItemEnvironmentView,
    EnsureSessionRequest,
    GenerateChallengeVersionRequest,
    GradeView,
    HintFeedbackRequest,
    HintRequest,
    HintView,
    LoginRequest,
    MaterializeChallengeDraftRequest,
    OracleObservation,
    RegisterRequest,
    RouteRegistrationRequest,
    RouteUnregisterRequest,
    ResolveAppealRequest,
    SessionResponse,
    SubmitRequest,
    SubmitResponse,
    PublishChallengeBankItemRequest,
    StartChallengeBankItemView,
    StudentChallengeBankItemView,
    StudentChallengeBankListView,
    TerminalTicketResponse,
    TicketRevokeRequest,
    TutorStateView,
    TranscriptRetentionApplyRequest,
    TranscriptRestoreVerifyRequest,
    TranscriptSegmentRequest,
    TranscriptSegmentUploadRequest,
    ChallengeBankItemView,
    ChallengeBankListView,
    UpdateChallengeBankItemRequest,
    UpsertCourseMemberRequest,
)
from cla.security import (
    Principal,
    api_error,
    authenticate_request,
    create_local_auth_token,
    hash_password,
    require_attempt_owner,
    require_attempt_owner_or_teacher,
    require_course_role,
    verify_password,
)
from cla.seed import DEV_IDS, seed_dev_data
from cla.settings import Settings, load_settings
from cla.tickets import TicketError, consume_terminal_ticket, issue_terminal_ticket
from cla.transcripts import (
    TranscriptObjectDeleteError,
    TranscriptRestoreError,
    TranscriptObjectStoreError,
    decode_segment_base64,
    delete_transcript_object,
    store_transcript_object,
    verify_transcript_object,
)
from cla.tutor import (
    DETECTOR_VERSION,
    assess_attempt,
    auto_hints_disabled,
    cooldown_active,
    create_hint,
    latest_assessment,
    latest_hint,
    persist_assessment,
)


SECURITY_ALERT_EVENT_TYPES = {"lab.egress.denied", "policy.egress.denied", "security.policy.denied"}
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TRANSCRIPT_RETENTION_DAYS = 30


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = make_engine(settings.database_url)
    SessionLocal = make_session_factory(engine)
    init_db(engine)
    with SessionLocal() as db:
        seed_dev_data(db)

    app = FastAPI(title="CLA Terminal Practice API", version="0.1.0")
    app.state.settings = settings
    app.state.SessionLocal = SessionLocal

    def get_db() -> Session:
        yield from session_scope(SessionLocal)

    def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
        return authenticate_request(request, db, settings)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "agentRuntimeEnabled": settings.agent_runtime_enabled}

    @app.post("/api/v1/auth/register", response_model=AuthTokenResponse, status_code=201)
    def register_local_account(body: RegisterRequest, db: Session = Depends(get_db)) -> dict:
        _require_local_auth_enabled(settings)
        email = _normalize_email(body.email)
        display_name = body.displayName.strip()
        if not email:
            raise api_error(422, "INVALID_EMAIL", "Email is invalid")
        if db.scalar(
            select(models.User).where(
                models.User.tenant_id == DEV_IDS["tenant"],
                func.lower(models.User.email) == email,
            )
        ):
            raise api_error(409, "ACCOUNT_ALREADY_EXISTS", "Account already exists")
        tenant = db.get(models.Tenant, DEV_IDS["tenant"])
        course = db.get(models.Course, DEV_IDS["course"])
        if tenant is None or course is None:
            raise api_error(500, "AUTH_BOOTSTRAP_MISSING", "Local auth bootstrap data is missing")
        user = models.User(
            id=new_id("user"),
            tenant_id=tenant.id,
            oidc_subject=f"local:{email}",
            display_name=display_name,
            email=email,
            password_hash=hash_password(body.password),
            created_at=datetime.now(timezone.utc),
        )
        course_role = body.role
        db.add_all(
            [
                user,
                models.CourseMember(course_id=course.id, user_id=user.id, role=course_role),
            ]
        )
        db.flush()
        roles = _global_roles_from_course_roles([course_role])
        token, expires_at = create_local_auth_token(
            settings,
            subject=user.oidc_subject,
            tenant_id=user.tenant_id,
            roles=roles,
        )
        _audit(
            db,
            Principal(user.tenant_id, user.id, user.oidc_subject, frozenset(roles)),
            "auth.register",
            "user",
            user.id,
            "ALLOW",
        )
        return _auth_token_response(db, user, roles, token, expires_at)

    @app.post("/api/v1/auth/login", response_model=AuthTokenResponse)
    def login_local_account(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
        _require_local_auth_enabled(settings)
        email = _normalize_email(body.email)
        user = db.scalar(
            select(models.User).where(
                models.User.tenant_id == DEV_IDS["tenant"],
                func.lower(models.User.email) == email,
                models.User.status == "ACTIVE",
            )
        )
        if user is None or not verify_password(body.password, user.password_hash):
            raise api_error(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
        memberships = db.scalars(
            select(models.CourseMember).where(models.CourseMember.user_id == user.id)
        ).all()
        roles = _global_roles_from_course_roles([membership.role for membership in memberships])
        user.last_login_at = datetime.now(timezone.utc)
        token, expires_at = create_local_auth_token(
            settings,
            subject=user.oidc_subject,
            tenant_id=user.tenant_id,
            roles=roles,
        )
        _audit(
            db,
            Principal(user.tenant_id, user.id, user.oidc_subject, frozenset(roles)),
            "auth.login",
            "user",
            user.id,
            "ALLOW",
        )
        return _auth_token_response(db, user, roles, token, expires_at)

    @app.get("/api/v1/me")
    def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
        user = db.get(models.User, principal.user_id)
        memberships = db.scalars(
            select(models.CourseMember).where(models.CourseMember.user_id == principal.user_id)
        ).all()
        return {
            "tenantId": principal.tenant_id,
            "userId": principal.user_id,
            "displayName": user.display_name if user else principal.oidc_subject,
            "roles": sorted(principal.roles),
            "courseRoles": [
                {"courseId": membership.course_id, "role": membership.role}
                for membership in memberships
            ],
        }

    @app.post("/api/v1/courses", response_model=CourseView, status_code=201)
    def create_course(
        body: CreateCourseRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not idempotency_key:
            raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
        if not ({"teacher", "admin"} & set(principal.roles)):
            raise api_error(403, "FORBIDDEN_SCOPE", "Only teachers or admins can create courses")
        route = "POST /api/v1/courses"
        existing = _idempotent_response(db, principal, route, idempotency_key)
        if existing is not None:
            return existing
        duplicate = db.scalar(
            select(models.Course).where(
                models.Course.tenant_id == principal.tenant_id,
                models.Course.code == body.code,
                models.Course.term == body.term,
            )
        )
        if duplicate is not None:
            raise api_error(409, "COURSE_ALREADY_EXISTS", "Course code already exists for term")
        course = models.Course(
            id=new_id("course"),
            tenant_id=principal.tenant_id,
            code=body.code,
            title=body.title,
            term=body.term,
            status="ACTIVE",
            owner_id=principal.user_id,
        )
        db.add_all(
            [
                course,
                models.CourseMember(course_id=course.id, user_id=principal.user_id, role="TEACHER"),
            ]
        )
        response = _course_view(course)
        _remember_idempotent_response(db, principal, route, idempotency_key, response)
        _audit(db, principal, "course.create", "course", course.id, "ALLOW")
        _outbox(
            db,
            "course",
            course.id,
            "course.created",
            {"courseId": course.id, "ownerId": principal.user_id},
        )
        return response

    @app.put(
        "/api/v1/courses/{course_id}/members/{user_id}",
        response_model=CourseMemberView,
    )
    def upsert_course_member(
        course_id: str,
        user_id: str,
        body: UpsertCourseMemberRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        course = db.get(models.Course, course_id)
        if course is None:
            raise api_error(404, "NOT_FOUND", "Course not found")
        if course.tenant_id != principal.tenant_id:
            raise api_error(403, "FORBIDDEN_SCOPE", "Course belongs to another tenant")
        require_course_role(db, principal, course.id, {"TEACHER"})
        user = db.get(models.User, user_id)
        if user is None or user.tenant_id != principal.tenant_id:
            raise api_error(404, "NOT_FOUND", "User not found")
        member = db.get(models.CourseMember, {"course_id": course.id, "user_id": user.id})
        before_role = member.role if member else None
        if member is None:
            member = models.CourseMember(course_id=course.id, user_id=user.id, role=body.role)
            db.add(member)
        else:
            member.role = body.role
        _audit(
            db,
            principal,
            "course.member.upsert",
            "course_member",
            f"{course.id}:{user.id}",
            "ALLOW",
            before_ref=before_role,
            after_ref=body.role,
        )
        _outbox(
            db,
            "course",
            course.id,
            "course.member.upserted",
            {"courseId": course.id, "userId": user.id, "role": body.role},
        )
        return _course_member_view(member)

    @app.get("/api/v1/challenge-registry", response_model=ChallengeRegistryListView)
    def challenge_registry(
        query: str = "",
        status: str | None = None,
        limit: int = 50,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not ({"teacher", "admin"} & set(principal.roles)):
            raise api_error(403, "FORBIDDEN_SCOPE", "Only teachers or admins can read registry")
        result = list_challenge_registry(
            db,
            tenant_id=principal.tenant_id,
            query=query,
            status=status,
            limit=max(1, min(100, limit)),
        )
        _audit(db, principal, "challenge.registry.read", "challenge_registry", "global", "ALLOW")
        return result

    @app.post(
        "/api/v1/challenge-registry/import-local",
        response_model=ChallengeImportView,
        status_code=202,
    )
    def import_challenge_registry(
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not ({"teacher", "admin"} & set(principal.roles)):
            raise api_error(403, "FORBIDDEN_SCOPE", "Only teachers or admins can import challenges")
        result = import_local_challenge_packages(
            db,
            settings,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
        )
        _audit(
            db,
            principal,
            "challenge.registry.import_local",
            "challenge_registry",
            "content/challenges",
            "ALLOW",
            after_ref=f"imported={len(result['imported'])} skipped={len(result['skipped'])}",
        )
        _outbox(
            db,
            "challenge_registry",
            principal.tenant_id,
            "challenge.registry.imported",
            {"imported": len(result["imported"]), "skipped": len(result["skipped"])},
        )
        return result

    @app.post(
        "/api/v1/challenge-registry/import-blueprints",
        response_model=ChallengeImportView,
        status_code=202,
    )
    def import_blueprint_registry(
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not ({"teacher", "admin"} & set(principal.roles)):
            raise api_error(403, "FORBIDDEN_SCOPE", "Only teachers or admins can import blueprints")
        result = import_authoritative_blueprints(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
        )
        _audit(
            db,
            principal,
            "challenge.registry.import_blueprints",
            "challenge_registry",
            "content/challenge-blueprints/authoritative-catalog.yaml",
            "ALLOW",
            after_ref=f"imported={len(result['imported'])} skipped={len(result['skipped'])}",
        )
        _outbox(
            db,
            "challenge_registry",
            principal.tenant_id,
            "challenge.registry.blueprints_imported",
            {
                "imported": len(result["imported"]),
                "skipped": len(result["skipped"]),
                "summary": result.get("summary", {}),
            },
        )
        return result

    @app.post(
        "/api/v1/challenge-drafts",
        response_model=ChallengeDraftView,
        status_code=201,
    )
    def create_challenge_draft(
        body: CreateChallengeDraftRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not idempotency_key:
            raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
        course = db.get(models.Course, body.courseId)
        if course is None:
            raise api_error(404, "NOT_FOUND", "Course not found")
        if course.tenant_id != principal.tenant_id:
            raise api_error(403, "FORBIDDEN_SCOPE", "Course belongs to another tenant")
        require_course_role(db, principal, course.id, {"TEACHER", "TA"})
        route = "POST /api/v1/challenge-drafts"
        existing = db.scalar(
            select(models.IdempotencyRecord).where(
                models.IdempotencyRecord.tenant_id == principal.tenant_id,
                models.IdempotencyRecord.actor_id == principal.user_id,
                models.IdempotencyRecord.route == route,
                models.IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing.response_json
        intent = parse_course_intent_for_draft(
            db,
            settings,
            tenant_id=principal.tenant_id,
            brief=body.brief,
            constraints=body.constraints,
            input_ref=f"course:{course.id}:brief:{idempotency_key}",
        )
        draft = models.ChallengeDraft(
            id=new_id("draft"),
            tenant_id=principal.tenant_id,
            course_id=course.id,
            brief_text=body.brief,
            constraints_json=body.constraints,
            intent_json=intent,
            status="PARSED",
            created_by=principal.user_id,
        )
        db.add(draft)
        response = _challenge_draft_view(draft)
        db.add(
            models.IdempotencyRecord(
                id=new_id("idem"),
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                route=route,
                idempotency_key=idempotency_key,
                response_json=response,
            )
        )
        _audit(db, principal, "challenge.draft.create", "challenge_draft", draft.id, "ALLOW")
        _outbox(
            db,
            "challenge_draft",
            draft.id,
            "challenge.draft.created",
            {"draftId": draft.id, "courseId": draft.course_id, "intent": intent},
        )
        return response

    @app.get(
        "/api/v1/challenge-drafts/{draft_id}/candidates",
        response_model=ChallengeCandidateSearchView,
    )
    def challenge_draft_candidates(
        draft_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        draft = _get_challenge_draft_or_404(db, draft_id)
        _require_challenge_draft_teacher(db, principal, draft)
        result = search_challenge_candidates(db, draft)
        _audit(
            db,
            principal,
            "challenge.draft.candidates.read",
            "challenge_draft",
            draft.id,
            "ALLOW",
        )
        return {
            "draftId": draft.id,
            "status": draft.status,
            "courseIntent": draft.intent_json,
            **result,
        }

    @app.post(
        "/api/v1/challenge-drafts/{draft_id}/generate-version",
        response_model=ChallengeGeneratedVersionView,
    )
    def generate_challenge_version(
        draft_id: str,
        body: GenerateChallengeVersionRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        draft = _get_challenge_draft_or_404(db, draft_id)
        _require_challenge_draft_teacher(db, principal, draft)
        if draft.selected_version_id is not None:
            version = db.get(models.ChallengeVersion, draft.selected_version_id)
            if version is None:
                raise api_error(404, "NOT_FOUND", "Generated ChallengeVersion not found")
            validation_run = _latest_validation_run(db, version.id)
            if validation_run is None:
                raise api_error(404, "NOT_FOUND", "Validation report not found")
            model_draft = version.manifest_json.get("authoring", {}).get("modelDraft", {})
            generated_by = version.manifest_json.get("authoring", {}).get("generatedBy", "unknown")
            return {
                **_challenge_materialize_view(
                    draft,
                    body.selectedCandidateId,
                    version,
                    validation_run,
                ),
                "generatedBy": generated_by,
                "modelDraft": model_draft,
            }
        try:
            version, validation_run, model_payload = generate_model_assisted_version(
                db,
                settings,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                draft=draft,
                selected_candidate_id=body.selectedCandidateId,
            )
        except KeyError as exc:
            raise api_error(404, "NOT_FOUND", "Candidate not found") from exc
        except ValueError as exc:
            try:
                details = json.loads(str(exc))
            except json.JSONDecodeError:
                details = {}
            raise api_error(
                422,
                "AUTHORING_HARD_CONSTRAINT_CONFLICT",
                "Selected candidate violates hard constraints",
                details,
            ) from exc
        _audit(
            db,
            principal,
            "challenge.draft.generate_version",
            "challenge_draft",
            draft.id,
            "ALLOW",
            before_ref=body.selectedCandidateId,
            after_ref=version.id,
        )
        _outbox(
            db,
            "challenge_version",
            version.id,
            "challenge.version.generated",
            {
                "draftId": draft.id,
                "sourceCandidateId": body.selectedCandidateId,
                "challengeVersionId": version.id,
                "generatedBy": model_payload["generatedBy"],
            },
        )
        return {
            **_challenge_materialize_view(
                draft,
                body.selectedCandidateId,
                version,
                validation_run,
            ),
            "generatedBy": model_payload["generatedBy"],
            "modelDraft": model_payload["draft"],
        }

    @app.post(
        "/api/v1/challenge-drafts/{draft_id}/generate-custom-package",
        response_model=ChallengeGeneratedVersionView,
    )
    def generate_custom_challenge_version(
        draft_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        draft = _get_challenge_draft_or_404(db, draft_id)
        _require_challenge_draft_teacher(db, principal, draft)
        existing_selection = draft.constraints_json.get("selectedCandidateId")
        if draft.selected_version_id is not None:
            if existing_selection and existing_selection != CUSTOM_CANDIDATE_ID:
                raise api_error(
                    409,
                    "DRAFT_ALREADY_GENERATED",
                    "Challenge draft has already been generated with another candidate",
                )
            version = db.get(models.ChallengeVersion, draft.selected_version_id)
            if version is None:
                raise api_error(404, "NOT_FOUND", "Generated ChallengeVersion not found")
            validation_run = _latest_validation_run(db, version.id)
            if validation_run is None:
                raise api_error(404, "NOT_FOUND", "Validation report not found")
            model_draft = version.manifest_json.get("authoring", {})
            return {
                **_challenge_materialize_view(draft, CUSTOM_CANDIDATE_ID, version, validation_run),
                "generatedBy": model_draft.get("generatedBy", "agent-scaffold"),
                "modelDraft": model_draft,
            }
        version, validation_run, payload = generate_custom_challenge_package(
            db,
            settings,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            draft=draft,
        )
        _audit(
            db,
            principal,
            "challenge.draft.generate_custom_package",
            "challenge_draft",
            draft.id,
            "ALLOW",
            before_ref=CUSTOM_CANDIDATE_ID,
            after_ref=version.id,
        )
        _outbox(
            db,
            "challenge_version",
            version.id,
            "challenge.version.custom_package_generated",
            {
                "draftId": draft.id,
                "sourceCandidateId": CUSTOM_CANDIDATE_ID,
                "challengeVersionId": version.id,
                "generatedBy": payload["generatedBy"],
            },
        )
        return {
            **_challenge_materialize_view(draft, CUSTOM_CANDIDATE_ID, version, validation_run),
            "generatedBy": payload["generatedBy"],
            "modelDraft": payload["draft"],
        }

    @app.post(
        "/api/v1/challenge-drafts/{draft_id}/materialize",
        response_model=ChallengeMaterializeView,
    )
    def materialize_challenge_draft(
        draft_id: str,
        body: MaterializeChallengeDraftRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        draft = _get_challenge_draft_or_404(db, draft_id)
        _require_challenge_draft_teacher(db, principal, draft)
        existing_selection = draft.constraints_json.get("selectedCandidateId")
        if draft.selected_version_id is not None:
            if existing_selection and existing_selection != body.selectedCandidateId:
                raise api_error(
                    409,
                    "DRAFT_ALREADY_MATERIALIZED",
                    "Challenge draft has already been materialized with another candidate",
                )
            version = db.get(models.ChallengeVersion, draft.selected_version_id)
            if version is None:
                raise api_error(404, "NOT_FOUND", "Materialized ChallengeVersion not found")
            validation_run = _latest_validation_run(db, version.id)
            if validation_run is None:
                raise api_error(404, "NOT_FOUND", "Validation report not found")
            return _challenge_materialize_view(draft, body.selectedCandidateId, version, validation_run)

        candidate_result = search_challenge_candidates(db, draft)
        candidates = {candidate["candidateId"]: candidate for candidate in candidate_result["candidates"]}
        rejected = {
            candidate["candidateId"]: candidate
            for candidate in candidate_result["rejectedCandidates"]
        }
        if body.selectedCandidateId in rejected:
            raise api_error(
                422,
                "AUTHORING_HARD_CONSTRAINT_CONFLICT",
                "Selected candidate violates hard constraints",
                {"conflicts": rejected[body.selectedCandidateId]["conflicts"]},
            )
        if body.selectedCandidateId not in candidates:
            raise api_error(404, "NOT_FOUND", "Candidate not found")

        source_version = db.get(models.ChallengeVersion, body.selectedCandidateId)
        if source_version is None:
            raise api_error(404, "NOT_FOUND", "Candidate ChallengeVersion not found")
        source_challenge = db.get(models.Challenge, source_version.challenge_id)
        if source_challenge is None:
            raise api_error(404, "NOT_FOUND", "Candidate Challenge not found")
        report = validate_selected_challenge_package()
        if str(report.get("overallStatus")) == "BLOCK":
            raise api_error(
                409,
                "VALIDATION_NOT_PASSING",
                "Challenge package validation has blocking failures",
                {"summary": report.get("summary", {})},
            )
        version = models.ChallengeVersion(
            id=new_id("cv"),
            challenge_id=source_challenge.id,
            semver=_materialized_semver(source_version.semver, draft.id),
            status="PENDING_APPROVAL",
            manifest_json=challenge_manifest(source_version, source_challenge),
            artifact_digest=source_version.artifact_digest,
            risk_tier=source_version.risk_tier,
            created_by=principal.user_id,
        )
        validation_run = models.ValidationRun(
            id=new_id("vr"),
            version_id=version.id,
            workflow_id=f"publish/{draft.id}/validate",
            status=str(report.get("overallStatus", "PASS")),
            report_ref=DEFAULT_VALIDATION_REPORT_REF,
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )
        draft.status = "MATERIALIZED"
        draft.selected_version_id = version.id
        constraints = dict(draft.constraints_json)
        constraints["selectedCandidateId"] = body.selectedCandidateId
        draft.constraints_json = constraints
        db.add_all([version, validation_run])
        _audit(
            db,
            principal,
            "challenge.draft.materialize",
            "challenge_draft",
            draft.id,
            "ALLOW",
            before_ref=body.selectedCandidateId,
            after_ref=version.id,
        )
        _outbox(
            db,
            "challenge_version",
            version.id,
            "challenge.version.materialized",
            {
                "draftId": draft.id,
                "sourceCandidateId": body.selectedCandidateId,
                "challengeVersionId": version.id,
                "validationRunId": validation_run.id,
            },
        )
        return _challenge_materialize_view(draft, body.selectedCandidateId, version, validation_run)

    @app.post("/api/v1/assignments", response_model=AssignmentView, status_code=201)
    def create_assignment(
        body: CreateAssignmentRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not idempotency_key:
            raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
        route = "POST /api/v1/assignments"
        existing = _idempotent_response(db, principal, route, idempotency_key)
        if existing is not None:
            return existing
        course = db.get(models.Course, body.courseId)
        if course is None:
            raise api_error(404, "NOT_FOUND", "Course not found")
        if course.tenant_id != principal.tenant_id:
            raise api_error(403, "FORBIDDEN_SCOPE", "Course belongs to another tenant")
        require_course_role(db, principal, course.id, {"TEACHER", "TA"})
        challenge_version = db.get(models.ChallengeVersion, body.challengeVersionId)
        if challenge_version is None:
            raise api_error(404, "NOT_FOUND", "ChallengeVersion not found")
        challenge = db.get(models.Challenge, challenge_version.challenge_id)
        if challenge is None:
            raise api_error(404, "NOT_FOUND", "Challenge not found")
        if challenge.tenant_id != principal.tenant_id:
            raise api_error(403, "FORBIDDEN_SCOPE", "ChallengeVersion belongs to another tenant")
        if challenge_version.status != "PUBLISHED":
            raise api_error(
                409,
                "CHALLENGE_VERSION_NOT_PUBLISHED",
                "Assignments must reference a published ChallengeVersion",
            )
        assignment = models.Assignment(
            id=new_id("asg"),
            course_id=course.id,
            challenge_version_id=challenge_version.id,
            title=body.title,
            open_at=body.openAt or datetime.now(timezone.utc),
            due_at=body.dueAt,
            attempt_policy_json=body.attemptPolicy or {"maxAttempts": 1, "maxResets": 2},
        )
        db.add(assignment)
        response = _assignment_view(assignment)
        _remember_idempotent_response(db, principal, route, idempotency_key, response)
        _audit(db, principal, "assignment.create", "assignment", assignment.id, "ALLOW")
        _outbox(
            db,
            "assignment",
            assignment.id,
            "assignment.opened",
            {
                "assignmentId": assignment.id,
                "courseId": assignment.course_id,
                "challengeVersionId": assignment.challenge_version_id,
            },
        )
        return response

    @app.get("/api/v1/assignments/{assignment_id}/live", response_model=AssignmentLiveView)
    def assignment_live(
        assignment_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        assignment = db.get(models.Assignment, assignment_id)
        if assignment is None:
            raise api_error(404, "NOT_FOUND", "Assignment not found")
        require_course_role(db, principal, assignment.course_id, {"TEACHER", "TA"})
        view = _assignment_live_view(db, assignment)
        _audit(db, principal, "assignment.live.read", "assignment", assignment.id, "ALLOW")
        return view

    @app.get(
        "/api/v1/challenge-versions/{version_id}/validation",
        response_model=ChallengeValidationView,
    )
    def challenge_validation(
        version_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        version = db.get(models.ChallengeVersion, version_id)
        if version is None:
            raise api_error(404, "NOT_FOUND", "ChallengeVersion not found")
        _require_challenge_version_teacher(db, principal, version)
        validation_run = _latest_validation_run(db, version.id)
        if validation_run is None:
            raise api_error(404, "NOT_FOUND", "Validation report not found")
        report = _load_validation_report(validation_run.report_ref)
        _audit(
            db,
            principal,
            "challenge.validation.read",
            "challenge_version",
            version.id,
            "ALLOW",
        )
        return _challenge_validation_view(version, validation_run, report)

    @app.post(
        "/api/v1/challenge-versions/{version_id}/approve",
        response_model=ChallengeApprovalView,
    )
    def approve_challenge_version(
        version_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        version = db.get(models.ChallengeVersion, version_id)
        if version is None:
            raise api_error(404, "NOT_FOUND", "ChallengeVersion not found")
        _require_challenge_version_teacher(db, principal, version)
        validation_run = _latest_validation_run(db, version.id)
        if validation_run is None:
            raise api_error(
                409,
                "VALIDATION_REPORT_REQUIRED",
                "ChallengeVersion cannot be published without a validation run",
            )
        report = _load_validation_report(validation_run.report_ref)
        overall_status = _require_publishable_validation(validation_run, report)
        already_published = version.status == "PUBLISHED"
        if version.status in {"ARCHIVED", "REVOKED"}:
            raise api_error(
                409,
                "CHALLENGE_VERSION_NOT_PUBLISHABLE",
                "Archived or revoked ChallengeVersions cannot be published",
            )
        before_status = version.status
        if not already_published:
            version.status = "PUBLISHED"
            _outbox(
                db,
                "challenge_version",
                version.id,
                "challenge.version.published",
                {
                    "challengeVersionId": version.id,
                    "challengeId": version.challenge_id,
                    "semver": version.semver,
                    "validationRunId": validation_run.id,
                    "approvedBy": principal.user_id,
                    "overallStatus": overall_status,
                },
            )
        _audit(
            db,
            principal,
            "challenge.version.approve",
            "challenge_version",
            version.id,
            "ALLOW",
            before_ref=before_status,
            after_ref=version.status,
        )
        return _challenge_approval_view(
            version,
            validation_run,
            overall_status=overall_status,
            already_published=already_published,
        )

    @app.get(
        "/api/v1/teacher/challenge-bank",
        response_model=ChallengeBankListView,
    )
    def teacher_challenge_bank(
        courseId: str | None = None,
        status: str | None = None,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        query = (
            select(models.ChallengeBankItem)
            .where(models.ChallengeBankItem.tenant_id == principal.tenant_id)
            .where(models.ChallengeBankItem.status != "DELETED")
            .order_by(
                models.ChallengeBankItem.updated_at.desc(),
                models.ChallengeBankItem.id.desc(),
            )
        )
        if courseId:
            course = _get_course_or_404(db, courseId)
            _require_course_same_tenant(principal, course)
            require_course_role(db, principal, course.id, {"TEACHER", "TA"})
            query = query.where(models.ChallengeBankItem.course_id == course.id)
        else:
            _require_global_teacher(principal)
        if status:
            query = query.where(models.ChallengeBankItem.status == status)
        items = db.scalars(query).all()
        visible_items = [
            item
            for item in items
            if courseId or _has_course_role(db, principal, item.course_id, {"TEACHER", "TA"})
        ]
        _audit(
            db,
            principal,
            "challenge_bank.read",
            "challenge_bank",
            courseId or "all",
            "ALLOW",
        )
        return {
            "courseId": courseId,
            "count": len(visible_items),
            "items": [_challenge_bank_item_view(db, item) for item in visible_items],
        }

    @app.get(
        "/api/v1/teacher/challenge-bank/trash",
        response_model=ChallengeBankListView,
    )
    def teacher_challenge_bank_trash(
        courseId: str | None = None,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        query = (
            select(models.ChallengeBankItem)
            .where(models.ChallengeBankItem.tenant_id == principal.tenant_id)
            .where(models.ChallengeBankItem.status == "DELETED")
            .order_by(
                models.ChallengeBankItem.deleted_at.desc(),
                models.ChallengeBankItem.id.desc(),
            )
        )
        if courseId:
            course = _get_course_or_404(db, courseId)
            _require_course_same_tenant(principal, course)
            require_course_role(db, principal, course.id, {"TEACHER", "TA"})
            query = query.where(models.ChallengeBankItem.course_id == course.id)
        else:
            _require_global_teacher(principal)
        items = db.scalars(query.limit(30)).all()
        visible_items = [
            item
            for item in items
            if courseId or _has_course_role(db, principal, item.course_id, {"TEACHER", "TA"})
        ][:30]
        _audit(
            db,
            principal,
            "challenge_bank.trash.read",
            "challenge_bank",
            courseId or "all",
            "ALLOW",
        )
        return {
            "courseId": courseId,
            "count": len(visible_items),
            "items": [_challenge_bank_item_view(db, item) for item in visible_items],
        }

    @app.post(
        "/api/v1/teacher/challenge-bank",
        response_model=ChallengeBankItemView,
        status_code=201,
    )
    def create_challenge_bank_item(
        body: CreateChallengeBankItemRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not idempotency_key:
            raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
        route = "POST /api/v1/teacher/challenge-bank"
        existing = _idempotent_response(db, principal, route, idempotency_key)
        if existing is not None:
            return existing
        course = _get_course_or_404(db, body.courseId)
        _require_course_same_tenant(principal, course)
        require_course_role(db, principal, course.id, {"TEACHER", "TA"})
        version = _get_published_challenge_version_or_error(db, principal, body.challengeVersionId)
        item = models.ChallengeBankItem(
            id=new_id("bank"),
            tenant_id=principal.tenant_id,
            course_id=course.id,
            challenge_version_id=version.id,
            assignment_id=None,
            title=body.title,
            summary=body.summary,
            description=body.description,
            requirements=body.requirements,
            status="DRAFT",
            tags_json=_normalized_tags(body.tags),
            created_by=principal.user_id,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(item)
        if body.publish:
            if body.publishWindow is None:
                raise api_error(
                    422,
                    "PUBLISH_WINDOW_REQUIRED",
                    "publishWindow is required when publish=true",
                )
            _publish_challenge_bank_item(db, principal, item, body.publishWindow.openAt, body.publishWindow.dueAt)
        db.flush()
        db.refresh(item)
        response = _challenge_bank_item_view(db, item)
        _remember_idempotent_response(db, principal, route, idempotency_key, response)
        _audit(
            db,
            principal,
            "challenge_bank.create",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            after_ref=item.status,
        )
        _outbox(
            db,
            "challenge_bank_item",
            item.id,
            "challenge_bank.item.created",
            {
                "itemId": item.id,
                "courseId": item.course_id,
                "challengeVersionId": item.challenge_version_id,
                "status": item.status,
            },
        )
        return response

    @app.get(
        "/api/v1/teacher/challenge-bank/{item_id}",
        response_model=ChallengeBankItemView,
    )
    def teacher_challenge_bank_detail(
        item_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_teacher(db, principal, item)
        _audit(db, principal, "challenge_bank.read_detail", "challenge_bank_item", item.id, "ALLOW")
        return _challenge_bank_item_view(db, item)

    @app.patch(
        "/api/v1/teacher/challenge-bank/{item_id}",
        response_model=ChallengeBankItemView,
    )
    def update_challenge_bank_item(
        item_id: str,
        body: UpdateChallengeBankItemRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_teacher(db, principal, item)
        if item.status == "DELETED":
            raise api_error(409, "CHALLENGE_BANK_ITEM_DELETED", "Deleted items must be restored first")
        if item.status == "PUBLISHED":
            raise api_error(
                409,
                "CHALLENGE_BANK_ITEM_PUBLISHED",
                "Published items must be unpublished before editing",
            )
        before_ref = item.status
        if body.title is not None:
            item.title = body.title
        if body.summary is not None:
            item.summary = body.summary
        if body.description is not None:
            item.description = body.description
        if body.requirements is not None:
            item.requirements = body.requirements
        if body.tags is not None:
            item.tags_json = _normalized_tags(body.tags)
        item.updated_at = datetime.now(timezone.utc)
        _audit(
            db,
            principal,
            "challenge_bank.update",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            before_ref=before_ref,
            after_ref=item.status,
        )
        return _challenge_bank_item_view(db, item)

    @app.post(
        "/api/v1/teacher/challenge-bank/{item_id}/publish",
        response_model=ChallengeBankItemView,
    )
    def publish_challenge_bank_item(
        item_id: str,
        body: PublishChallengeBankItemRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_teacher(db, principal, item)
        if item.status == "DELETED":
            raise api_error(409, "CHALLENGE_BANK_ITEM_DELETED", "Deleted items must be restored first")
        before_ref = item.status
        _publish_challenge_bank_item(db, principal, item, body.openAt, body.dueAt)
        _audit(
            db,
            principal,
            "challenge_bank.publish",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            before_ref=before_ref,
            after_ref=item.status,
        )
        _outbox(
            db,
            "challenge_bank_item",
            item.id,
            "challenge_bank.item.published",
            {
                "itemId": item.id,
                "assignmentId": item.assignment_id,
                "openAt": item.open_at.isoformat() if item.open_at else None,
                "dueAt": item.due_at.isoformat() if item.due_at else None,
            },
        )
        return _challenge_bank_item_view(db, item)

    @app.post(
        "/api/v1/teacher/challenge-bank/{item_id}/unpublish",
        response_model=ChallengeBankItemView,
    )
    def unpublish_challenge_bank_item(
        item_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_teacher(db, principal, item)
        if item.status == "DELETED":
            raise api_error(409, "CHALLENGE_BANK_ITEM_DELETED", "Deleted items must be restored first")
        before_ref = item.status
        item.status = "UNPUBLISHED"
        item.unpublished_at = datetime.now(timezone.utc)
        item.updated_at = item.unpublished_at
        _audit(
            db,
            principal,
            "challenge_bank.unpublish",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            before_ref=before_ref,
            after_ref=item.status,
        )
        _outbox(
            db,
            "challenge_bank_item",
            item.id,
            "challenge_bank.item.unpublished",
            {"itemId": item.id, "assignmentId": item.assignment_id},
        )
        return _challenge_bank_item_view(db, item)

    @app.delete(
        "/api/v1/teacher/challenge-bank/{item_id}",
        response_model=ChallengeBankItemView,
    )
    def delete_challenge_bank_item(
        item_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_teacher(db, principal, item)
        if item.status == "PUBLISHED":
            raise api_error(
                409,
                "CHALLENGE_BANK_ITEM_PUBLISHED",
                "Published items must be unpublished before deletion",
            )
        before_ref = item.status
        item.status = "DELETED"
        item.deleted_at = datetime.now(timezone.utc)
        item.updated_at = item.deleted_at
        _audit(
            db,
            principal,
            "challenge_bank.delete",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            before_ref=before_ref,
            after_ref=item.status,
        )
        return _challenge_bank_item_view(db, item)

    @app.post(
        "/api/v1/teacher/challenge-bank/{item_id}/restore",
        response_model=ChallengeBankItemView,
    )
    def restore_challenge_bank_item(
        item_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_teacher(db, principal, item)
        if item.status != "DELETED":
            raise api_error(
                409,
                "CHALLENGE_BANK_ITEM_NOT_DELETED",
                "Only deleted items can be restored",
            )
        item.status = "UNPUBLISHED"
        item.deleted_at = None
        item.restored_at = datetime.now(timezone.utc)
        item.updated_at = item.restored_at
        _audit(
            db,
            principal,
            "challenge_bank.restore",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            before_ref="DELETED",
            after_ref=item.status,
        )
        return _challenge_bank_item_view(db, item)

    @app.get(
        "/api/v1/student/challenge-bank",
        response_model=StudentChallengeBankListView,
    )
    def student_challenge_bank(
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        course_ids = _principal_course_ids(db, principal, {"STUDENT"})
        items = db.scalars(
            select(models.ChallengeBankItem)
            .where(models.ChallengeBankItem.tenant_id == principal.tenant_id)
            .where(models.ChallengeBankItem.course_id.in_(course_ids or [""]))
            .where(models.ChallengeBankItem.status == "PUBLISHED")
            .order_by(models.ChallengeBankItem.open_at.asc(), models.ChallengeBankItem.id.asc())
        ).all()
        _audit(db, principal, "student.challenge_bank.read", "challenge_bank", "mine", "ALLOW")
        return {
            "count": len(items),
            "items": [_student_challenge_bank_item_view(db, settings, principal, item) for item in items],
        }

    @app.get(
        "/api/v1/student/challenge-bank/{item_id}",
        response_model=StudentChallengeBankItemView,
    )
    def student_challenge_bank_detail(
        item_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_student(db, principal, item)
        if item.status != "PUBLISHED":
            raise api_error(404, "NOT_FOUND", "Challenge bank item is not published")
        _audit(db, principal, "student.challenge_bank.read_detail", "challenge_bank_item", item.id, "ALLOW")
        return _student_challenge_bank_item_view(db, settings, principal, item)

    @app.post(
        "/api/v1/student/challenge-bank/{item_id}/start",
        response_model=StartChallengeBankItemView,
        status_code=202,
    )
    def start_challenge_bank_item(
        item_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_student(db, principal, item)
        if _challenge_bank_publish_state(item) != "ACTIVE":
            raise api_error(
                409,
                "CHALLENGE_BANK_ITEM_NOT_ACTIVE",
                "Only active challenge bank items can start a lab environment",
            )
        if item.assignment_id is None:
            raise api_error(
                500,
                "ASSIGNMENT_MISSING",
                "Published challenge bank item is missing its internal assignment",
            )
        assignment = db.get(models.Assignment, item.assignment_id)
        if assignment is None:
            raise api_error(500, "ASSIGNMENT_MISSING", "Challenge bank assignment is missing")
        attempt = db.scalar(
            select(models.Attempt)
            .where(models.Attempt.assignment_id == assignment.id)
            .where(models.Attempt.student_id == principal.user_id)
            .order_by(models.Attempt.number.asc(), models.Attempt.created_at.asc())
            .limit(1)
        )
        reused = attempt is not None
        if attempt is None:
            attempt = models.Attempt(
                id=new_id("a"),
                tenant_id=principal.tenant_id,
                assignment_id=assignment.id,
                student_id=principal.user_id,
                number=1,
                seed_hex=secrets.token_hex(16),
                status="PROVISIONING",
                started_at=datetime.now(timezone.utc),
            )
            db.add(attempt)
            append_event(
                db,
                tenant_id=principal.tenant_id,
                attempt_id=attempt.id,
                session_epoch=1,
                source="cla-api",
                event_type="attempt.created",
                payload={
                    "assignment_id": assignment.id,
                    "challenge_bank_item_id": item.id,
                    "student_id": principal.user_id,
                },
            )
            _outbox(
                db,
                "attempt",
                attempt.id,
                "attempt.created",
                {"attemptId": attempt.id, "challengeBankItemId": item.id},
            )
        lab = _active_lab_session(db, attempt.id)
        if lab is None:
            lab = _create_local_lab_session(db, settings, principal.tenant_id, attempt)
        target_url = _challenge_bank_target_url(settings, item)
        append_event(
            db,
            tenant_id=principal.tenant_id,
            attempt_id=attempt.id,
            session_epoch=lab.epoch,
            source="cla-api",
            event_type="target.access_url.issued",
            payload={
                "challenge_bank_item_id": item.id,
                "target_url_kind": "local-dev",
                "http_observation": "reserved",
            },
        )
        _audit(
            db,
            principal,
            "student.challenge_bank.start",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            after_ref=f"attempt={attempt.id} reused={str(reused).lower()}",
        )
        return {
            "itemId": item.id,
            "assignmentId": assignment.id,
            "attemptId": attempt.id,
            "sessionId": lab.id,
            "sessionEpoch": lab.epoch,
            "sessionStatus": lab.status,
            "targetUrl": target_url,
            "terminalUrl": f"/student/terminal?attemptId={attempt.id}",
            "workspaceUrl": f"/student/terminal?attemptId={attempt.id}",
            "reusedAttempt": reused,
        }

    @app.delete(
        "/api/v1/student/challenge-bank/{item_id}/environment",
        response_model=DestroyChallengeBankItemEnvironmentView,
    )
    def destroy_challenge_bank_environment(
        item_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        item = _get_challenge_bank_item_or_404(db, item_id)
        _require_challenge_bank_student(db, principal, item)
        if item.assignment_id is None:
            raise api_error(404, "CHALLENGE_BANK_ENVIRONMENT_NOT_FOUND", "No lab environment exists")
        assignment = db.get(models.Assignment, item.assignment_id)
        if assignment is None:
            raise api_error(500, "ASSIGNMENT_MISSING", "Challenge bank assignment is missing")
        attempt = db.scalar(
            select(models.Attempt)
            .where(models.Attempt.assignment_id == assignment.id)
            .where(models.Attempt.student_id == principal.user_id)
            .order_by(models.Attempt.number.asc(), models.Attempt.created_at.asc())
            .limit(1)
        )
        if attempt is None:
            raise api_error(404, "CHALLENGE_BANK_ENVIRONMENT_NOT_FOUND", "No lab environment exists")
        lab = _active_lab_session(db, attempt.id)
        if lab is None:
            raise api_error(
                409,
                "CHALLENGE_BANK_ENVIRONMENT_NOT_RUNNING",
                "No running lab environment exists",
            )
        issued = list(
            db.scalars(
                select(models.TerminalTicketNonce)
                .where(models.TerminalTicketNonce.attempt_id == attempt.id)
                .where(models.TerminalTicketNonce.session_id == lab.id)
                .where(models.TerminalTicketNonce.status == "ISSUED")
            )
        )
        for nonce in issued:
            nonce.status = "REVOKED"
        lab.route_endpoint = ""
        lab.status = "DESTROYED"
        attempt.status = "ENVIRONMENT_DESTROYED"
        append_event(
            db,
            tenant_id=principal.tenant_id,
            attempt_id=attempt.id,
            session_epoch=lab.epoch,
            source="cla-api",
            event_type="lab.destroyed",
            payload={
                "challenge_bank_item_id": item.id,
                "session_id": lab.id,
                "revoked_tickets": len(issued),
            },
        )
        _outbox(
            db,
            "lab_session",
            lab.id,
            "lab.destroyed",
            {
                "attemptId": attempt.id,
                "challengeBankItemId": item.id,
                "sessionEpoch": lab.epoch,
            },
        )
        _audit(
            db,
            principal,
            "student.challenge_bank.environment.destroy",
            "challenge_bank_item",
            item.id,
            "ALLOW",
            after_ref=f"attempt={attempt.id} session={lab.id}",
        )
        return {
            "itemId": item.id,
            "assignmentId": assignment.id,
            "attemptId": attempt.id,
            "sessionId": lab.id,
            "sessionEpoch": lab.epoch,
            "sessionStatus": lab.status,
            "destroyed": True,
        }

    @app.post(
        "/api/v1/assignments/{assignment_id}/attempts",
        response_model=AttemptResponse,
        status_code=202,
    )
    def create_attempt(
        assignment_id: str,
        body: CreateAttemptRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        if not idempotency_key:
            raise api_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
        if "TERMINAL" not in body.clientCapabilities.workspaceTypes:
            raise api_error(
                422,
                "WORKSPACE_FEATURE_NOT_ENABLED",
                "Phase one supports only TERMINAL workspace attempts",
            )
        assignment = db.get(models.Assignment, assignment_id)
        if assignment is None:
            raise api_error(404, "NOT_FOUND", "Assignment not found")
        if assignment.course.tenant_id != principal.tenant_id:
            raise api_error(403, "FORBIDDEN_SCOPE", "Assignment belongs to another tenant")
        require_course_role(db, principal, assignment.course_id, {"STUDENT"})
        route = f"POST /api/v1/assignments/{assignment_id}/attempts"
        existing = db.scalar(
            select(models.IdempotencyRecord).where(
                models.IdempotencyRecord.tenant_id == principal.tenant_id,
                models.IdempotencyRecord.actor_id == principal.user_id,
                models.IdempotencyRecord.route == route,
                models.IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing.response_json
        attempt_number = int(
            db.scalar(
                select(func.count(models.Attempt.id)).where(
                    models.Attempt.assignment_id == assignment.id,
                    models.Attempt.student_id == principal.user_id,
                )
            )
            or 0
        ) + 1
        attempt = models.Attempt(
            id=new_id("a"),
            tenant_id=principal.tenant_id,
            assignment_id=assignment.id,
            student_id=principal.user_id,
            number=attempt_number,
            seed_hex=secrets.token_hex(16),
            status="PROVISIONING",
            started_at=datetime.now(timezone.utc),
        )
        db.add(attempt)
        response = {
            "attemptId": attempt.id,
            "status": attempt.status,
            "challengeVersion": "web-sqli-auth-001@1.3.0",
            "workspaceType": "TERMINAL",
            "sessionWorkflowId": f"session/{attempt.id}/1",
            "statusUrl": f"/api/v1/attempts/{attempt.id}",
        }
        db.add(
            models.IdempotencyRecord(
                id=new_id("idem"),
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                route=route,
                idempotency_key=idempotency_key,
                response_json=response,
            )
        )
        append_event(
            db,
            tenant_id=principal.tenant_id,
            attempt_id=attempt.id,
            session_epoch=1,
            source="cla-api",
            event_type="attempt.created",
            payload={"assignment_id": assignment.id, "student_id": principal.user_id},
        )
        _outbox(db, "attempt", attempt.id, "attempt.created", response)
        _audit(db, principal, "attempt.create", "attempt", attempt.id, "ALLOW")
        return response

    @app.get("/api/v1/attempts/{attempt_id}", response_model=AttemptView)
    def get_attempt(
        attempt_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner_or_teacher(db, principal, attempt)
        lab = _active_lab_session(db, attempt.id)
        return _attempt_view(attempt, lab)

    @app.post("/api/v1/attempts/{attempt_id}/sessions", response_model=SessionResponse, status_code=202)
    def ensure_session(
        attempt_id: str,
        body: EnsureSessionRequest | None = None,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        body = body or EnsureSessionRequest()
        if body.workspaceType != "TERMINAL":
            raise api_error(
                422,
                "WORKSPACE_FEATURE_NOT_ENABLED",
                "REMOTE_DESKTOP and SIMULATED are reserved but disabled in phase one",
            )
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner(db, principal, attempt)
        lab = _active_lab_session(db, attempt.id)
        if lab is None:
            lab = _create_local_lab_session(db, settings, principal.tenant_id, attempt)
        return {
            "sessionId": lab.id,
            "sessionEpoch": lab.epoch,
            "status": lab.status,
            "workspaceType": lab.workspace_type,
            "expiresAt": lab.expires_at,
        }

    @app.post(
        "/api/v1/attempts/{attempt_id}/sessions/reset",
        response_model=SessionResponse,
        status_code=202,
    )
    def reset_session(
        attempt_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner(db, principal, attempt)
        old_lab = _active_lab_session(db, attempt.id)
        if old_lab is not None:
            old_lab.status = "RESETTING"
            append_event(
                db,
                tenant_id=principal.tenant_id,
                attempt_id=attempt.id,
                session_epoch=old_lab.epoch,
                source="cla-api",
                event_type="lab.reset.requested",
                payload={"previous_session_id": old_lab.id},
            )
            _outbox(
                db,
                "lab_session",
                old_lab.id,
                "lab.reset.requested",
                {"attemptId": attempt.id, "sessionEpoch": old_lab.epoch},
            )
        lab = _create_local_lab_session(db, settings, principal.tenant_id, attempt)
        _audit(db, principal, "lab_session.reset", "attempt", attempt.id, "ALLOW")
        return {
            "sessionId": lab.id,
            "sessionEpoch": lab.epoch,
            "status": lab.status,
            "workspaceType": lab.workspace_type,
            "expiresAt": lab.expires_at,
        }

    @app.post(
        "/api/v1/attempts/{attempt_id}/terminal-ticket",
        response_model=TerminalTicketResponse,
    )
    def terminal_ticket(
        attempt_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner(db, principal, attempt)
        lab = _active_lab_session(db, attempt.id)
        if lab is None or lab.status not in {"READY", "RUNNING"}:
            raise api_error(409, "LAB_SESSION_NOT_READY", "Lab session is not ready")
        token, expires_at = issue_terminal_ticket(
            db,
            settings,
            principal_user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            attempt=attempt,
            lab_session=lab,
        )
        _audit(db, principal, "terminal.ticket.issue", "attempt", attempt.id, "ALLOW")
        return {
            "sessionId": lab.id,
            "sessionEpoch": lab.epoch,
            "ticket": token,
            "websocketUrl": settings.gateway_url,
            "expiresAt": expires_at,
            "terminal": {"cols": 120, "rows": 32, "encoding": "utf-8"},
            "reconnect": {"supported": True, "bufferSeconds": 60},
            "policies": {"clipboard": "TEXT", "fileTransfer": "CONTROLLED"},
        }

    @app.get("/api/v1/attempts/{attempt_id}/tutor-state", response_model=TutorStateView)
    def tutor_state(
        attempt_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner(db, principal, attempt)
        result = assess_attempt(db, attempt)
        previous_assessment = latest_assessment(db, attempt.id)
        hint = latest_hint(db, attempt.id)
        auto_enabled = not auto_hints_disabled(db, attempt.id)
        should_auto_offer = (
            result.state == "CONFIRMED"
            and previous_assessment is not None
            and previous_assessment.state == "CONFIRMED"
            and auto_enabled
            and not cooldown_active(hint)
        )
        assessment = persist_assessment(
            db,
            attempt,
            result,
            decision="AUTO_OFFERED" if should_auto_offer else "OBSERVE",
        )
        if should_auto_offer:
            hint = create_hint(
                db,
                attempt,
                level="L1",
                trigger_type="AUTO_STUCK",
                assessment=assessment,
                evidence_refs=result.evidence_refs,
            )
            _audit_system(
                db,
                tenant_id=attempt.tenant_id,
                actor="cla-tutor",
                action="hint.auto_offer",
                resource_type="attempt",
                resource_id=attempt.id,
                decision="ALLOW",
            )
        return _tutor_state_view(
            attempt,
            assessment,
            hint,
            auto_enabled=auto_enabled,
            cooldown_hint=hint,
        )

    @app.post("/api/v1/attempts/{attempt_id}/hints/request", response_model=HintView, status_code=201)
    def request_hint(
        attempt_id: str,
        body: HintRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner(db, principal, attempt)
        previous_hint = latest_hint(db, attempt.id)
        if cooldown_active(previous_hint):
            raise api_error(
                409,
                "TUTOR_COOLDOWN",
                "A recent hint is still in cooldown; send feedback before requesting another hint",
                {"hintId": previous_hint.id if previous_hint else None},
            )
        result = assess_attempt(db, attempt, explicit_help=True)
        assessment = persist_assessment(db, attempt, result, decision="SHOW_HINT")
        hint = create_hint(
            db,
            attempt,
            level=body.level,
            trigger_type="ACTIVE_HELP",
            assessment=assessment,
            evidence_refs=result.evidence_refs,
        )
        _audit(db, principal, "hint.request", "attempt", attempt.id, "ALLOW")
        return _hint_view(hint)

    @app.post("/api/v1/hints/{hint_id}/feedback")
    def hint_feedback(
        hint_id: str,
        body: HintFeedbackRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        hint = db.get(models.Hint, hint_id)
        if hint is None:
            raise api_error(404, "NOT_FOUND", "Hint not found")
        attempt = _get_attempt_or_404(db, hint.attempt_id)
        require_attempt_owner(db, principal, attempt)
        hint.status = body.feedback
        append_event(
            db,
            tenant_id=attempt.tenant_id,
            attempt_id=attempt.id,
            session_epoch=latest_session_epoch(db, attempt.id),
            source="cla-tutor",
            event_type="hint.feedback",
            payload={
                "hint_id": hint.id,
                "feedback": body.feedback,
                "tutor_version": hint.tutor_version,
            },
        )
        _audit(db, principal, "hint.feedback", "hint", hint.id, "ALLOW")
        return {"hintId": hint.id, "status": hint.status}

    @app.post("/internal/terminal/tickets/consume")
    def consume_ticket_internal(
        body: ConsumeTicketRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        try:
            claims = consume_terminal_ticket(db, settings, body.ticket)
        except TicketError as exc:
            _audit_ticket_consume_failure(db, body.ticket, exc.code)
            db.commit()
            raise api_error(401, exc.code, exc.message) from exc
        lab = db.get(models.LabSession, claims["session_id"])
        if lab is None or lab.route_ref != claims["route_ref"] or lab.status not in {"READY", "RUNNING"}:
            _audit_system(
                db,
                tenant_id=claims["tenant_id"],
                actor="terminal-gateway",
                action="terminal.ticket.consume",
                resource_type="attempt",
                resource_id=claims["attempt_id"],
                decision="DENY",
            )
            db.commit()
            raise api_error(401, "TERMINAL_TICKET_EXPIRED", "Terminal route binding mismatch")
        _audit_system(
            db,
            tenant_id=claims["tenant_id"],
            actor="terminal-gateway",
            action="terminal.ticket.consume",
            resource_type="attempt",
            resource_id=claims["attempt_id"],
            decision="ALLOW",
        )
        return {
            "tenantId": claims["tenant_id"],
            "attemptId": claims["attempt_id"],
            "sessionId": claims["session_id"],
            "sessionEpoch": claims["session_epoch"],
            "sessionRoute": {
                "routeRef": lab.route_ref,
                "endpoint": lab.route_endpoint,
                "protocol": "tcp-sessionwire",
            },
            "permissions": claims["permissions"],
        }

    @app.post("/internal/attempts/{attempt_id}/sessions/{session_epoch}/route", status_code=202)
    def register_session_route_internal(
        attempt_id: str,
        session_epoch: int,
        body: RouteRegistrationRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        attempt = _get_attempt_or_404(db, attempt_id)
        lab = _lab_session_by_epoch(db, attempt.id, session_epoch)
        if lab is None:
            raise api_error(404, "LAB_SESSION_NOT_FOUND", "Lab session epoch not found")
        if lab.route_ref != body.routeRef:
            raise api_error(409, "LAB_ROUTE_MISMATCH", "Route registration does not match session")
        lab.route_endpoint = body.endpoint
        lab.status = "READY"
        attempt.status = "READY"
        append_event(
            db,
            tenant_id=attempt.tenant_id,
            attempt_id=attempt.id,
            session_epoch=lab.epoch,
            source="cla-environment-controller",
            event_type="lab.route.registered",
            payload={"protocol": body.protocol, "session_epoch": lab.epoch},
        )
        _audit_system(
            db,
            tenant_id=attempt.tenant_id,
            actor="environment-controller",
            action="lab.route.register",
            resource_type="lab_session",
            resource_id=lab.id,
            decision="ALLOW",
        )
        return {"attemptId": attempt.id, "sessionEpoch": lab.epoch, "status": lab.status}

    @app.post(
        "/internal/attempts/{attempt_id}/sessions/{session_epoch}/route/unregister",
        status_code=202,
    )
    def unregister_session_route_internal(
        attempt_id: str,
        session_epoch: int,
        body: RouteUnregisterRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        attempt = _get_attempt_or_404(db, attempt_id)
        lab = _lab_session_by_epoch(db, attempt.id, session_epoch)
        if lab is None:
            raise api_error(404, "LAB_SESSION_NOT_FOUND", "Lab session epoch not found")
        if lab.route_ref != body.routeRef:
            raise api_error(409, "LAB_ROUTE_MISMATCH", "Route unregistration does not match session")
        lab.route_endpoint = ""
        lab.status = "TERMINATING"
        append_event(
            db,
            tenant_id=attempt.tenant_id,
            attempt_id=attempt.id,
            session_epoch=lab.epoch,
            source="cla-environment-controller",
            event_type="lab.route.unregistered",
            payload={"session_epoch": lab.epoch},
        )
        _audit_system(
            db,
            tenant_id=attempt.tenant_id,
            actor="environment-controller",
            action="lab.route.unregister",
            resource_type="lab_session",
            resource_id=lab.id,
            decision="ALLOW",
        )
        return {"attemptId": attempt.id, "sessionEpoch": lab.epoch, "status": lab.status}

    @app.post(
        "/internal/attempts/{attempt_id}/sessions/{session_epoch}/tickets/revoke",
        status_code=202,
    )
    def revoke_session_tickets_internal(
        attempt_id: str,
        session_epoch: int,
        body: TicketRevokeRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        attempt = _get_attempt_or_404(db, attempt_id)
        lab = _lab_session_by_epoch(db, attempt.id, session_epoch)
        if lab is None:
            raise api_error(404, "LAB_SESSION_NOT_FOUND", "Lab session epoch not found")
        if lab.route_ref != body.routeRef:
            raise api_error(409, "LAB_ROUTE_MISMATCH", "Ticket revocation does not match session")
        issued = list(
            db.scalars(
                select(models.TerminalTicketNonce)
                .where(models.TerminalTicketNonce.attempt_id == attempt.id)
                .where(models.TerminalTicketNonce.session_id == lab.id)
                .where(models.TerminalTicketNonce.status == "ISSUED")
            )
        )
        for nonce in issued:
            nonce.status = "REVOKED"
        append_event(
            db,
            tenant_id=attempt.tenant_id,
            attempt_id=attempt.id,
            session_epoch=lab.epoch,
            source="cla-environment-controller",
            event_type="terminal.tickets.revoked",
            payload={"session_epoch": lab.epoch, "revoked_count": len(issued)},
        )
        _audit_system(
            db,
            tenant_id=attempt.tenant_id,
            actor="environment-controller",
            action="terminal.tickets.revoke",
            resource_type="lab_session",
            resource_id=lab.id,
            decision="ALLOW",
        )
        return {"attemptId": attempt.id, "sessionEpoch": lab.epoch, "revokedCount": len(issued)}

    @app.post("/internal/attempts/{attempt_id}/events", status_code=202)
    def append_internal_events(
        attempt_id: str,
        body: AppendBatchRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        attempt = _get_attempt_or_404(db, attempt_id)
        event_ids: list[str] = []
        for item in body.events:
            event = append_event(
                db,
                tenant_id=attempt.tenant_id,
                attempt_id=attempt.id,
                session_epoch=item.sessionEpoch,
                source=item.source,
                event_type=item.type,
                payload=item.payload,
            )
            event.trace_id = item.traceId
            event_ids.append(event.id)
        _audit_system(
            db,
            tenant_id=attempt.tenant_id,
            actor="internal-event-ingest",
            action="events.append_batch",
            resource_type="attempt",
            resource_id=attempt.id,
            decision="ALLOW",
        )
        return {"attemptId": attempt.id, "eventIds": event_ids}

    @app.post("/internal/attempts/{attempt_id}/transcript-segments", status_code=202)
    def append_transcript_segment(
        attempt_id: str,
        body: TranscriptSegmentRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        if body.seqTo < body.seqFrom:
            raise api_error(422, "INVALID_TRANSCRIPT_RANGE", "seqTo must be greater than seqFrom")
        attempt = _get_attempt_or_404(db, attempt_id)
        segment = models.TranscriptSegment(
            id=new_id("seg"),
            attempt_id=attempt.id,
            epoch=body.sessionEpoch,
            direction=body.direction,
            seq_from=body.seqFrom,
            seq_to=body.seqTo,
            object_ref=body.objectRef,
            sha256=body.sha256,
            redaction_state=body.redactionState,
        )
        db.add(segment)
        _audit_system(
            db,
            tenant_id=attempt.tenant_id,
            actor="transcript-writer",
            action="transcript.segment.index",
            resource_type="attempt",
            resource_id=attempt.id,
            decision="ALLOW",
        )
        return {"segmentId": segment.id, "attemptId": attempt.id}

    @app.post("/internal/attempts/{attempt_id}/transcript-segments/upload", status_code=202)
    def upload_transcript_segment(
        attempt_id: str,
        body: TranscriptSegmentUploadRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        if body.seqTo < body.seqFrom:
            raise api_error(422, "INVALID_TRANSCRIPT_RANGE", "seqTo must be greater than seqFrom")
        try:
            plaintext = decode_segment_base64(body.segmentBase64)
        except Exception as exc:
            raise api_error(422, "INVALID_TRANSCRIPT_SEGMENT", "segmentBase64 is invalid") from exc
        attempt = _get_attempt_or_404(db, attempt_id)
        try:
            stored = store_transcript_object(
                settings,
                tenant_id=attempt.tenant_id,
                attempt_id=attempt.id,
                epoch=body.sessionEpoch,
                direction=body.direction,
                seq_from=body.seqFrom,
                seq_to=body.seqTo,
                plaintext=plaintext,
            )
        except TranscriptObjectStoreError as exc:
            raise api_error(503, exc.code, exc.message) from exc
        segment = models.TranscriptSegment(
            id=new_id("seg"),
            attempt_id=attempt.id,
            epoch=body.sessionEpoch,
            direction=body.direction,
            seq_from=body.seqFrom,
            seq_to=body.seqTo,
            object_ref=stored.object_ref,
            sha256=stored.object_sha256,
            redaction_state="ENCRYPTED",
        )
        db.add(segment)
        _audit_system(
            db,
            tenant_id=attempt.tenant_id,
            actor="transcript-writer",
            action="transcript.segment.upload",
            resource_type="attempt",
            resource_id=attempt.id,
            decision="ALLOW",
        )
        return {
            "segmentId": segment.id,
            "attemptId": attempt.id,
            "objectRef": stored.object_ref,
            "objectSha256": stored.object_sha256,
            "plaintextSha256": stored.plaintext_sha256,
            "byteCount": stored.byte_count,
        }

    @app.post("/internal/attempts/{attempt_id}/transcript-segments/verify-restore")
    def verify_transcript_restore(
        attempt_id: str,
        body: TranscriptRestoreVerifyRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        attempt = _get_attempt_or_404(db, attempt_id)
        query = select(models.TranscriptSegment).where(
            models.TranscriptSegment.attempt_id == attempt.id
        )
        if body.sessionEpoch is not None:
            query = query.where(models.TranscriptSegment.epoch == body.sessionEpoch)
        segments = db.scalars(
            query.order_by(
                models.TranscriptSegment.epoch,
                models.TranscriptSegment.seq_from,
                models.TranscriptSegment.id,
            ).limit(body.limit)
        ).all()

        results: list[dict] = []
        for segment in segments:
            result = {
                "segmentId": segment.id,
                "epoch": segment.epoch,
                "direction": segment.direction,
                "seqFrom": segment.seq_from,
                "seqTo": segment.seq_to,
                "objectRef": segment.object_ref,
                "status": "PASS",
                "code": None,
                "byteCount": None,
            }
            try:
                restored = verify_transcript_object(
                    settings,
                    object_ref=segment.object_ref,
                    expected_object_sha256=segment.sha256,
                    tenant_id=attempt.tenant_id,
                    attempt_id=attempt.id,
                    epoch=segment.epoch,
                    direction=segment.direction,
                    seq_from=segment.seq_from,
                    seq_to=segment.seq_to,
                )
                result["byteCount"] = restored.byte_count
            except TranscriptRestoreError as exc:
                result["status"] = "FAIL"
                result["code"] = exc.code
            results.append(result)

        failed = sum(1 for item in results if item["status"] != "PASS")
        _audit_system(
            db,
            tenant_id=attempt.tenant_id,
            actor="transcript-verifier",
            action="transcript.restore.verify",
            resource_type="attempt",
            resource_id=attempt.id,
            decision="ALLOW",
            after_ref=f"checked={len(results)} failed={failed}",
        )
        return {
            "attemptId": attempt.id,
            "checked": len(results),
            "passed": len(results) - failed,
            "failed": failed,
            "restorable": failed == 0,
            "results": results,
        }

    @app.post("/internal/transcript-segments/apply-retention")
    def apply_transcript_retention(
        body: TranscriptRetentionApplyRequest,
        x_cla_service_token: str | None = Header(default=None, alias="X-CLA-Service-Token"),
        db: Session = Depends(get_db),
    ) -> dict:
        _require_internal_service(settings, x_cla_service_token)
        now = datetime.now(timezone.utc)
        segments = db.scalars(
            select(models.TranscriptSegment)
            .order_by(models.TranscriptSegment.created_at, models.TranscriptSegment.id)
            .limit(body.limit * 5)
        ).all()

        results: list[dict] = []
        deleted = 0
        skipped = 0
        failed = 0
        tenant_ids: set[str] = set()
        for segment in segments:
            attempt = db.get(models.Attempt, segment.attempt_id)
            if attempt is not None:
                tenant_ids.add(attempt.tenant_id)
            retention_days, policy_ref = _transcript_retention_policy_for_segment(
                db, segment, override_days=body.olderThanDays
            )
            segment_cutoff = now - timedelta(days=retention_days)
            if _aware_utc(segment.created_at) >= segment_cutoff:
                continue
            if len(results) >= body.limit:
                break
            result = {
                "segmentId": segment.id,
                "attemptId": segment.attempt_id,
                "objectRef": segment.object_ref,
                "retentionDays": retention_days,
                "policyRef": policy_ref,
                "status": "CANDIDATE" if body.dryRun else "DELETED",
                "code": None,
            }
            if body.dryRun:
                skipped += 1
                results.append(result)
                continue
            try:
                delete_status = delete_transcript_object(settings, segment.object_ref)
                result["code"] = delete_status
                db.delete(segment)
                deleted += 1
            except TranscriptObjectDeleteError as exc:
                result["status"] = "SKIPPED" if exc.code == "UNSUPPORTED_OBJECT_REF" else "FAIL"
                result["code"] = exc.code
                if result["status"] == "SKIPPED":
                    skipped += 1
                else:
                    failed += 1
            results.append(result)

        after_ref = (
            f"candidates={len(results)} deleted={deleted} skipped={skipped} "
            f"failed={failed} dryRun={str(body.dryRun).lower()}"
        )
        for tenant_id in sorted(tenant_ids) or [DEV_IDS["tenant"]]:
            _audit_system(
                db,
                tenant_id=tenant_id,
                actor="transcript-retention",
                action="transcript.retention.apply",
                resource_type="transcript_segments",
                resource_id="global",
                decision="ALLOW",
                after_ref=after_ref,
            )
        return {
            "cutoff": (
                (now - timedelta(days=body.olderThanDays)).isoformat()
                if body.olderThanDays is not None
                else None
            ),
            "dryRun": body.dryRun,
            "candidates": len(results),
            "deleted": deleted,
            "skipped": skipped,
            "failed": failed,
            "results": results,
        }

    @app.post("/internal/oracle/attempts/{attempt_id}/observations", status_code=202)
    def observe_oracle(
        attempt_id: str,
        body: OracleObservation,
        x_cla_oracle_signature: str | None = Header(default=None, alias="X-CLA-Oracle-Signature"),
        db: Session = Depends(get_db),
    ) -> dict:
        payload = body.model_dump(by_alias=True)
        if not x_cla_oracle_signature or not verify_oracle_signature(
            settings, payload, x_cla_oracle_signature
        ):
            raise api_error(401, "ORACLE_SIGNATURE_INVALID", "Oracle signature invalid")
        attempt = _get_attempt_or_404(db, attempt_id)
        epoch = latest_session_epoch(db, attempt.id)
        event = append_event(
            db,
            tenant_id=attempt.tenant_id,
            attempt_id=attempt.id,
            session_epoch=epoch,
            source="cla-oracle",
            event_type="oracle.observed",
            payload={
                "oracle_version": body.oracleVersion,
                "passed": body.passed,
                "target_session_key": body.targetSessionKey,
                "evidence": body.evidence,
                "trust": "S4",
            },
        )
        _outbox(db, "attempt", attempt.id, "oracle.observed", {"eventId": event.id})
        return {"eventId": event.id, "passed": body.passed}

    @app.post("/api/v1/attempts/{attempt_id}/submit", response_model=SubmitResponse, status_code=202)
    def submit_attempt(
        attempt_id: str,
        body: SubmitRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner(db, principal, attempt)
        answer_text = "\n\n".join(answer.content for answer in body.answers)
        attempt.status = "SUBMITTED"
        attempt.submitted_at = datetime.now(timezone.utc)
        epoch = latest_session_epoch(db, attempt.id)
        append_event(
            db,
            tenant_id=principal.tenant_id,
            attempt_id=attempt.id,
            session_epoch=epoch,
            source="cla-api",
            event_type="attempt.submitted",
            payload={"answer_refs": ["submission.answer.root-cause"]},
        )
        grade = publish_grade_revision(db, attempt, answer_text)
        _outbox(db, "grade_revision", grade.id, "grade.revision.published", {"attemptId": attempt.id})
        _audit(db, principal, "attempt.submit", "attempt", attempt.id, "ALLOW")
        return {
            "attemptId": attempt.id,
            "status": "SUBMITTED",
            "gradingWorkflowId": f"grade/{attempt.id}/rev-{grade.revision_no}",
        }

    @app.get("/api/v1/attempts/{attempt_id}/grade", response_model=GradeView)
    def get_grade(
        attempt_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> models.GradeRevision:
        attempt = _get_attempt_or_404(db, attempt_id)
        require_attempt_owner_or_teacher(db, principal, attempt)
        grade = db.scalar(
            select(models.GradeRevision)
            .where(models.GradeRevision.attempt_id == attempt.id)
            .order_by(models.GradeRevision.revision_no.desc())
            .limit(1)
        )
        if grade is None:
            raise api_error(404, "NOT_FOUND", "Grade not found")
        return _grade_view(grade)

    @app.post("/api/v1/grades/{grade_revision_id}/appeals", status_code=201)
    def create_appeal(
        grade_revision_id: str,
        body: AppealRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        grade = db.get(models.GradeRevision, grade_revision_id)
        if grade is None:
            raise api_error(404, "NOT_FOUND", "Grade revision not found")
        attempt = _get_attempt_or_404(db, grade.attempt_id)
        require_attempt_owner(db, principal, attempt)
        criterion_exists = any(
            criterion.criterion_id == body.criterionId for criterion in grade.criteria
        )
        if not criterion_exists:
            raise api_error(
                422,
                "GRADE_CRITERION_NOT_FOUND",
                "Appeal must reference a criterion in the grade revision",
            )
        appeal = models.Appeal(
            id=new_id("ap"),
            grade_revision_id=grade.id,
            criterion_id=body.criterionId,
            student_id=principal.user_id,
            reason=body.reason,
            status="OPEN",
        )
        db.add(appeal)
        _audit(db, principal, "appeal.create", "grade_revision", grade.id, "ALLOW")
        return {"appealId": appeal.id, "criterionId": appeal.criterion_id, "status": appeal.status}

    @app.post("/api/v1/appeals/{appeal_id}/resolve")
    def resolve_appeal(
        appeal_id: str,
        body: ResolveAppealRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        appeal = db.get(models.Appeal, appeal_id)
        if appeal is None:
            raise api_error(404, "NOT_FOUND", "Appeal not found")
        if appeal.status != "OPEN":
            raise api_error(409, "APPEAL_NOT_OPEN", "Appeal is not open")
        grade = db.get(models.GradeRevision, appeal.grade_revision_id)
        if grade is None:
            raise api_error(404, "NOT_FOUND", "Grade revision not found")
        attempt = _get_attempt_or_404(db, grade.attempt_id)
        require_course_role(db, principal, attempt.assignment.course_id, {"TEACHER", "TA"})

        new_grade: models.GradeRevision | None = None
        if body.decision == "OVERRIDE_SCORE":
            overrides = {override.criterionId: override for override in body.criterionOverrides}
            if appeal.criterion_id not in overrides:
                raise api_error(
                    422,
                    "APPEAL_CRITERION_OVERRIDE_REQUIRED",
                    "Teacher override must target the appealed criterion",
                )
            existing = {criterion.criterion_id: criterion for criterion in grade.criteria}
            unknown = sorted(set(overrides) - set(existing))
            if unknown:
                raise api_error(
                    422,
                    "GRADE_CRITERION_NOT_FOUND",
                    "Override references a criterion outside the grade revision",
                    {"criterionIds": unknown},
                )
            for criterion_id, override in overrides.items():
                if override.score > existing[criterion_id].max_score:
                    raise api_error(
                        422,
                        "GRADE_SCORE_OUT_OF_RANGE",
                        "Override score exceeds criterion max score",
                        {"criterionId": criterion_id, "maxScore": existing[criterion_id].max_score},
                    )
            new_grade = _copy_grade_with_teacher_overrides(db, grade, appeal, overrides)
            db.add(new_grade)

        appeal.status = "RESOLVED"
        appeal.resolution = body.resolution
        appeal.resolved_by = principal.user_id
        _audit(
            db,
            principal,
            "appeal.resolve",
            "appeal",
            appeal.id,
            "ALLOW",
            before_ref=grade.id,
            after_ref=new_grade.id if new_grade else grade.id,
        )
        return {
            "appealId": appeal.id,
            "status": appeal.status,
            "decision": body.decision,
            "gradeRevisionId": new_grade.id if new_grade else grade.id,
        }

    return app


def _get_attempt_or_404(db: Session, attempt_id: str) -> models.Attempt:
    attempt = db.get(models.Attempt, attempt_id)
    if attempt is None:
        raise api_error(404, "NOT_FOUND", "Attempt not found")
    return attempt


def _idempotent_response(
    db: Session, principal: Principal, route: str, idempotency_key: str
) -> dict | None:
    existing = db.scalar(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.tenant_id == principal.tenant_id,
            models.IdempotencyRecord.actor_id == principal.user_id,
            models.IdempotencyRecord.route == route,
            models.IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    return existing.response_json if existing is not None else None


def _remember_idempotent_response(
    db: Session,
    principal: Principal,
    route: str,
    idempotency_key: str,
    response: dict,
) -> None:
    db.add(
        models.IdempotencyRecord(
            id=new_id("idem"),
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            route=route,
            idempotency_key=idempotency_key,
            response_json=jsonable_encoder(response),
        )
    )


def _course_view(course: models.Course) -> dict:
    return {
        "courseId": course.id,
        "code": course.code,
        "title": course.title,
        "term": course.term,
        "status": course.status,
        "ownerId": course.owner_id,
    }


def _course_member_view(member: models.CourseMember) -> dict:
    return {
        "courseId": member.course_id,
        "userId": member.user_id,
        "role": member.role,
    }


def _assignment_view(assignment: models.Assignment) -> dict:
    return {
        "assignmentId": assignment.id,
        "courseId": assignment.course_id,
        "challengeVersionId": assignment.challenge_version_id,
        "title": assignment.title,
        "openAt": assignment.open_at.isoformat(),
        "dueAt": assignment.due_at.isoformat() if assignment.due_at else None,
        "attemptPolicy": assignment.attempt_policy_json,
    }


def _get_course_or_404(db: Session, course_id: str) -> models.Course:
    course = db.get(models.Course, course_id)
    if course is None:
        raise api_error(404, "NOT_FOUND", "Course not found")
    return course


def _require_course_same_tenant(principal: Principal, course: models.Course) -> None:
    if course.tenant_id != principal.tenant_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "Course belongs to another tenant")


def _require_global_teacher(principal: Principal) -> None:
    if not ({"teacher", "admin"} & set(principal.roles)):
        raise api_error(403, "FORBIDDEN_SCOPE", "Only teachers or admins can manage bank items")


def _has_course_role(
    db: Session, principal: Principal, course_id: str, roles: set[str]
) -> bool:
    member = db.get(models.CourseMember, {"course_id": course_id, "user_id": principal.user_id})
    return member is not None and member.role in roles


def _principal_course_ids(db: Session, principal: Principal, roles: set[str]) -> list[str]:
    members = db.scalars(
        select(models.CourseMember)
        .where(models.CourseMember.user_id == principal.user_id)
        .where(models.CourseMember.role.in_(roles))
    ).all()
    return [member.course_id for member in members]


def _get_challenge_bank_item_or_404(
    db: Session, item_id: str
) -> models.ChallengeBankItem:
    item = db.get(models.ChallengeBankItem, item_id)
    if item is None:
        raise api_error(404, "NOT_FOUND", "Challenge bank item not found")
    return item


def _require_challenge_bank_teacher(
    db: Session, principal: Principal, item: models.ChallengeBankItem
) -> None:
    if item.tenant_id != principal.tenant_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "Challenge bank item belongs to another tenant")
    require_course_role(db, principal, item.course_id, {"TEACHER", "TA"})


def _require_challenge_bank_student(
    db: Session, principal: Principal, item: models.ChallengeBankItem
) -> None:
    if item.tenant_id != principal.tenant_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "Challenge bank item belongs to another tenant")
    require_course_role(db, principal, item.course_id, {"STUDENT"})


def _get_published_challenge_version_or_error(
    db: Session, principal: Principal, version_id: str
) -> models.ChallengeVersion:
    version = db.get(models.ChallengeVersion, version_id)
    if version is None:
        raise api_error(404, "NOT_FOUND", "ChallengeVersion not found")
    challenge = db.get(models.Challenge, version.challenge_id)
    if challenge is None:
        raise api_error(404, "NOT_FOUND", "Challenge not found")
    if challenge.tenant_id != principal.tenant_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "ChallengeVersion belongs to another tenant")
    if version.status != "PUBLISHED":
        raise api_error(
            409,
            "CHALLENGE_VERSION_NOT_PUBLISHED",
            "Bank items must reference a published ChallengeVersion",
        )
    return version


def _validate_publish_window(open_at: datetime, due_at: datetime) -> tuple[datetime, datetime]:
    open_value = _aware_utc(open_at)
    due_value = _aware_utc(due_at)
    if due_value <= open_value:
        raise api_error(
            422,
            "INVALID_PUBLISH_WINDOW",
            "dueAt must be later than openAt",
        )
    return open_value, due_value


def _publish_challenge_bank_item(
    db: Session,
    principal: Principal,
    item: models.ChallengeBankItem,
    open_at: datetime,
    due_at: datetime,
) -> None:
    open_value, due_value = _validate_publish_window(open_at, due_at)
    _get_published_challenge_version_or_error(db, principal, item.challenge_version_id)
    assignment = db.get(models.Assignment, item.assignment_id) if item.assignment_id else None
    if assignment is None:
        assignment = models.Assignment(
            id=new_id("asg"),
            course_id=item.course_id,
            challenge_version_id=item.challenge_version_id,
            title=item.title,
            open_at=open_value,
            due_at=due_value,
            attempt_policy_json={
                "maxAttempts": 1,
                "maxResets": 2,
                "source": "challenge-bank",
            },
        )
        db.add(assignment)
        item.assignment_id = assignment.id
    else:
        assignment.title = item.title
        assignment.open_at = open_value
        assignment.due_at = due_value
        assignment.challenge_version_id = item.challenge_version_id
        assignment.attempt_policy_json = {
            **(assignment.attempt_policy_json or {}),
            "source": "challenge-bank",
            "maxAttempts": 1,
        }
    now = datetime.now(timezone.utc)
    item.status = "PUBLISHED"
    item.open_at = open_value
    item.due_at = due_value
    item.published_at = now
    item.updated_at = now


def _normalized_tags(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value[:40])
        if len(result) >= 20:
            break
    return result


def _challenge_bank_publish_state(item: models.ChallengeBankItem) -> str:
    if item.status == "DELETED":
        return "DELETED"
    if item.status != "PUBLISHED":
        return "UNPUBLISHED"
    now = datetime.now(timezone.utc)
    if item.open_at and now < _aware_utc(item.open_at):
        return "NOT_STARTED"
    if item.due_at and now > _aware_utc(item.due_at):
        return "ENDED"
    return "ACTIVE"


def _challenge_bank_actions(item: models.ChallengeBankItem) -> dict:
    state = _challenge_bank_publish_state(item)
    return {
        "canEdit": item.status in {"DRAFT", "UNPUBLISHED"},
        "canPublish": item.status in {"DRAFT", "UNPUBLISHED"},
        "canUnpublish": item.status == "PUBLISHED",
        "canDelete": item.status in {"DRAFT", "UNPUBLISHED"},
        "canRestore": item.status == "DELETED",
        "canStart": state == "ACTIVE",
    }


def _challenge_bank_version_view(db: Session, version: models.ChallengeVersion) -> dict:
    challenge = db.get(models.Challenge, version.challenge_id)
    if challenge is None:
        raise api_error(404, "NOT_FOUND", "Challenge not found")
    manifest = version.manifest_json or {}
    spec = manifest.get("spec", {}) if isinstance(manifest.get("spec", {}), dict) else {}
    metadata = (
        manifest.get("metadata", {}) if isinstance(manifest.get("metadata", {}), dict) else {}
    )
    workspace = spec.get("workspace", {}) if isinstance(spec.get("workspace", {}), dict) else {}
    validation = _latest_validation_run(db, version.id)
    artifacts = db.scalars(
        select(models.ChallengeArtifact)
        .where(models.ChallengeArtifact.version_id == version.id)
        .order_by(models.ChallengeArtifact.created_at.desc(), models.ChallengeArtifact.id.desc())
    ).all()
    return {
        "challengeId": challenge.id,
        "challengeVersionId": version.id,
        "slug": challenge.slug,
        "title": str(metadata.get("title") or challenge.title),
        "category": challenge.category,
        "semver": version.semver,
        "status": version.status,
        "workspaceType": str(workspace.get("type") or spec.get("workspaceType") or "TERMINAL"),
        "difficulty": int(spec.get("difficulty") or 0),
        "expectedMinutes": int(spec.get("expectedMinutes") or 0),
        "riskTier": version.risk_tier,
        "artifactDigest": version.artifact_digest,
        "validationStatus": validation.status if validation else "UNKNOWN",
        "searchScore": 0.0,
        "created": False,
        "artifactCount": len(artifacts),
        "latestArtifactRef": artifacts[0].object_ref if artifacts else None,
        "approvalUrl": f"/api/v1/challenge-versions/{version.id}/approve",
        "validationUrl": f"/api/v1/challenge-versions/{version.id}/validation",
    }


def _challenge_bank_item_view(db: Session, item: models.ChallengeBankItem) -> dict:
    version = db.get(models.ChallengeVersion, item.challenge_version_id)
    if version is None:
        raise api_error(404, "NOT_FOUND", "ChallengeVersion not found")
    return {
        "itemId": item.id,
        "courseId": item.course_id,
        "challengeVersionId": item.challenge_version_id,
        "assignmentId": item.assignment_id,
        "title": item.title,
        "summary": item.summary,
        "description": item.description,
        "requirements": item.requirements,
        "tags": list(item.tags_json or []),
        "status": item.status,
        "publishState": _challenge_bank_publish_state(item),
        "openAt": item.open_at,
        "dueAt": item.due_at,
        "createdAt": item.created_at,
        "updatedAt": item.updated_at,
        "publishedAt": item.published_at,
        "unpublishedAt": item.unpublished_at,
        "deletedAt": item.deleted_at,
        "restoredAt": item.restored_at,
        "version": _challenge_bank_version_view(db, version),
        "actions": _challenge_bank_actions(item),
    }


def _student_challenge_bank_item_view(
    db: Session,
    settings: Settings,
    principal: Principal,
    item: models.ChallengeBankItem,
) -> dict:
    state = _challenge_bank_publish_state(item)
    disabled_reason = None
    if state == "NOT_STARTED":
        disabled_reason = "题目还未开始"
    elif state == "ENDED":
        disabled_reason = "题目已结束"
    elif state != "ACTIVE":
        disabled_reason = "题目未发布"
    attempt = None
    if item.assignment_id:
        attempt = db.scalar(
            select(models.Attempt)
            .where(models.Attempt.assignment_id == item.assignment_id)
            .where(models.Attempt.student_id == principal.user_id)
            .order_by(models.Attempt.number.asc(), models.Attempt.created_at.asc())
            .limit(1)
        )
    lab = _active_lab_session(db, attempt.id) if attempt else None
    grade = _latest_grade_revision(db, attempt.id) if attempt else None
    completed = grade is not None
    return {
        "itemId": item.id,
        "courseId": item.course_id,
        "title": item.title,
        "summary": item.summary,
        "description": item.description,
        "requirements": item.requirements,
        "tags": list(item.tags_json or []),
        "publishState": state,
        "clickable": state == "ACTIVE",
        "disabledReason": disabled_reason,
        "openAt": item.open_at,
        "dueAt": item.due_at,
        "attemptId": attempt.id if attempt else None,
        "completionStatus": "COMPLETED" if completed else "INCOMPLETE",
        "completed": completed,
        "latestScore": float(grade.total_score) if grade else None,
        "gradeRevisionId": grade.id if grade else None,
        "hasEnvironment": lab is not None,
        "sessionId": lab.id if lab else None,
        "sessionStatus": lab.status if lab else None,
        "targetUrl": _challenge_bank_target_url(settings, item) if lab else None,
        "terminalUrl": f"/student/terminal?attemptId={attempt.id}" if lab and attempt else None,
    }


def _latest_grade_revision(db: Session, attempt_id: str) -> models.GradeRevision | None:
    return db.scalar(
        select(models.GradeRevision)
        .where(models.GradeRevision.attempt_id == attempt_id)
        .order_by(models.GradeRevision.revision_no.desc(), models.GradeRevision.published_at.desc())
        .limit(1)
    )


def _challenge_bank_target_url(settings: Settings, item: models.ChallengeBankItem) -> str:
    base_url = settings.local_target_base_url.rstrip("/")
    return base_url


def _get_challenge_draft_or_404(db: Session, draft_id: str) -> models.ChallengeDraft:
    draft = db.get(models.ChallengeDraft, draft_id)
    if draft is None:
        raise api_error(404, "NOT_FOUND", "Challenge draft not found")
    return draft


def _require_challenge_draft_teacher(
    db: Session, principal: Principal, draft: models.ChallengeDraft
) -> None:
    if draft.tenant_id != principal.tenant_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "Challenge draft belongs to another tenant")
    require_course_role(db, principal, draft.course_id, {"TEACHER", "TA"})


def _require_challenge_version_teacher(
    db: Session, principal: Principal, version: models.ChallengeVersion
) -> None:
    challenge = db.get(models.Challenge, version.challenge_id)
    if challenge is None:
        raise api_error(404, "NOT_FOUND", "Challenge not found")
    if challenge.tenant_id != principal.tenant_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "ChallengeVersion belongs to another tenant")
    assignment = db.scalar(
        select(models.Assignment)
        .where(models.Assignment.challenge_version_id == version.id)
        .order_by(models.Assignment.open_at.desc(), models.Assignment.id.desc())
        .limit(1)
    )
    if assignment is not None:
        require_course_role(db, principal, assignment.course_id, {"TEACHER", "TA"})
        return
    if version.created_by != principal.user_id:
        raise api_error(403, "FORBIDDEN_SCOPE", "User is not allowed for this challenge version")


def _challenge_draft_view(draft: models.ChallengeDraft) -> dict:
    return {
        "draftId": draft.id,
        "status": draft.status,
        "courseId": draft.course_id,
        "courseIntent": draft.intent_json,
        "constraints": draft.constraints_json,
        "candidatesUrl": f"/api/v1/challenge-drafts/{draft.id}/candidates",
    }


def _challenge_materialize_view(
    draft: models.ChallengeDraft,
    source_candidate_id: str,
    version: models.ChallengeVersion,
    validation_run: models.ValidationRun,
) -> dict:
    return {
        "draftId": draft.id,
        "status": draft.status,
        "sourceCandidateId": source_candidate_id,
        "challengeVersionId": version.id,
        "challengeId": version.challenge_id,
        "semver": version.semver,
        "versionStatus": version.status,
        "validationRunId": validation_run.id,
        "validationStatus": validation_run.status,
        "validationReportUrl": f"/api/v1/challenge-versions/{version.id}/validation",
        "approvalRequired": version.status != "PUBLISHED",
    }


def _materialized_semver(source_semver: str, draft_id: str) -> str:
    suffix = draft_id.split("_")[-1][:8]
    return f"{source_semver}+draft.{suffix}"


def _active_lab_session(db: Session, attempt_id: str) -> models.LabSession | None:
    return db.scalar(
        select(models.LabSession)
        .where(models.LabSession.attempt_id == attempt_id)
        .where(models.LabSession.status.in_(["READY", "RUNNING", "PROVISIONING"]))
        .order_by(models.LabSession.epoch.desc())
        .limit(1)
    )


def _lab_session_by_epoch(
    db: Session,
    attempt_id: str,
    session_epoch: int,
) -> models.LabSession | None:
    return db.scalar(
        select(models.LabSession)
        .where(models.LabSession.attempt_id == attempt_id)
        .where(models.LabSession.epoch == session_epoch)
        .limit(1)
    )


def _create_local_lab_session(
    db: Session,
    settings: Settings,
    tenant_id: str,
    attempt: models.Attempt,
) -> models.LabSession:
    epoch = (
        db.scalar(
            select(func.max(models.LabSession.epoch)).where(
                models.LabSession.attempt_id == attempt.id
            )
        )
        or 0
    ) + 1
    lab = models.LabSession(
        id=new_id("ls"),
        attempt_id=attempt.id,
        epoch=int(epoch),
        workspace_type="TERMINAL",
        runtime_tier=1,
        status="READY",
        route_ref=new_id("route"),
        route_endpoint=settings.sessiond_endpoint,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=90),
        workflow_id=f"session/{attempt.id}/{epoch}",
    )
    db.add(lab)
    attempt.status = "READY"
    append_event(
        db,
        tenant_id=tenant_id,
        attempt_id=attempt.id,
        session_epoch=lab.epoch,
        source="cla-api",
        event_type="lab.provisioned",
        payload={"workspace_type": "TERMINAL", "runtime_tier": 1},
    )
    _outbox(db, "lab_session", lab.id, "lab.provisioned", {"attemptId": attempt.id})
    return lab


def _attempt_view(attempt: models.Attempt, lab: models.LabSession | None) -> dict:
    return {
        "attemptId": attempt.id,
        "status": attempt.status,
        "assignmentId": attempt.assignment_id,
        "workspaceType": "TERMINAL",
        "session": None
        if lab is None
        else {
            "sessionId": lab.id,
            "sessionEpoch": lab.epoch,
            "status": lab.status,
            "workspaceType": lab.workspace_type,
            "expiresAt": lab.expires_at.isoformat(),
        },
    }


def _latest_validation_run(db: Session, version_id: str) -> models.ValidationRun | None:
    return db.scalar(
        select(models.ValidationRun)
        .where(models.ValidationRun.version_id == version_id)
        .order_by(models.ValidationRun.started_at.desc(), models.ValidationRun.id.desc())
        .limit(1)
    )


def _load_validation_report(report_ref: str | None) -> dict:
    if not report_ref:
        raise api_error(404, "NOT_FOUND", "Validation report object is missing")
    report_path = (REPO_ROOT / report_ref).resolve()
    if REPO_ROOT not in report_path.parents:
        raise api_error(500, "VALIDATION_REPORT_REF_INVALID", "Validation report ref is invalid")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise api_error(500, "VALIDATION_REPORT_UNAVAILABLE", "Validation report is unavailable") from exc
    if not isinstance(report, dict):
        raise api_error(500, "VALIDATION_REPORT_INVALID", "Validation report is invalid")
    return report


def _validation_summary(report: dict) -> dict:
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        return {"passed": 0, "warnings": 0, "blocked": 0}
    return {
        "passed": int(summary.get("passed", 0)),
        "warnings": int(summary.get("warnings", 0)),
        "blocked": int(summary.get("blocked", 0)),
    }


def _validation_checks(report: dict) -> list[dict]:
    return [
        {
            "id": str(check.get("id", "")),
            "category": str(check.get("category", "")),
            "status": str(check.get("status", "BLOCK")),
            "title": str(check.get("title", "")),
            "evidenceRefs": [str(ref) for ref in check.get("evidenceRefs", [])],
        }
        for check in report.get("checks", [])
        if isinstance(check, dict)
    ]


def _require_publishable_validation(
    validation_run: models.ValidationRun, report: dict
) -> str:
    overall_status = str(report.get("overallStatus", validation_run.status))
    summary = _validation_summary(report)
    checks = _validation_checks(report)
    blocked_checks = [check["id"] for check in checks if check["status"] == "BLOCK"]
    if (
        validation_run.status not in {"PASS", "WARN"}
        or overall_status not in {"PASS", "WARN"}
        or summary["blocked"] > 0
        or blocked_checks
    ):
        raise api_error(
            409,
            "VALIDATION_NOT_PASSING",
            "ChallengeVersion cannot be published while validation has blocking failures",
            {
                "validationRunId": validation_run.id,
                "validationStatus": validation_run.status,
                "overallStatus": overall_status,
                "blockedChecks": blocked_checks,
            },
        )
    return overall_status


def _challenge_validation_view(
    version: models.ChallengeVersion, validation_run: models.ValidationRun, report: dict
) -> dict:
    checks = _validation_checks(report)
    summary = _validation_summary(report)
    return {
        "challengeVersionId": version.id,
        "challengeId": version.challenge_id,
        "semver": version.semver,
        "versionStatus": version.status,
        "artifactDigest": version.artifact_digest,
        "validationRunId": validation_run.id,
        "workflowId": validation_run.workflow_id,
        "status": validation_run.status,
        "reportRef": validation_run.report_ref,
        "startedAt": validation_run.started_at,
        "endedAt": validation_run.ended_at,
        "overallStatus": str(report.get("overallStatus", validation_run.status)),
        "summary": summary,
        "checks": checks,
        "forbiddenDisclosuresChecked": [
            str(item) for item in report.get("forbiddenDisclosuresChecked", [])
        ],
    }


def _challenge_approval_view(
    version: models.ChallengeVersion,
    validation_run: models.ValidationRun,
    *,
    overall_status: str,
    already_published: bool,
) -> dict:
    return {
        "challengeVersionId": version.id,
        "challengeId": version.challenge_id,
        "semver": version.semver,
        "status": version.status,
        "artifactDigest": version.artifact_digest,
        "validationRunId": validation_run.id,
        "validationStatus": validation_run.status,
        "overallStatus": overall_status,
        "published": version.status == "PUBLISHED",
        "alreadyPublished": already_published,
    }


def _assignment_live_view(db: Session, assignment: models.Assignment) -> dict:
    attempts = db.scalars(
        select(models.Attempt)
        .where(models.Attempt.assignment_id == assignment.id)
        .order_by(models.Attempt.created_at.asc(), models.Attempt.id.asc())
    ).all()
    sessions = [_assignment_live_attempt_view(db, assignment, attempt) for attempt in attempts]
    return {
        "assignmentId": assignment.id,
        "title": assignment.title,
        "generatedAt": datetime.now(timezone.utc),
        "summary": {
            "totalAttempts": len(sessions),
            "readySessions": sum(
                1 for session in sessions if session["sessionStatus"] == "READY"
            ),
            "stuckSuspected": sum(
                1
                for session in sessions
                if session["latestAssessment"]
                and session["latestAssessment"]["state"] in {"SUSPECTED", "CONFIRMED"}
            ),
            "resourceAlerts": sum(session["alerts"]["resource"] for session in sessions),
            "securityAlerts": sum(session["alerts"]["security"] for session in sessions),
        },
        "sessions": sessions,
    }


def _assignment_live_attempt_view(
    db: Session, assignment: models.Assignment, attempt: models.Attempt
) -> dict:
    lab = db.scalar(
        select(models.LabSession)
        .where(models.LabSession.attempt_id == attempt.id)
        .order_by(models.LabSession.epoch.desc(), models.LabSession.id.desc())
        .limit(1)
    )
    student = db.get(models.User, attempt.student_id)
    assessment = latest_assessment(db, attempt.id)
    hint = latest_hint(db, attempt.id)
    resource_alerts = int(
        db.scalar(
            select(func.count())
            .select_from(models.Event)
            .where(
                models.Event.attempt_id == attempt.id,
                models.Event.type.like("lab.resource.%"),
            )
        )
        or 0
    )
    security_alerts = int(
        db.scalar(
            select(func.count())
            .select_from(models.Event)
            .where(
                models.Event.attempt_id == attempt.id,
                models.Event.type.in_(SECURITY_ALERT_EVENT_TYPES),
            )
        )
        or 0
    )
    latest_event_at = db.scalar(
        select(func.max(models.Event.occurred_at)).where(models.Event.attempt_id == attempt.id)
    )
    workspace_type = (
        lab.workspace_type
        if lab is not None
        else assignment.challenge_version.manifest_json.get("workspaceType", "TERMINAL")
    )
    return {
        "attemptId": attempt.id,
        "studentId": attempt.student_id,
        "studentDisplayName": student.display_name if student else attempt.student_id,
        "attemptStatus": attempt.status,
        "workspaceType": workspace_type,
        "sessionStatus": lab.status if lab else None,
        "sessionEpoch": lab.epoch if lab else None,
        "sessionExpiresAt": lab.expires_at if lab else None,
        "latestAssessment": _assessment_view(assessment) if assessment else None,
        "latestHint": (
            {"level": hint.level, "status": hint.status, "triggerType": hint.trigger_type}
            if hint
            else None
        ),
        "alerts": {"resource": resource_alerts, "security": security_alerts},
        "latestEventAt": latest_event_at,
    }


def _grade_view(grade: models.GradeRevision) -> dict:
    return {
        "gradeRevisionId": grade.id,
        "attemptId": grade.attempt_id,
        "revisionNo": grade.revision_no,
        "status": grade.status,
        "totalScore": grade.total_score,
        "independenceIndex": grade.independence_index,
        "rubricVersion": grade.rubric_version,
        "graderVersion": grade.grader_version,
        "publishedAt": grade.published_at,
        "criteria": [
            {
                "criterionId": criterion.criterion_id,
                "score": criterion.score,
                "maxScore": criterion.max_score,
                "graderType": criterion.grader_type,
                "confidence": criterion.confidence,
                "explanation": criterion.explanation,
                "evidenceRefs": criterion.evidence_refs,
            }
            for criterion in grade.criteria
        ],
    }


def _tutor_state_view(
    attempt: models.Attempt,
    assessment: models.StuckAssessment,
    hint: models.Hint | None,
    *,
    auto_enabled: bool,
    cooldown_hint: models.Hint | None,
) -> dict:
    return {
        "attemptId": attempt.id,
        "assessment": _assessment_view(assessment),
        "latestHint": _hint_view(hint) if hint else None,
        "autoHintsEnabled": auto_enabled,
        "cooldown": {
            "active": cooldown_active(cooldown_hint),
            "hintId": cooldown_hint.id if cooldown_active(cooldown_hint) else None,
        },
    }


def _assessment_view(assessment: models.StuckAssessment) -> dict:
    features = assessment.features_json or {}
    return {
        "state": assessment.state,
        "score": assessment.score,
        "detectorVersion": assessment.detector_version or DETECTOR_VERSION,
        "featureContributions": features.get("feature_contributions", {}),
        "excludedReasons": features.get("excluded_reasons", []),
        "evidenceRefs": features.get("evidence_refs", []),
    }


def _hint_view(hint: models.Hint) -> dict:
    return {
        "hintId": hint.id,
        "level": hint.level,
        "triggerType": hint.trigger_type,
        "content": hint.content,
        "evidenceRefs": hint.evidence_refs,
        "tutorVersion": hint.tutor_version,
        "shownAt": hint.shown_at,
        "status": hint.status,
    }


def _copy_grade_with_teacher_overrides(
    db: Session,
    grade: models.GradeRevision,
    appeal: models.Appeal,
    overrides: dict[str, CriterionOverrideRequest],
) -> models.GradeRevision:
    latest_revision_no = db.scalar(
        select(func.max(models.GradeRevision.revision_no)).where(
            models.GradeRevision.attempt_id == grade.attempt_id
        )
    )
    revision_no = int(latest_revision_no or grade.revision_no) + 1
    criteria: list[models.CriterionResult] = []
    total_score = 0.0
    for criterion in grade.criteria:
        override = overrides.get(criterion.criterion_id)
        if override is None:
            score = criterion.score
            grader_type = criterion.grader_type
            confidence = criterion.confidence
            explanation = criterion.explanation
            evidence_refs = list(criterion.evidence_refs)
        else:
            score = float(override.score)
            grader_type = "TEACHER_OVERRIDE"
            confidence = 1.0
            explanation = override.explanation
            evidence_refs = list(criterion.evidence_refs) + [f"appeal:{appeal.id}"]
        total_score += score
        criteria.append(
            models.CriterionResult(
                grade_revision_id="",
                criterion_id=criterion.criterion_id,
                score=score,
                max_score=criterion.max_score,
                grader_type=grader_type,
                confidence=confidence,
                explanation=explanation,
                evidence_refs=evidence_refs,
            )
        )
    new_grade = models.GradeRevision(
        id=new_id("gr"),
        attempt_id=grade.attempt_id,
        revision_no=revision_no,
        status="PUBLISHED",
        total_score=total_score,
        independence_index=grade.independence_index,
        rubric_version=grade.rubric_version,
        grader_version="cla-teacher-override/0.1.0",
    )
    for criterion in criteria:
        criterion.grade_revision_id = new_grade.id
    new_grade.criteria = criteria
    return new_grade


def _transcript_retention_policy_for_segment(
    db: Session, segment: models.TranscriptSegment, *, override_days: int | None
) -> tuple[int, str]:
    if override_days is not None:
        return override_days, "request.override"
    attempt = db.get(models.Attempt, segment.attempt_id)
    if attempt is None:
        return DEFAULT_TRANSCRIPT_RETENTION_DAYS, "default"
    assignment = db.get(models.Assignment, attempt.assignment_id)
    if assignment is None:
        return DEFAULT_TRANSCRIPT_RETENTION_DAYS, "default"
    version = db.get(models.ChallengeVersion, assignment.challenge_version_id)
    if version is None:
        return DEFAULT_TRANSCRIPT_RETENTION_DAYS, "default"
    challenge = db.get(models.Challenge, version.challenge_id)
    if challenge is None:
        return DEFAULT_TRANSCRIPT_RETENTION_DAYS, "default"
    manifest = challenge_manifest(version, challenge)
    policy_ref = str(manifest.get("spec", {}).get("retentionPolicyRef") or "")
    if not policy_ref:
        return DEFAULT_TRANSCRIPT_RETENTION_DAYS, "default"
    policy_path = _safe_challenge_policy_path(challenge, manifest, policy_ref)
    if policy_path is None:
        return DEFAULT_TRANSCRIPT_RETENTION_DAYS, "default"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    retention_days = (
        policy.get("terminalTranscript", {}).get("rawSegmentRetentionDays")
        or DEFAULT_TRANSCRIPT_RETENTION_DAYS
    )
    return int(retention_days), policy_ref


def _safe_challenge_policy_path(
    challenge: models.Challenge, manifest: dict, policy_ref: str
) -> Path | None:
    relative = Path(policy_ref)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidates = []
    if challenge.slug == "web-sqli-auth-001":
        candidates.append(DEFAULT_CHALLENGE_DIR / relative)
    manifest_id = manifest.get("metadata", {}).get("id")
    if manifest_id:
        candidates.append(REPO_ROOT / "content" / "challenges" / str(manifest_id) / relative)
    content_root = (REPO_ROOT / "content" / "challenges").resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(content_root) and resolved.exists():
            return resolved
    return None


def _aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_local_auth_enabled(settings: Settings) -> None:
    if not settings.local_auth_enabled:
        raise api_error(403, "LOCAL_AUTH_DISABLED", "Local account login is disabled")


def _normalize_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        return ""
    return value


def _global_roles_from_course_roles(course_roles: list[str]) -> list[str]:
    roles: set[str] = set()
    for role in course_roles:
        if role in {"TEACHER", "TA"}:
            roles.add("teacher")
        elif role == "STUDENT":
            roles.add("student")
    return sorted(roles)


def _auth_token_response(
    db: Session,
    user: models.User,
    roles: list[str],
    access_token: str,
    expires_at: datetime,
) -> dict:
    return {
        "accessToken": access_token,
        "tokenType": "Bearer",
        "expiresAt": expires_at,
        "user": _auth_user_view(db, user, roles),
    }


def _auth_user_view(db: Session, user: models.User, roles: list[str]) -> dict:
    memberships = db.scalars(
        select(models.CourseMember).where(models.CourseMember.user_id == user.id)
    ).all()
    return {
        "tenantId": user.tenant_id,
        "userId": user.id,
        "displayName": user.display_name,
        "email": user.email,
        "roles": sorted(roles),
        "courseRoles": [
            {"courseId": membership.course_id, "role": membership.role}
            for membership in memberships
        ],
    }


def _require_internal_service(settings: Settings, token: str | None) -> None:
    if token != settings.internal_service_token:
        raise api_error(401, "UNAUTHENTICATED", "Internal service token invalid")


def _audit(
    db: Session,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str,
    decision: str,
    before_ref: str | None = None,
    after_ref: str | None = None,
) -> None:
    db.add(
        models.AuditLog(
            id=new_id("audit"),
            tenant_id=principal.tenant_id,
            actor=principal.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
            before_ref=before_ref,
            after_ref=after_ref,
        )
    )


def _audit_system(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    decision: str,
    before_ref: str | None = None,
    after_ref: str | None = None,
) -> None:
    db.add(
        models.AuditLog(
            id=new_id("audit"),
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
            before_ref=before_ref,
            after_ref=after_ref,
        )
    )


def _audit_ticket_consume_failure(db: Session, token: str, decision_detail: str) -> None:
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return
    nonce_value = unverified.get("nonce")
    nonce = db.get(models.TerminalTicketNonce, nonce_value) if nonce_value else None
    if nonce is None:
        return
    _audit_system(
        db,
        tenant_id=nonce.tenant_id,
        actor="terminal-gateway",
        action=f"terminal.ticket.consume.{decision_detail}",
        resource_type="attempt",
        resource_id=nonce.attempt_id,
        decision="DENY",
    )


def _outbox(
    db: Session, aggregate_type: str, aggregate_id: str, event_type: str, payload: dict
) -> None:
    db.add(
        models.OutboxEvent(
            id=new_id("out"),
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload_json=payload,
        )
    )


class LazyApp:
    def __init__(self) -> None:
        self._app: FastAPI | None = None

    async def __call__(self, scope, receive, send) -> None:
        if self._app is None:
            self._app = create_app()
        await self._app(scope, receive, send)


app = LazyApp()
