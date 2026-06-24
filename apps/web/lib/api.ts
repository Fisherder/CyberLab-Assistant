import { z } from "zod";

const API_BASE = process.env.NEXT_PUBLIC_CLA_API_BASE ?? "http://localhost:8000";
const ASSIGNMENT_ID = process.env.NEXT_PUBLIC_CLA_ASSIGNMENT_ID ?? "asg_web_sqli_auth";

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

function token(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem("claDevToken") ?? "";
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
