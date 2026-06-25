import { z } from "zod";

const API_BASE = process.env.NEXT_PUBLIC_CLA_API_BASE ?? "http://localhost:8000";
const ASSIGNMENT_ID = process.env.NEXT_PUBLIC_CLA_ASSIGNMENT_ID ?? "asg_web_sqli_auth";
const AUTH_TOKEN_KEY = "claAuthToken";
const DEV_TOKEN_KEY = "claDevToken";

const AuthUserResponse = z.object({
  tenantId: z.string(),
  userId: z.string(),
  displayName: z.string(),
  email: z.string().optional(),
  roles: z.array(z.string()),
  courseRoles: z.array(z.object({ courseId: z.string(), role: z.string() }))
});

const AuthTokenResponse = z.object({
  accessToken: z.string(),
  tokenType: z.literal("Bearer"),
  expiresAt: z.string(),
  user: AuthUserResponse
});

const AttemptResponse = z.object({
  attemptId: z.string(),
  status: z.string(),
  statusUrl: z.string()
});

const SessionResponse = z.object({
  sessionId: z.string(),
  sessionEpoch: z.number(),
  status: z.string(),
  workspaceType: z.literal("TERMINAL"),
  expiresAt: z.string()
});

const TicketResponse = z.object({
  sessionId: z.string(),
  sessionEpoch: z.number(),
  ticket: z.string(),
  websocketUrl: z.string(),
  expiresAt: z.string(),
  terminal: z.object({ cols: z.number(), rows: z.number(), encoding: z.string() }),
  reconnect: z.object({ supported: z.boolean(), bufferSeconds: z.number() }),
  policies: z.record(z.string())
});

const GradeResponse = z.object({
  gradeRevisionId: z.string(),
  attemptId: z.string(),
  revisionNo: z.number(),
  status: z.string(),
  totalScore: z.number(),
  independenceIndex: z.number(),
  rubricVersion: z.string(),
  graderVersion: z.string(),
  publishedAt: z.string(),
  criteria: z.array(
    z.object({
      criterionId: z.string(),
      score: z.number(),
      maxScore: z.number(),
      graderType: z.string(),
      confidence: z.number(),
      explanation: z.string(),
      evidenceRefs: z.array(z.string())
    })
  )
});

const AppealResponse = z.object({
  appealId: z.string(),
  criterionId: z.string(),
  status: z.string()
});

const HintResponse = z.object({
  hintId: z.string(),
  level: z.string(),
  triggerType: z.string(),
  content: z.string(),
  evidenceRefs: z.array(z.string()),
  tutorVersion: z.string(),
  shownAt: z.string().nullable(),
  status: z.string()
});

const TutorStateResponse = z.object({
  attemptId: z.string(),
  assessment: z.object({
    state: z.string(),
    score: z.number(),
    detectorVersion: z.string(),
    featureContributions: z.record(z.unknown()),
    excludedReasons: z.array(z.string()),
    evidenceRefs: z.array(z.string())
  }),
  latestHint: HintResponse.nullable(),
  autoHintsEnabled: z.boolean(),
  cooldown: z.object({
    active: z.boolean(),
    hintId: z.string().nullable()
  })
});

const AssignmentLiveResponse = z.object({
  assignmentId: z.string(),
  title: z.string(),
  generatedAt: z.string(),
  summary: z.object({
    totalAttempts: z.number(),
    readySessions: z.number(),
    stuckSuspected: z.number(),
    resourceAlerts: z.number(),
    securityAlerts: z.number()
  }),
  sessions: z.array(
    z.object({
      attemptId: z.string(),
      studentId: z.string(),
      studentDisplayName: z.string(),
      attemptStatus: z.string(),
      workspaceType: z.string(),
      sessionStatus: z.string().nullable(),
      sessionEpoch: z.number().nullable(),
      sessionExpiresAt: z.string().nullable(),
      latestAssessment: z
        .object({
          state: z.string(),
          score: z.number(),
          detectorVersion: z.string(),
          featureContributions: z.record(z.unknown()),
          excludedReasons: z.array(z.string()),
          evidenceRefs: z.array(z.string())
        })
        .nullable(),
      latestHint: z
        .object({
          level: z.string(),
          status: z.string(),
          triggerType: z.string()
        })
        .nullable(),
      alerts: z.object({
        resource: z.number(),
        security: z.number()
      }),
      latestEventAt: z.string().nullable()
    })
  )
});

