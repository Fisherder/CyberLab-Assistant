"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, CalendarClock, Plus, Send, UploadCloud } from "lucide-react";
import {
  createChallengeBankItem,
  createChallengeDraft,
  fetchChallengeCandidates,
  generateCustomChallengePackage,
  hasAuthToken,
  type ChallengeCandidateSearchResponse
} from "../lib/api";
import { TeacherWorkspaceShell } from "./TeacherWorkspaceShell";

const DEFAULT_COURSE_ID = "course_websec";
const DEFAULT_VERSION_ID = "cv_web_sqli_auth_1_3_0";

type ChatMessage = {
  role: "teacher" | "agent";
  content: string;
};

type PreviewState = {
  courseId: string;
  challengeVersionId: string;
  title: string;
  summary: string;
  description: string;
  requirements: string;
  tags: string;
};

type PublishWindow = {
  openAt: string;
  dueAt: string;
};

type PublishWindowUpdate = {
  window: PublishWindow;
  label: string;
};

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
      const publishUpdate = inferPublishWindowUpdate(text, publishWindow);
      const activePublishWindow = publishUpdate?.window ?? publishWindow;
      if (publishUpdate) {
        setPublishWindow(publishUpdate.window);
      }
      const brief = buildConversationBrief(nextMessages);
      const draft = await createChallengeDraft(preview.courseId, brief, {
        internet: false,
        maxDifficulty: 5,
        workspaceType: "TERMINAL",
        authoringConversation: nextMessages,
        latestTeacherMessage: text,
        currentPreview: preview,
        currentPublishWindow: activePublishWindow
      });
      const candidates = await fetchChallengeCandidates(draft.candidatesUrl);
      setCandidateSearch(candidates);
      const proposal = candidates.authoringProposal;
      let challengeVersionId = proposal.challengeVersionId ?? candidates.candidates[0]?.challengeVersionId ?? preview.challengeVersionId;
      let agentMessage = proposal.agentMessage;
      if (proposal.requiresCustomGeneration) {
        const generated = await generateCustomChallengePackage(draft.draftId);
        challengeVersionId = generated.challengeVersionId;
        const generatedFiles = Array.isArray(generated.modelDraft.generatedFiles)
          ? generated.modelDraft.generatedFiles.map(String)
          : proposal.generatedFiles;
        agentMessage = [
          proposal.agentMessage,
          `已生成定制靶场代码包草稿 ${generated.challengeVersionId}。`,
          generatedFiles.length ? `生成文件：${generatedFiles.slice(0, 8).join("、")}。` : "",
          "请在发布前查看验证报告并完成教师审核。"
        ]
          .filter(Boolean)
          .join("\n");
      }
      setPreview((current) => ({
        ...current,
        challengeVersionId,
        title: proposal.title,
        summary: proposal.summary,
        description: proposal.description,
        requirements: proposal.requirements,
        tags: proposal.tags.join(", ")
      }));
      setMessages((current) => [
        ...current,
        {
          role: "agent",
          content: formatAgentReply(agentMessage, publishUpdate)
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
    if (nextPublish && !publishWindowReady) {
      setError("请先设置完整的开始时间和结束时间。");
      return;
    }
    setLoading(nextPublish ? "publish" : "create");
    try {
      const item = await createChallengeBankItem({
        courseId: preview.courseId.trim(),
        challengeVersionId: preview.challengeVersionId.trim(),
        title: preview.title.trim(),
        summary: preview.summary.trim(),
        description: preview.description.trim(),
        requirements: preview.requirements.trim(),
        tags: parseTags(preview.tags),
        publish: nextPublish,
        publishWindow: nextPublish ? toApiWindow(publishWindow) : null
      });
      setMessage(nextPublish ? "题目已创建并发布。" : "题目已创建为未发布草稿。");
      window.location.href = `/teacher/challenge-bank?created=${encodeURIComponent(item.itemId)}`;
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
        {message ? <div className="status-note">{message}</div> : null}

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

function formatAgentReply(agentMessage: string, publishUpdate: PublishWindowUpdate | null): string {
  const parts = [agentMessage.trim()];
  if (publishUpdate) {
    parts.push(`发布设置已更新：${publishUpdate.label}。`);
  }
  return parts.filter(Boolean).join("\n");
}

function defaultWindow() {
  const openAt = new Date();
  const dueAt = new Date(openAt.getTime() + 2 * 60 * 60 * 1000);
  return { openAt: toLocalInput(openAt.toISOString()), dueAt: toLocalInput(dueAt.toISOString()) };
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

function toLocalInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function inferPublishWindowUpdate(text: string, current: PublishWindow): PublishWindowUpdate | null {
  if (!/(发布|开放|截止|持续|时间)/.test(text)) return null;
  const duration = parseDuration(text);
  if (!duration) return null;
  const openAt = current.openAt ? new Date(toIso(current.openAt)) : new Date();
  const dueAt = addDuration(openAt, duration.amount, duration.unit);
  const window = {
    openAt: toLocalInput(openAt.toISOString()),
    dueAt: toLocalInput(dueAt.toISOString())
  };
  return {
    window,
    label: `${formatLocalDateTime(window.openAt)} 至 ${formatLocalDateTime(window.dueAt)}`
  };
}

function parseDuration(text: string): { amount: number; unit: "year" | "month" | "week" | "day" | "hour" } | null {
  if (/半年/.test(text)) return { amount: 6, unit: "month" };
  const match = text.match(/([0-9]+|[一二两三四五六七八九十]+)\s*(年|个月|月|周|星期|天|日|小时)/);
  if (!match) return null;
  const amount = parseDurationAmount(match[1]);
  if (!amount) return null;
  const unitText = match[2];
  if (unitText === "年") return { amount, unit: "year" };
  if (unitText === "个月" || unitText === "月") return { amount, unit: "month" };
  if (unitText === "周" || unitText === "星期") return { amount, unit: "week" };
  if (unitText === "小时") return { amount, unit: "hour" };
  return { amount, unit: "day" };
}

function parseDurationAmount(value: string): number {
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) return numeric;
  const digits: Record<string, number> = {
    一: 1,
    二: 2,
    两: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9
  };
  if (value === "十") return 10;
  if (value.includes("十")) {
    const [left, right] = value.split("十");
    const tens = left ? digits[left] ?? 0 : 1;
    const ones = right ? digits[right] ?? 0 : 0;
    return tens * 10 + ones;
  }
  return digits[value] ?? 0;
}

function addDuration(date: Date, amount: number, unit: "year" | "month" | "week" | "day" | "hour"): Date {
  const next = new Date(date.getTime());
  if (unit === "year") next.setFullYear(next.getFullYear() + amount);
  if (unit === "month") next.setMonth(next.getMonth() + amount);
  if (unit === "week") next.setDate(next.getDate() + amount * 7);
  if (unit === "day") next.setDate(next.getDate() + amount);
  if (unit === "hour") next.setHours(next.getHours() + amount);
  return next;
}

function formatLocalDateTime(value: string): string {
  return value.replace("T", " ");
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
