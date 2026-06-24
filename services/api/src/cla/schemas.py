from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


WorkspaceType = Literal["TERMINAL", "REMOTE_DESKTOP", "SIMULATED"]


class ClientCapabilities(BaseModel):
    terminalBinaryFrames: bool = True
    workspaceTypes: list[WorkspaceType] = Field(default_factory=lambda: ["TERMINAL"])


class CreateChallengeDraftRequest(BaseModel):
    courseId: str = Field(min_length=1, max_length=64)
    brief: str = Field(min_length=10, max_length=8000)
    constraints: dict = Field(default_factory=dict)


class MaterializeChallengeDraftRequest(BaseModel):
    selectedCandidateId: str = Field(min_length=1, max_length=120)


class CreateCourseRequest(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    term: str = Field(min_length=1, max_length=80)


class CourseView(BaseModel):
    courseId: str
    code: str
    title: str
    term: str
    status: str
    ownerId: str


class UpsertCourseMemberRequest(BaseModel):
    role: Literal["STUDENT", "TEACHER", "TA"]


class CourseMemberView(BaseModel):
    courseId: str
    userId: str
    role: str


class CreateAssignmentRequest(BaseModel):
    courseId: str = Field(min_length=1, max_length=64)
    challengeVersionId: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=240)
    openAt: datetime | None = None
    dueAt: datetime | None = None
    attemptPolicy: dict = Field(default_factory=dict)


class AssignmentView(BaseModel):
    assignmentId: str
    courseId: str
    challengeVersionId: str
    title: str
    openAt: datetime
    dueAt: datetime | None
    attemptPolicy: dict


class CourseIntentView(BaseModel):
    category: str
    target: str
    difficulty: int
    expectedMinutes: int
    workspaceType: WorkspaceType
    isolationTier: int
    allowedTools: list[str]
    learningObjectives: list[str]
    uncertainFields: list[str]
    confidence: float


class ChallengeDraftView(BaseModel):
    draftId: str
    status: str
    courseId: str
    courseIntent: CourseIntentView
    constraints: dict
    candidatesUrl: str


class ChallengeCandidateView(BaseModel):
    candidateId: str
    challengeId: str
    challengeVersionId: str
    title: str
    semver: str
    artifactDigest: str
    riskTier: int
    score: float
    constraintsSatisfied: bool
    matchReasons: list[str]
    conflicts: list[str]
    validationStatus: str


class ChallengeCandidateSearchView(BaseModel):
    draftId: str
    status: str
    courseIntent: CourseIntentView
    candidates: list[ChallengeCandidateView]
    rejectedCandidates: list[ChallengeCandidateView]


class ChallengeMaterializeView(BaseModel):
    draftId: str
    status: str
    sourceCandidateId: str
    challengeVersionId: str
    challengeId: str
    semver: str
    versionStatus: str
    validationRunId: str
    validationStatus: str
    validationReportUrl: str
    approvalRequired: bool


class CreateAttemptRequest(BaseModel):
    clientCapabilities: ClientCapabilities = Field(default_factory=ClientCapabilities)


class AttemptResponse(BaseModel):
    attemptId: str
    status: str
    challengeVersion: str
    workspaceType: WorkspaceType
    sessionWorkflowId: str
    statusUrl: str


class AttemptView(BaseModel):
    attemptId: str
    status: str
    assignmentId: str
    workspaceType: WorkspaceType
    session: dict | None


class EnsureSessionRequest(BaseModel):
    workspaceType: WorkspaceType = "TERMINAL"


class SessionResponse(BaseModel):
    sessionId: str
    sessionEpoch: int
    status: str
    workspaceType: WorkspaceType
    expiresAt: datetime


class TerminalTicketResponse(BaseModel):
    sessionId: str
    sessionEpoch: int
    ticket: str
    websocketUrl: str
    expiresAt: datetime
    terminal: dict
    reconnect: dict
    policies: dict


class ConsumeTicketRequest(BaseModel):
    ticket: str


class InternalEventInput(BaseModel):
    sessionEpoch: int = Field(ge=1)
    source: str = Field(min_length=1, max_length=120)
    type: str = Field(min_length=1, max_length=160)
    payload: dict = Field(default_factory=dict)
    traceId: str | None = None


class AppendBatchRequest(BaseModel):
    events: list[InternalEventInput] = Field(min_length=1, max_length=100)


class RouteRegistrationRequest(BaseModel):
    routeRef: str = Field(min_length=1, max_length=120)
    endpoint: str = Field(min_length=1, max_length=240)
    protocol: Literal["tcp-sessionwire"] = "tcp-sessionwire"


class RouteUnregisterRequest(BaseModel):
    routeRef: str = Field(min_length=1, max_length=120)


class TicketRevokeRequest(BaseModel):
    routeRef: str = Field(min_length=1, max_length=120)


class TranscriptSegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionEpoch: int = Field(ge=1)
    direction: Literal["INPUT", "OUTPUT"]
    seqFrom: int = Field(ge=0)
    seqTo: int = Field(ge=0)
    objectRef: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r"^(sha256:)?[0-9a-fA-F]{64}$")
    redactionState: Literal["RAW", "REDACTED", "ENCRYPTED", "INDEX_ONLY"] = "INDEX_ONLY"


class TranscriptSegmentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionEpoch: int = Field(ge=1)
    direction: Literal["INPUT", "OUTPUT"]
    seqFrom: int = Field(ge=0)
    seqTo: int = Field(ge=0)
    segmentBase64: str = Field(min_length=1)


class TranscriptRestoreVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionEpoch: int | None = Field(default=None, ge=1)
    limit: int = Field(default=100, ge=1, le=1000)


class TranscriptRetentionApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    olderThanDays: int | None = Field(default=None, ge=1, le=3650)
    limit: int = Field(default=1000, ge=1, le=10000)
    dryRun: bool = True


class OracleObservation(BaseModel):
    oracleVersion: str
    passed: bool
    targetSessionKey: str
    evidence: dict = Field(default_factory=dict)


class Answer(BaseModel):
    questionId: str
    format: Literal["MARKDOWN", "TEXT"] = "MARKDOWN"
    content: str
    clientDraftId: str | None = None


class SubmitRequest(BaseModel):
    answers: list[Answer]
    requestOracleCheck: bool = True


class SubmitResponse(BaseModel):
    attemptId: str
    status: str
    gradingWorkflowId: str


class CriterionResultView(BaseModel):
    criterionId: str
    score: float
    maxScore: float
    graderType: str
    confidence: float
    explanation: str
    evidenceRefs: list[str]


class GradeView(BaseModel):
    gradeRevisionId: str
    attemptId: str
    revisionNo: int
    status: str
    totalScore: float
    independenceIndex: float
    rubricVersion: str
    graderVersion: str
    publishedAt: datetime
    criteria: list[CriterionResultView]


class AppealRequest(BaseModel):
    criterionId: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=3, max_length=4000)


class CriterionOverrideRequest(BaseModel):
    criterionId: str = Field(min_length=1, max_length=120)
    score: float = Field(ge=0)
    explanation: str = Field(min_length=3, max_length=4000)


class ResolveAppealRequest(BaseModel):
    decision: Literal["UPHOLD_ORIGINAL", "OVERRIDE_SCORE"]
    resolution: str = Field(min_length=3, max_length=4000)
    criterionOverrides: list[CriterionOverrideRequest] = Field(default_factory=list, max_length=5)


class HintRequest(BaseModel):
    level: Literal["L1", "L2", "L3"] = "L1"


class HintFeedbackRequest(BaseModel):
    feedback: Literal["ACCEPTED", "LATER", "MISJUDGED", "AUTO_DISABLED"]


class StuckAssessmentView(BaseModel):
    state: str
    score: float
    detectorVersion: str
    featureContributions: dict
    excludedReasons: list[str]
    evidenceRefs: list[str]


class HintView(BaseModel):
    hintId: str
    level: str
    triggerType: str
    content: str
    evidenceRefs: list[str]
    tutorVersion: str
    shownAt: datetime | None
    status: str


class TutorStateView(BaseModel):
    attemptId: str
    assessment: StuckAssessmentView
    latestHint: HintView | None
    autoHintsEnabled: bool
    cooldown: dict


class LiveHintSummary(BaseModel):
    level: str
    status: str
    triggerType: str


class LiveAlertCounts(BaseModel):
    resource: int
    security: int


class AssignmentLiveAttemptView(BaseModel):
    attemptId: str
    studentId: str
    studentDisplayName: str
    attemptStatus: str
    workspaceType: WorkspaceType
    sessionStatus: str | None
    sessionEpoch: int | None
    sessionExpiresAt: datetime | None
    latestAssessment: StuckAssessmentView | None
    latestHint: LiveHintSummary | None
    alerts: LiveAlertCounts
    latestEventAt: datetime | None


class AssignmentLiveSummary(BaseModel):
    totalAttempts: int
    readySessions: int
    stuckSuspected: int
    resourceAlerts: int
    securityAlerts: int


class AssignmentLiveView(BaseModel):
    assignmentId: str
    title: str
    generatedAt: datetime
    summary: AssignmentLiveSummary
    sessions: list[AssignmentLiveAttemptView]


class ValidationCheckView(BaseModel):
    id: str
    category: str
    status: Literal["PASS", "WARN", "BLOCK"]
    title: str
    evidenceRefs: list[str]


class ValidationReportSummary(BaseModel):
    passed: int
    warnings: int
    blocked: int


class ChallengeValidationView(BaseModel):
    challengeVersionId: str
    challengeId: str
    semver: str
    versionStatus: str
    artifactDigest: str
    validationRunId: str
    workflowId: str
    status: str
    reportRef: str | None
    startedAt: datetime
    endedAt: datetime | None
    overallStatus: str
    summary: ValidationReportSummary
    checks: list[ValidationCheckView]
    forbiddenDisclosuresChecked: list[str]


class ChallengeApprovalView(BaseModel):
    challengeVersionId: str
    challengeId: str
    semver: str
    status: str
    artifactDigest: str
    validationRunId: str
    validationStatus: str
    overallStatus: Literal["PASS", "WARN"]
    published: bool
    alreadyPublished: bool