const ChallengeValidationResponse = z.object({
  challengeVersionId: z.string(),
  challengeId: z.string(),
  semver: z.string(),
  versionStatus: z.string(),
  artifactDigest: z.string(),
  validationRunId: z.string(),
  workflowId: z.string(),
  status: z.string(),
  reportRef: z.string().nullable(),
  startedAt: z.string(),
  endedAt: z.string().nullable(),
  overallStatus: z.string(),
  summary: z.object({
    passed: z.number(),
    warnings: z.number(),
    blocked: z.number()
  }),
  checks: z.array(
    z.object({
      id: z.string(),
      category: z.string(),
      status: z.enum(["PASS", "WARN", "BLOCK"]),
      title: z.string(),
      evidenceRefs: z.array(z.string())
    })
  ),
  forbiddenDisclosuresChecked: z.array(z.string())
});

const ChallengeApprovalResponse = z.object({
  challengeVersionId: z.string(),
  challengeId: z.string(),
  semver: z.string(),
  status: z.string(),
  artifactDigest: z.string(),
  validationRunId: z.string(),
  validationStatus: z.enum(["PASS", "WARN"]),
  overallStatus: z.enum(["PASS", "WARN"]),
  published: z.boolean(),
  alreadyPublished: z.boolean()
});

const ChallengeRegistryVersionResponse = z.object({
  challengeId: z.string(),
  challengeVersionId: z.string(),
  slug: z.string(),
  title: z.string(),
  category: z.string(),
  semver: z.string(),
  status: z.string(),
  workspaceType: z.string(),
  difficulty: z.number(),
  expectedMinutes: z.number(),
  riskTier: z.number(),
  artifactDigest: z.string(),
  validationStatus: z.string(),
  searchScore: z.number(),
  created: z.boolean(),
  artifactCount: z.number(),
  latestArtifactRef: z.string().nullable(),
  approvalUrl: z.string(),
  validationUrl: z.string()
});

const ChallengeRegistryResponse = z.object({
  query: z.string(),
  count: z.number(),
  versions: z.array(ChallengeRegistryVersionResponse),
  retrieval: z.object({
    mode: z.string(),
    vectorEnabled: z.boolean(),
    vectorReason: z.string()
  })
});

const ChallengeImportResponse = z.object({
  imported: z.array(ChallengeRegistryVersionResponse),
  skipped: z.array(z.record(z.unknown()))
});

const CourseIntentResponse = z.object({
  category: z.string(),
  target: z.string(),
  difficulty: z.number(),
  expectedMinutes: z.number(),
  workspaceType: z.string(),
  isolationTier: z.number(),
  allowedTools: z.array(z.string()),
  learningObjectives: z.array(z.string()),
  uncertainFields: z.array(z.string()),
  confidence: z.number()
});

const ChallengeDraftResponse = z.object({
  draftId: z.string(),
  status: z.string(),
  courseId: z.string(),
  courseIntent: CourseIntentResponse,
  constraints: z.record(z.unknown()),
  candidatesUrl: z.string()
});

const ChallengeCandidateResponse = z.object({
  candidateId: z.string(),
  challengeId: z.string(),
  challengeVersionId: z.string(),
  title: z.string(),
  semver: z.string(),
  artifactDigest: z.string(),
  riskTier: z.number(),
  score: z.number(),
  searchScore: z.number(),
  retrievalSignals: z.record(z.unknown()),
  constraintsSatisfied: z.boolean(),
  matchReasons: z.array(z.string()),
  conflicts: z.array(z.string()),
  validationStatus: z.string()
});

const ChallengeCandidateSearchResponse = z.object({
  draftId: z.string(),
  status: z.string(),
  courseIntent: CourseIntentResponse,
  candidates: z.array(ChallengeCandidateResponse),
  rejectedCandidates: z.array(ChallengeCandidateResponse)
});

const ChallengeGeneratedVersionResponse = z.object({
  draftId: z.string(),
  status: z.string(),
  sourceCandidateId: z.string(),
  challengeVersionId: z.string(),
  challengeId: z.string(),
  semver: z.string(),
  versionStatus: z.string(),
  validationRunId: z.string(),
  validationStatus: z.string(),
  validationReportUrl: z.string(),
  approvalRequired: z.boolean(),
  generatedBy: z.string(),
  modelDraft: z.record(z.unknown())
});

