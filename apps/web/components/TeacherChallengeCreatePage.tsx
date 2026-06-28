"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, CalendarClock, CheckCircle2, CircleAlert, Loader2, Plus, Send, UploadCloud } from "lucide-react";
import {
  createChallengeBankItem,
  createChallengeDraft,
  fetchChallengeCandidates,
  generateCustomChallengePackage,
  hasAuthToken,
  runChallengeAuthoringPipeline,
  type AuthoringPipelineRunResponse,
  type AuthoringPipelineStepResponse,
  type ChallengeDraftResponse,
  type ChallengeCandidateSearchResponse,
  type ChallengeBankItemResponse
} from "../lib/api";
import {
  applyPreviewFieldUpdate,
  inferAuthoringFieldUpdate,
  toLocalInput,
  type AuthoringFieldUpdate,
  type AuthoringPreviewState,
  type PublishWindow
} from "../lib/authoringFieldUpdates";
import { TeacherWorkspaceShell } from "./TeacherWorkspaceShell";

const DEFAULT_COURSE_ID = "course_websec";
const DEFAULT_VERSION_ID = "cv_web_sqli_auth_1_3_0";

type ChatMessage = {
  role: "teacher" | "agent";
  content: string;
};

type PreviewState = AuthoringPreviewState;

export function TeacherChallengeCreatePage() {
  const [preview, setPreview] = useState<PreviewState>(() => initialPreview());
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "agent",
      content:
        "请描述你想发布给学生的实践题。我会从题目数据库中检索候选题，并实时更新中间的题目详情卡片。"
    }
  ]);
  const [input, setInput] = useState(
    "创建一个 Web 登录认证绕过题，学生需要获取容器、访问目标地址、用终端或浏览器验证认证边界，并提交根因和修复建议。"
  );
  const [publishWindow, setPublishWindow] = useState<PublishWindow>(() => emptyWindow());
  const [candidateSearch, setCandidateSearch] = useState<ChallengeCandidateSearchResponse | null>(null);
  const [courseIntent, setCourseIntent] = useState<ChallengeDraftResponse["courseIntent"] | null>(null);
  const [pipelineSteps, setPipelineSteps] = useState<AuthoringPipelineStepResponse[]>([]);
  const [pipelineRun, setPipelineRun] = useState<AuthoringPipelineRunResponse | null>(null);
  const [createdItem, setCreatedItem] = useState<ChallengeBankItemResponse | null>(null);
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    setPublishWindow(defaultWindow());
  }, []);

  useEffect(() => {
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
    }
  }, []);

  const bestCandidate = useMemo(() => candidateSearch?.candidates[0] ?? null, [candidateSearch]);
  const authoringProposal = useMemo(() => candidateSearch?.authoringProposal ?? null, [candidateSearch]);
  const publishWindowReady = publishWindow.openAt !== "" && publishWindow.dueAt !== "";

  async function sendToAgent() {
    const text = input.trim();
    if (!text) return;
    setError("");
    setMessage("");
    setLoading("agent");
    const nextMessages: ChatMessage[] = [...messages, { role: "teacher", content: text }];
    setMessages(nextMessages);
    setInput("");
    try {
      const fieldUpdate = inferAuthoringFieldUpdate(text, preview, publishWindow, new Date(), courseIntent);
      const activePublishWindow = fieldUpdate.publish?.window ?? publishWindow;
      const activePreview = applyPreviewFieldUpdate(preview, fieldUpdate.preview);
      if (fieldUpdate.publish) {
        setPublishWindow(fieldUpdate.publish.window);
      }
      const brief = buildConversationBrief(nextMessages);
      const draft = await createChallengeDraft(preview.courseId, brief, {
        internet: false,
        maxDifficulty: 5,
        workspaceType: "TERMINAL",
        ...fieldUpdate.constraints,
        authoringConversation: nextMessages,
        latestTeacherMessage: text,
        currentPreview: activePreview,
        currentCourseIntent: courseIntent,
        currentPublishWindow: activePublishWindow
      });
      setCourseIntent(draft.courseIntent);
      const candidates = await fetchChallengeCandidates(draft.candidatesUrl);
      setCandidateSearch(candidates);
      const proposal = candidates.authoringProposal;
      let challengeVersionId = proposal.challengeVersionId ?? candidates.candidates[0]?.challengeVersionId ?? preview.challengeVersionId;
      let generatedVersionId = "";
      if (proposal.requiresCustomGeneration) {
        const generated = await generateCustomChallengePackage(draft.draftId);
        challengeVersionId = generated.challengeVersionId;
        generatedVersionId = generated.challengeVersionId;
      }
      setPreview((current) => applyPreviewFieldUpdate({
        ...current,
        challengeVersionId,
        title: proposal.title,
        summary: proposal.summary,
        description: proposal.description,
        requirements: proposal.requirements,
        tags: proposal.tags.join(", ")
      }, fieldUpdate.preview));
      setMessages((current) => [
        ...current,
        {
          role: "agent",
          content: formatAgentReply(
            fieldUpdate,
            proposal.mode,
            proposal.title,
            candidates.candidates[0]?.title ?? "",
            candidates.candidates[0]?.score ?? 0,
            generatedVersionId
          )
        }
      ]);
    } catch (err) {
      setError(readError(err));
      setMessages((current) => [
        ...current,
        { role: "agent", content: "这轮检索没有成功。你可以继续补充需求，或直接编辑题目详情卡片。" }
      ]);
    } finally {
      setLoading("");
    }
  }

  async function createItem(nextPublish: boolean) {
    setError("");
    setMessage("");
    setCreatedItem(null);
    setPipelineRun(null);
    if (nextPublish && !publishWindowReady) {
      setError("请先设置完整的开始时间和结束时间。");
      return;
    }
    const tags = parseTags(preview.tags);
    const layerOnePrompt = buildLayerOnePrompt(preview, messages, candidateSearch, nextPublish);
    setPipelineSteps(initialPipelineSteps(preview.title));
    setLoading(nextPublish ? "publish" : "create");
    try {
      const run = await runChallengeAuthoringPipeline({
        courseId: preview.courseId.trim(),
        challengeVersionId: preview.challengeVersionId.trim(),
        title: preview.title.trim(),
        summary: preview.summary.trim(),
        description: preview.description.trim(),
        requirements: preview.requirements.trim(),
        tags,
        layerOnePrompt,
        candidateContext: {
          mode: authoringProposal?.mode ?? "UNKNOWN",
          proposalTitle: authoringProposal?.title ?? "",
          candidateIds: authoringProposal?.candidateIds ?? [],
          bestCandidateId: bestCandidate?.candidateId ?? "",
          bestCandidateTitle: bestCandidate?.title ?? "",
          courseIntent,
        },
        publish: nextPublish,
        publishWindow: nextPublish ? toApiWindow(publishWindow) : null
      });
      setPipelineRun(run);
      setPipelineSteps(run.steps);
      if (run.status !== "PASS") {
        setError("三层出题 Agent 验证未通过，已停止创建。请根据过程反馈继续修改题面。");
        return;
      }
      const item = await createChallengeBankItem({
        courseId: preview.courseId.trim(),
        challengeVersionId: preview.challengeVersionId.trim(),
        title: preview.title.trim(),
        summary: preview.summary.trim(),
        description: preview.description.trim(),
        requirements: preview.requirements.trim(),
        tags,
        publish: nextPublish,
        publishWindow: nextPublish ? toApiWindow(publishWindow) : null
      });
      setCreatedItem(item);
      setMessage(nextPublish ? "题目已创建并发布，三层 Agent 验证过程如下。" : "题目已创建为未发布草稿，三层 Agent 验证过程如下。");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  return (
    <TeacherWorkspaceShell active="bank">
      <main className="teacher-create-main">
        <header className="teacher-page-header">
          <div>
            <Link className="backlink" href="/teacher/challenge-bank">
              <ArrowLeft size={16} /> 返回题库
            </Link>
            <h1>创建题目</h1>
            <span>和 Agent 多轮确认题面，确认无误后创建到教师题库。</span>
          </div>
        </header>

        {error ? <div className="error banner">{error}</div> : null}
        {message ? (
          <div className="status-note">
            {message}
            {createdItem ? (
              <Link href={`/teacher/challenge-bank?created=${encodeURIComponent(createdItem.itemId)}`}>
                查看题库条目
              </Link>
            ) : null}
          </div>
        ) : null}

        <section className="teacher-create-layout">
          <article className="challenge-preview-card">
            <div className="authoring-title">
              <Plus size={18} />
              <h2>题目详细信息</h2>
            </div>
            <div className="preview-form-grid">
              <label>
                课程 ID
                <input
                  value={preview.courseId}
                  onChange={(event) => setPreview({ ...preview, courseId: event.target.value })}
                />
              </label>
              <label>
                题目版本 ID
                <input
                  value={preview.challengeVersionId}
                  onChange={(event) => setPreview({ ...preview, challengeVersionId: event.target.value })}
                />
              </label>
              <label>
                题目标题
                <input value={preview.title} onChange={(event) => setPreview({ ...preview, title: event.target.value })} />
              </label>
              <label>
                标签
                <input value={preview.tags} onChange={(event) => setPreview({ ...preview, tags: event.target.value })} />
              </label>
            </div>
            <label className="field-label">列表摘要</label>
            <input value={preview.summary} onChange={(event) => setPreview({ ...preview, summary: event.target.value })} />
            <label className="field-label">题目说明</label>
            <textarea
              value={preview.description}
              onChange={(event) => setPreview({ ...preview, description: event.target.value })}
            />
            <label className="field-label">完成要求</label>
            <textarea
              value={preview.requirements}
              onChange={(event) => setPreview({ ...preview, requirements: event.target.value })}
            />

            <section className="publish-box">
              <div className="authoring-title">
                <CalendarClock size={17} />
                <h3>发布设置</h3>
              </div>
              <div className="publish-grid">
                <label>
                  开始时间
                  <input
                    type="datetime-local"
                    value={publishWindow.openAt}
                    onChange={(event) => setPublishWindow({ ...publishWindow, openAt: event.target.value })}
                  />
                </label>
                <label>
                  结束时间
                  <input
                    type="datetime-local"
                    value={publishWindow.dueAt}
                    onChange={(event) => setPublishWindow({ ...publishWindow, dueAt: event.target.value })}
                  />
                </label>
              </div>
            </section>

            <footer className="bank-actionbar">
              <button className="iconbutton" type="button" onClick={() => createItem(false)} disabled={loading !== ""}>
                <Plus size={16} /> 创建题目
              </button>
              <button
                className="iconbutton primary"
                type="button"
                onClick={() => createItem(true)}
                disabled={loading !== "" || !publishWindowReady}
              >
                <UploadCloud size={16} /> 创建并发布
              </button>
            </footer>

            {pipelineSteps.length ? (
              <section className="authoring-pipeline-panel">
                <div className="authoring-title">
                  {loading === "create" || loading === "publish" ? <Loader2 className="spin" size={17} /> : <CheckCircle2 size={17} />}
                  <h3>三层出题 Agent 过程</h3>
                </div>
                <p className="pipeline-summary">
                  {pipelineRun?.summary ?? "正在执行需求对齐、环境构建、模拟做题验证和评分标准生成。"}
                </p>
                <div className="pipeline-timeline">
                  {pipelineSteps.map((step, index) => (
                    <article className={`pipeline-step ${step.status.toLowerCase()}`} key={`${step.layer}-${step.iteration}-${index}`}>
                      <div className="pipeline-step-head">
                        {step.status === "NEEDS_REVISION" ? <CircleAlert size={16} /> : <CheckCircle2 size={16} />}
                        <strong>{step.title}</strong>
                        <span>{step.agent} · 第 {step.iteration} 轮 · {step.status}</span>
                      </div>
                      <p>{step.detail}</p>
                      {step.feedback.length ? <ul>{step.feedback.map((item) => <li key={item}>{item}</li>)}</ul> : null}
                      {step.artifacts.length ? (
                        <div className="pipeline-artifacts">
                          {step.artifacts.slice(0, 8).map((artifact) => <code key={artifact}>{artifact}</code>)}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
                {pipelineRun ? (
                  <div className="pipeline-result-grid">
                    <div>
                      <strong>验证检查</strong>
                      <span>{pipelineRun.validationChecks.length} 项通过</span>
                    </div>
                    <div>
                      <strong>生成资产</strong>
                      <span>{pipelineRun.generatedFiles.length} 个文件</span>
                    </div>
                    <div>
                      <strong>评分标准</strong>
                      <span>{rubricTotal(pipelineRun.rubric)} 分 · {rubricCriteriaCount(pipelineRun.rubric)} 项</span>
                    </div>
                  </div>
                ) : null}
              </section>
            ) : null}
          </article>

          <aside className="agent-chat-panel">
            <div className="authoring-title">
              <Bot size={18} />
              <h2>出题 Agent</h2>
            </div>
            <div className="agent-messages">
              {messages.map((item, index) => (
                <div className={`agent-message ${item.role}`} key={`${item.role}-${index}`}>
                  <strong>{item.role === "agent" ? "Agent" : "教师"}</strong>
                  <p>{item.content}</p>
                </div>
              ))}
            </div>
            {bestCandidate ? (
              <div className="candidate-summary">
                <strong>当前候选</strong>
                <span>{bestCandidate.title}@{bestCandidate.semver}</span>
                <span>匹配 {Math.round(bestCandidate.score * 100)}%</span>
              </div>
            ) : null}
            {authoringProposal ? (
              <div className="candidate-summary">
                <strong>Agent 提案</strong>
                <span>{proposalModeLabel(authoringProposal.mode)}</span>
                <span>{authoringProposal.title}</span>
              </div>
            ) : null}
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="继续描述题目目标、难度、时间、知识点或发布要求"
            />
            <button className="iconbutton primary" type="button" onClick={sendToAgent} disabled={loading !== ""}>
              <Send size={16} /> {loading === "agent" ? "Agent 处理中" : "发送给 Agent"}
            </button>
          </aside>
        </section>
      </main>
    </TeacherWorkspaceShell>
  );
}

function initialPreview(): PreviewState {
  return {
    courseId: DEFAULT_COURSE_ID,
    challengeVersionId: DEFAULT_VERSION_ID,
    title: "Web 登录认证绕过实践",
    summary: "通过终端访问目标 Web 服务，观察登录接口在异常输入下的认证边界。",
    description:
      "本题会为每位学生启动独立的 Web 目标服务。进入题目后先获取容器环境，再打开题目给出的目标地址。建议从健康检查接口开始确认服务可访问，然后围绕登录接口构造请求，观察正常账号、错误密码和特殊输入的返回差异。",
    requirements:
      "完成时需要提交根因解释，说明认证逻辑为什么会被绕过、哪些输入会触发问题、应如何改成参数化查询或等价的安全实现。",
    tags: "Web安全, 认证, SQL注入, 终端实践"
  };
}

function proposalModeLabel(value: string): string {
  if (value === "GENERATE_CUSTOM") return "生成定制靶场";
  if (value === "COMPOSE_EXISTING") return "组合题库候选";
  return "使用题库候选";
}

function buildConversationBrief(items: ChatMessage[]): string {
  const teacherTurns = items.filter((item) => item.role === "teacher");
  return teacherTurns
    .map((item, index) => `教师第 ${index + 1} 轮：${item.content}`)
    .join("\n");
}

function buildLayerOnePrompt(
  preview: PreviewState,
  messages: ChatMessage[],
  candidateSearch: ChallengeCandidateSearchResponse | null,
  publish: boolean
): string {
  const conversation = messages.map((item) => `${item.role === "teacher" ? "教师" : "Agent"}：${item.content}`).join("\n");
  const candidates = (candidateSearch?.candidates ?? [])
    .slice(0, 5)
    .map((item, index) => `${index + 1}. ${item.title} (${item.challengeVersionId}) 匹配 ${Math.round(item.score * 100)}%`)
    .join("\n");
  return [
    "第一层需求 Agent 已将教师对话收敛为第二层环境构建任务。",
    `发布模式：${publish ? "创建并发布" : "创建未发布草稿"}`,
    `课程 ID：${preview.courseId}`,
    `题目版本 ID：${preview.challengeVersionId}`,
    `题目标题：${preview.title}`,
    `列表摘要：${preview.summary}`,
    `题目说明：${preview.description}`,
    `完成要求：${preview.requirements}`,
    `标签：${preview.tags}`,
    "教师和 Agent 对话：",
    conversation || "无额外对话",
    "题库候选：",
    candidates || "无候选，按定制靶场草稿处理",
    "第二层必须生成可审核的完整题目环境，第三层必须模拟真实学生解题并生成评分标准。"
  ].join("\n");
}

function initialPipelineSteps(title: string): AuthoringPipelineStepResponse[] {
  return [
    {
      layer: "L1_REQUIREMENT_AGENT",
      agent: "需求对齐 Agent",
      iteration: 1,
      status: "DONE",
      title: "锁定教师需求与出题提示词",
      detail: `已准备将“${title}”交给第二层环境构建 Agent。`,
      artifacts: ["authoring_prompt.md"],
      feedback: []
    },
    {
      layer: "L2_BUILDER_AGENT",
      agent: "环境构建 Agent",
      iteration: 1,
      status: "RUNNING",
      title: "生成题目环境",
      detail: "正在生成目标服务/程序、工作区、拓扑、验证器和参考测试。",
      artifacts: [],
      feedback: []
    },
    {
      layer: "L3_TESTER_AGENT",
      agent: "做题验证 Agent",
      iteration: 1,
      status: "WAITING",
      title: "等待模拟做题验证",
      detail: "第二层生成完成后会按学生视角验证入口、漏洞路径、提交材料和评分标准。",
      artifacts: [],
      feedback: []
    }
  ];
}

function rubricTotal(rubric: Record<string, unknown>): number {
  const value = rubric.totalScore;
  return typeof value === "number" ? value : 0;
}

function rubricCriteriaCount(rubric: Record<string, unknown>): number {
  return Array.isArray(rubric.criteria) ? rubric.criteria.length : 0;
}

function formatAgentReply(
  fieldUpdate: AuthoringFieldUpdate,
  proposalMode: string,
  proposalTitle: string,
  candidateTitle: string,
  score: number,
  generatedVersionId: string
): string {
  const parts: string[] = [];
  if (fieldUpdate.labels.length) {
    parts.push(`已更新：${fieldUpdate.labels.join("；")}。`);
  }
  if (generatedVersionId) {
    parts.push(`已生成定制草稿 ${generatedVersionId}，发布前仍需审核验证。`);
  } else if (!fieldUpdate.labels.length) {
    const title = candidateTitle || proposalTitle;
    const scoreText = score > 0 ? `，匹配 ${Math.round(score * 100)}%` : "";
    parts.push(`已更新题目卡片，当前候选：${title || proposalMode}${scoreText}。`);
  } else if (candidateTitle) {
    parts.push(`当前候选保持为“${candidateTitle}”。`);
  }
  return parts.filter(Boolean).join("\n");
}

function defaultWindow() {
  const openAt = new Date();
  const dueAt = new Date(openAt.getTime() + 2 * 60 * 60 * 1000);
  return { openAt: toLocalInput(openAt.toISOString()), dueAt: toLocalInput(dueAt.toISOString()), mode: "duration" as const };
}

function emptyWindow(): PublishWindow {
  return { openAt: "", dueAt: "" };
}

function toApiWindow(value: PublishWindow) {
  return { openAt: toIso(value.openAt), dueAt: toIso(value.dueAt) };
}

function toIso(value: string): string {
  return new Date(value).toISOString();
}

function parseTags(value: string): string[] {
  return value
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
    .slice(0, 20);
}

function readError(err: unknown): string {
  return err instanceof Error ? err.message : "UNKNOWN_ERROR";
}
