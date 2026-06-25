"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, CalendarClock, Plus, Send, UploadCloud } from "lucide-react";
import {
  createChallengeBankItem,
  createChallengeDraft,
  fetchChallengeCandidates,
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
  const [publishWindow, setPublishWindow] = useState(defaultWindow());
  const [candidateSearch, setCandidateSearch] = useState<ChallengeCandidateSearchResponse | null>(null);
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
    }
  }, []);

  const bestCandidate = useMemo(() => candidateSearch?.candidates[0] ?? null, [candidateSearch]);

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
      const brief = nextMessages
        .filter((item) => item.role === "teacher")
        .map((item) => item.content)
        .join("\n");
      const draft = await createChallengeDraft(preview.courseId, brief, {
        internet: false,
        maxDifficulty: 3,
        workspaceType: "TERMINAL"
      });
      const candidates = await fetchChallengeCandidates(draft.candidatesUrl);
      setCandidateSearch(candidates);
      const candidate = candidates.candidates[0];
      const intent = draft.courseIntent;
      setPreview((current) => ({
        ...current,
        challengeVersionId: candidate?.challengeVersionId ?? current.challengeVersionId,
        title: titleFromBrief(text, candidate?.title ?? current.title),
        summary: `面向 ${intent.target || "课程目标"} 的 ${intent.category} 终端实践，预计 ${intent.expectedMinutes || 75} 分钟。`,
        description: buildDescription(text, candidate?.title ?? current.title),
        requirements: buildRequirements(text),
        tags: normalizeTags([intent.category, intent.target, "终端实践", "容器环境"])
      }));
      setMessages((current) => [
        ...current,
        {
          role: "agent",
          content: candidate
            ? `已检索到候选版本 ${candidate.title}@${candidate.semver}，我已把题目详情卡片更新为可发布版本。`
            : "没有找到完全匹配的候选题，我先保留当前默认题目版本，并根据你的描述更新题面。"
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
                disabled={loading !== ""}
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

function titleFromBrief(brief: string, fallback: string): string {
  const trimmed = brief.replace(/[。.!！?？]/g, " ").trim();
  if (trimmed.length >= 8 && trimmed.length <= 28) return trimmed;
  return fallback;
}

function buildDescription(brief: string, candidateTitle: string): string {
  return `题目基于“${candidateTitle}”版本创建。学生进入题目后先获取容器环境，再根据目标地址访问服务。教师需求：${brief}`;
}

function buildRequirements(brief: string): string {
  return `学生需要完成操作验证，并提交根因说明、验证过程和修复建议。教师补充要求：${brief}`;
}

function normalizeTags(values: string[]): string {
  return values
    .map((value) => value.trim())
    .filter(Boolean)
    .slice(0, 6)
    .join(", ");
}

function defaultWindow() {
  const openAt = new Date();
  const dueAt = new Date(openAt.getTime() + 2 * 60 * 60 * 1000);
  return { openAt: toLocalInput(openAt.toISOString()), dueAt: toLocalInput(dueAt.toISOString()) };
}

function toApiWindow(value: { openAt: string; dueAt: string }) {
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