const ChallengeBankItemResponse = z.object({
  itemId: z.string(),
  courseId: z.string(),
  challengeVersionId: z.string(),
  assignmentId: z.string().nullable(),
  title: z.string(),
  summary: z.string(),
  description: z.string(),
  requirements: z.string(),
  tags: z.array(z.string()),
  status: z.string(),
  publishState: z.string(),
  openAt: z.string().nullable(),
  dueAt: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
  publishedAt: z.string().nullable(),
  unpublishedAt: z.string().nullable(),
  deletedAt: z.string().nullable(),
  restoredAt: z.string().nullable(),
  version: ChallengeRegistryVersionResponse,
  actions: z.record(z.boolean())
});

const ChallengeBankListResponse = z.object({
  courseId: z.string().nullable(),
  count: z.number(),
  items: z.array(ChallengeBankItemResponse)
});

const StudentChallengeBankItemResponse = z.object({
  itemId: z.string(),
  courseId: z.string(),
  title: z.string(),
  summary: z.string(),
  description: z.string(),
  requirements: z.string(),
  tags: z.array(z.string()),
  publishState: z.string(),
  clickable: z.boolean(),
  disabledReason: z.string().nullable(),
  openAt: z.string(),
  dueAt: z.string(),
  attemptId: z.string().nullable(),
  targetUrl: z.string().nullable(),
  terminalUrl: z.string().nullable()
});

const StudentChallengeBankListResponse = z.object({
  count: z.number(),
  items: z.array(StudentChallengeBankItemResponse)
});

const StartChallengeBankItemResponse = z.object({
  itemId: z.string(),
  assignmentId: z.string(),
  attemptId: z.string(),
  sessionId: z.string(),
  sessionEpoch: z.number(),
  sessionStatus: z.string(),
  targetUrl: z.string(),
  terminalUrl: z.string(),
  workspaceUrl: z.string(),
  reusedAttempt: z.boolean()
});

export type AttemptResponse = z.infer<typeof AttemptResponse>;
export type SessionResponse = z.infer<typeof SessionResponse>;
export type TicketResponse = z.infer<typeof TicketResponse>;
export type GradeResponse = z.infer<typeof GradeResponse>;
export type AppealResponse = z.infer<typeof AppealResponse>;
export type HintResponse = z.infer<typeof HintResponse>;
export type TutorStateResponse = z.infer<typeof TutorStateResponse>;
export type AssignmentLiveResponse = z.infer<typeof AssignmentLiveResponse>;
export type ChallengeValidationResponse = z.infer<typeof ChallengeValidationResponse>;
export type ChallengeApprovalResponse = z.infer<typeof ChallengeApprovalResponse>;
export type AuthUserResponse = z.infer<typeof AuthUserResponse>;
export type AuthTokenResponse = z.infer<typeof AuthTokenResponse>;
export type ChallengeRegistryVersionResponse = z.infer<typeof ChallengeRegistryVersionResponse>;
export type ChallengeRegistryResponse = z.infer<typeof ChallengeRegistryResponse>;
export type ChallengeImportResponse = z.infer<typeof ChallengeImportResponse>;
export type ChallengeDraftResponse = z.infer<typeof ChallengeDraftResponse>;
export type ChallengeCandidateSearchResponse = z.infer<typeof ChallengeCandidateSearchResponse>;
export type ChallengeGeneratedVersionResponse = z.infer<typeof ChallengeGeneratedVersionResponse>;
export type ChallengeBankItemResponse = z.infer<typeof ChallengeBankItemResponse>;
export type ChallengeBankListResponse = z.infer<typeof ChallengeBankListResponse>;
export type StudentChallengeBankItemResponse = z.infer<typeof StudentChallengeBankItemResponse>;
export type StudentChallengeBankListResponse = z.infer<typeof StudentChallengeBankListResponse>;
export type StartChallengeBankItemResponse = z.infer<typeof StartChallengeBankItemResponse>;

export function currentToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(AUTH_TOKEN_KEY) ?? window.localStorage.getItem(DEV_TOKEN_KEY) ?? "";
}

export function hasAuthToken(): boolean {
  return currentToken().length > 0;
}

export function setAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  window.localStorage.removeItem(DEV_TOKEN_KEY);
}

export function setDevToken(tokenValue: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(DEV_TOKEN_KEY, tokenValue);
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(DEV_TOKEN_KEY);
}

function token(): string {
  return currentToken();
}

async function api<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("content-type", "application/json");
  const bearer = token();
  if (bearer) headers.set("authorization", `Bearer ${bearer}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.code ?? response.statusText);
  }
  return schema.parse(await response.json());
}

export async function loginLocalAccount(email: string, password: string): Promise<AuthTokenResponse> {
  return api("/api/v1/auth/login", AuthTokenResponse, {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export async function registerLocalAccount(
  email: string,
  password: string,
  displayName: string,
  role: "STUDENT" | "TEACHER"
): Promise<AuthTokenResponse> {
  return api("/api/v1/auth/register", AuthTokenResponse, {
    method: "POST",
    body: JSON.stringify({ email, password, displayName, role })
  });
}

export async function fetchMe(): Promise<AuthUserResponse> {
  return api("/api/v1/me", AuthUserResponse);
}

export async function createAttempt(): Promise<AttemptResponse> {
  return api(`/api/v1/assignments/${ASSIGNMENT_ID}/attempts`, AttemptResponse, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      clientCapabilities: { terminalBinaryFrames: true, workspaceTypes: ["TERMINAL"] }
    })
  });
}

export async function ensureSession(attemptId: string): Promise<SessionResponse> {
  return api(`/api/v1/attempts/${attemptId}/sessions`, SessionResponse, {
    method: "POST",
    body: JSON.stringify({ workspaceType: "TERMINAL" })
  });
}

export async function resetSession(attemptId: string): Promise<SessionResponse> {
  return api(`/api/v1/attempts/${attemptId}/sessions/reset`, SessionResponse, { method: "POST" });
}

export async function terminalTicket(attemptId: string): Promise<TicketResponse> {
  return api(`/api/v1/attempts/${attemptId}/terminal-ticket`, TicketResponse, { method: "POST" });
}

export async function submitAnswer(attemptId: string, content: string): Promise<void> {
  await api(
    `/api/v1/attempts/${attemptId}/submit`,
    z.object({ attemptId: z.string(), status: z.string(), gradingWorkflowId: z.string() }),
    {
      method: "POST",
      body: JSON.stringify({
        answers: [{ questionId: "root-cause", format: "MARKDOWN", content }],
        requestOracleCheck: true
      })
    }
  );
}

export async function fetchGrade(attemptId: string): Promise<GradeResponse> {
  return api(`/api/v1/attempts/${attemptId}/grade`, GradeResponse);
}

export async function createAppeal(
  gradeRevisionId: string,
  criterionId: string,
  reason: string
): Promise<AppealResponse> {
  return api(`/api/v1/grades/${gradeRevisionId}/appeals`, AppealResponse, {
    method: "POST",
    body: JSON.stringify({ criterionId, reason })
  });
}

export async function fetchTutorState(attemptId: string): Promise<TutorStateResponse> {
  return api(`/api/v1/attempts/${attemptId}/tutor-state`, TutorStateResponse);
}

export async function fetchAssignmentLive(assignmentId: string): Promise<AssignmentLiveResponse> {
  return api(`/api/v1/assignments/${assignmentId}/live`, AssignmentLiveResponse);
}

export async function fetchChallengeValidation(
  versionId: string
): Promise<ChallengeValidationResponse> {
  return api(`/api/v1/challenge-versions/${versionId}/validation`, ChallengeValidationResponse);
}

export async function approveChallengeVersion(
  versionId: string
): Promise<ChallengeApprovalResponse> {
  return api(`/api/v1/challenge-versions/${versionId}/approve`, ChallengeApprovalResponse, {
    method: "POST"
  });
}

export async function fetchChallengeRegistry(query = ""): Promise<ChallengeRegistryResponse> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("query", query.trim());
  const suffix = params.toString() ? `?${params}` : "";
  return api(`/api/v1/challenge-registry${suffix}`, ChallengeRegistryResponse);
}

export async function importLocalChallenges(): Promise<ChallengeImportResponse> {
  return api("/api/v1/challenge-registry/import-local", ChallengeImportResponse, {
    method: "POST"
  });
}

export async function createChallengeDraft(
  courseId: string,
  brief: string,
  constraints: Record<string, unknown>
): Promise<ChallengeDraftResponse> {
  return api("/api/v1/challenge-drafts", ChallengeDraftResponse, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ courseId, brief, constraints })
  });
}

export async function fetchChallengeCandidates(
  candidatesUrl: string
): Promise<ChallengeCandidateSearchResponse> {
  return api(candidatesUrl, ChallengeCandidateSearchResponse);
}

export async function generateChallengeVersion(
  draftId: string,
  selectedCandidateId: string
): Promise<ChallengeGeneratedVersionResponse> {
  return api(`/api/v1/challenge-drafts/${draftId}/generate-version`, ChallengeGeneratedVersionResponse, {
    method: "POST",
    body: JSON.stringify({ selectedCandidateId })
  });
}

export async function fetchTeacherChallengeBank(courseId?: string): Promise<ChallengeBankListResponse> {
  const params = new URLSearchParams();
  if (courseId?.trim()) params.set("courseId", courseId.trim());
  const suffix = params.toString() ? `?${params}` : "";
  return api(`/api/v1/teacher/challenge-bank${suffix}`, ChallengeBankListResponse);
}

export async function fetchTeacherChallengeBankTrash(courseId?: string): Promise<ChallengeBankListResponse> {
  const params = new URLSearchParams();
  if (courseId?.trim()) params.set("courseId", courseId.trim());
  const suffix = params.toString() ? `?${params}` : "";
  return api(`/api/v1/teacher/challenge-bank/trash${suffix}`, ChallengeBankListResponse);
}

export async function createChallengeBankItem(payload: {
  courseId: string;
  challengeVersionId: string;
  title: string;
  summary: string;
  description: string;
  requirements: string;
  tags: string[];
  publish: boolean;
  publishWindow?: { openAt: string; dueAt: string } | null;
}): Promise<ChallengeBankItemResponse> {
  return api("/api/v1/teacher/challenge-bank", ChallengeBankItemResponse, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(payload)
  });
}

export async function updateChallengeBankItem(
  itemId: string,
  payload: {
    title?: string;
    summary?: string;
    description?: string;
    requirements?: string;
    tags?: string[];
  }
): Promise<ChallengeBankItemResponse> {
  return api(`/api/v1/teacher/challenge-bank/${itemId}`, ChallengeBankItemResponse, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function publishChallengeBankItem(
  itemId: string,
  openAt: string,
  dueAt: string
): Promise<ChallengeBankItemResponse> {
  return api(`/api/v1/teacher/challenge-bank/${itemId}/publish`, ChallengeBankItemResponse, {
    method: "POST",
    body: JSON.stringify({ openAt, dueAt })
  });
}

export async function unpublishChallengeBankItem(itemId: string): Promise<ChallengeBankItemResponse> {
  return api(`/api/v1/teacher/challenge-bank/${itemId}/unpublish`, ChallengeBankItemResponse, {
    method: "POST"
  });
}

export async function deleteChallengeBankItem(itemId: string): Promise<ChallengeBankItemResponse> {
  return api(`/api/v1/teacher/challenge-bank/${itemId}`, ChallengeBankItemResponse, {
    method: "DELETE"
  });
}

export async function restoreChallengeBankItem(itemId: string): Promise<ChallengeBankItemResponse> {
  return api(`/api/v1/teacher/challenge-bank/${itemId}/restore`, ChallengeBankItemResponse, {
    method: "POST"
  });
}

export async function fetchStudentChallengeBank(): Promise<StudentChallengeBankListResponse> {
  return api("/api/v1/student/challenge-bank", StudentChallengeBankListResponse);
}

export async function startStudentChallengeBankItem(itemId: string): Promise<StartChallengeBankItemResponse> {
  return api(`/api/v1/student/challenge-bank/${itemId}/start`, StartChallengeBankItemResponse, {
    method: "POST"
  });
}

export async function requestHint(attemptId: string, level: "L1" | "L2" | "L3"): Promise<HintResponse> {
  return api(`/api/v1/attempts/${attemptId}/hints/request`, HintResponse, {
    method: "POST",
    body: JSON.stringify({ level })
  });
}

export async function sendHintFeedback(
  hintId: string,
  feedback: "ACCEPTED" | "LATER" | "MISJUDGED" | "AUTO_DISABLED"
): Promise<{ hintId: string; status: string }> {
  return api(
    `/api/v1/hints/${hintId}/feedback`,
    z.object({ hintId: z.string(), status: z.string() }),
    {
      method: "POST",
      body: JSON.stringify({ feedback })
    }
  );
}
