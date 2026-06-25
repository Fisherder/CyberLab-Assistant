"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArchiveRestore,
  ArrowLeft,
  BookOpenCheck,
  CalendarClock,
  Eye,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  UploadCloud
} from "lucide-react";
import {
  createChallengeBankItem,
  deleteChallengeBankItem,
  fetchTeacherChallengeBank,
  fetchTeacherChallengeBankTrash,
  hasAuthToken,
  publishChallengeBankItem,
  restoreChallengeBankItem,
  unpublishChallengeBankItem,
  updateChallengeBankItem,
  type ChallengeBankItemResponse
} from "../lib/api";

const DEFAULT_COURSE_ID = "course_websec";
const DEFAULT_VERSION_ID = "cv_web_sqli_auth_1_3_0";

type BankView = "active" | "trash";

export function TeacherChallengeBankPage() {
  const [view, setView] = useState<BankView>("active");
  const [courseId, setCourseId] = useState(DEFAULT_COURSE_ID);
  const [items, setItems] = useState<ChallengeBankItemResponse[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [form, setForm] = useState(() => initialForm());
  const [publishNow, setPublishNow] = useState(false);
  const [publishWindow, setPublishWindow] = useState(defaultWindow());

  useEffect(() => {
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
      return;
    }
    void loadItems("active");
  }, []);

  const selected = useMemo(
    () => items.find((item) => item.itemId === selectedId) ?? items[0] ?? null,
    [items, selectedId]
  );

  async function loadItems(nextView = view) {
    setError("");
    setLoading("list");
    try {
      const result =
        nextView === "trash"
          ? await fetchTeacherChallengeBankTrash(courseId)
          : await fetchTeacherChallengeBank(courseId);
      setItems(result.items);
      setView(nextView);
      setSelectedId((current) => {
        if (result.items.some((item) => item.itemId === current)) return current;
        return result.items[0]?.itemId ?? "";
      });
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function createItem() {
    setError("");
    setMessage("");
    setLoading("create");
    try {
      const item = await createChallengeBankItem({
        courseId: form.courseId.trim(),
        challengeVersionId: form.challengeVersionId.trim(),
        title: form.title.trim(),
        summary: form.summary.trim(),
        description: form.description.trim(),
        requirements: form.requirements.trim(),
        tags: parseTags(form.tags),
        publish: publishNow,
        publishWindow: publishNow ? toApiWindow(publishWindow) : null
      });
      setMessage(publishNow ? "题目已创建并发布。" : "题目已保存为草稿。");
      setCourseId(form.courseId.trim());
      await loadItems("active");
      setSelectedId(item.itemId);
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function saveSelected() {
    if (!selected) return;
    setError("");
    setMessage("");
    setLoading("save");
    try {
      await updateChallengeBankItem(selected.itemId, {
        title: form.title.trim(),
        summary: form.summary.trim(),
        description: form.description.trim(),
        requirements: form.requirements.trim(),
        tags: parseTags(form.tags)
      });
      setMessage("题目内容已保存。");
      await loadItems(view);
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function publishSelected() {
    if (!selected) return;
    setError("");
    setMessage("");
    setLoading("publish");
    try {
      await publishChallengeBankItem(selected.itemId, toIso(publishWindow.openAt), toIso(publishWindow.dueAt));
      setMessage("题目已发布，学生端会按时间窗口显示。");
      await loadItems("active");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function unpublishSelected() {
    if (!selected) return;
    setError("");
    setMessage("");
    setLoading("unpublish");
    try {
      await unpublishChallengeBankItem(selected.itemId);
      setMessage("题目已下架，可以继续编辑。");
      await loadItems("active");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function deleteSelected() {
    if (!selected) return;
    setError("");
    setMessage("");
    setLoading("delete");
    try {
      await deleteChallengeBankItem(selected.itemId);
      setMessage("题目已移入回收站。");
      await loadItems("active");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function restoreSelected() {
    if (!selected) return;
    setError("");
    setMessage("");
    setLoading("restore");
    try {
      await restoreChallengeBankItem(selected.itemId);
      setMessage("题目已恢复为未发布状态。");
      await loadItems("trash");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  function fillFromSelected(item: ChallengeBankItemResponse) {
    setSelectedId(item.itemId);
    setForm({
      courseId: item.courseId,
      challengeVersionId: item.challengeVersionId,
      title: item.title,
      summary: item.summary,
      description: item.description,
      requirements: item.requirements,
      tags: item.tags.join(", ")
    });
    setPublishWindow({
      openAt: toLocalInput(item.openAt) || publishWindow.openAt,
      dueAt: toLocalInput(item.dueAt) || publishWindow.dueAt
    });
  }

  return (
    <main className="registry-shell">
      <header className="registry-header">
        <div>
          <Link className="backlink" href="/">
            <ArrowLeft size={16} /> Workbench
          </Link>
          <h1>教师题库</h1>
          <span>{items.length} 个题目 · {view === "trash" ? "回收站" : "当前列表"}</span>
        </div>
        <div className="registry-actions">
          <Link className="iconbutton" href="/teacher/challenges/registry">
            <BookOpenCheck size={16} /> 版本 Registry
          </Link>
          <button className="iconbutton" type="button" onClick={() => loadItems(view)} disabled={loading !== ""}>
            <RefreshCw size={16} /> 刷新
          </button>
          <button
            className="iconbutton"
            type="button"
            onClick={() => loadItems(view === "trash" ? "active" : "trash")}
            disabled={loading !== ""}
          >
            {view === "trash" ? <Eye size={16} /> : <Trash2 size={16} />}
            {view === "trash" ? "当前题库" : "回收站"}
          </button>
        </div>
      </header>

      {error ? <div className="error banner">{error}</div> : null}
      {message ? <div className="status-note">{message}</div> : null}

      <section className="registry-toolbar">
        <label>
          <BookOpenCheck size={16} />
          <input value={courseId} onChange={(event) => setCourseId(event.target.value)} />
        </label>
        <button className="iconbutton" type="button" onClick={() => loadItems(view)} disabled={loading !== ""}>
          <RefreshCw size={16} /> 按课程加载
        </button>
      </section>

      <section className="bank-layout">
        <div className="registry-list">
          {items.map((item) => (
            <button
              className={item.itemId === selected?.itemId ? "bank-row selected" : "bank-row"}
              key={item.itemId}
              type="button"
              onClick={() => fillFromSelected(item)}
            >
              <div>
                <strong>{item.title}</strong>
                <span>{item.summary}</span>
              </div>
              <div className="registry-row-meta">
                <span className={`pill ${item.publishState === "ACTIVE" ? "good" : "warn"}`}>
                  {stateLabel(item.publishState)}
                </span>
                <span className="pill">{item.status}</span>
                <span>{formatDate(item.openAt)} - {formatDate(item.dueAt)}</span>
              </div>
            </button>
          ))}
          {items.length === 0 ? <div className="empty-state">{loading === "list" ? "加载中" : "暂无题目"}</div> : null}
        </div>

        <aside className="bank-editor">
          <section className="authoring-section">
            <div className="authoring-title">
              <Plus size={17} />
              <h2>创建或编辑题目</h2>
            </div>
            <label className="field-label">课程 ID</label>
            <input value={form.courseId} onChange={(event) => setForm({ ...form, courseId: event.target.value })} />
            <label className="field-label">题目版本 ID</label>
            <input
              value={form.challengeVersionId}
              onChange={(event) => setForm({ ...form, challengeVersionId: event.target.value })}
            />
            <label className="field-label">题目标题</label>
            <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
            <label className="field-label">列表摘要</label>
            <input value={form.summary} onChange={(event) => setForm({ ...form, summary: event.target.value })} />
            <label className="field-label">题目说明</label>
            <textarea
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
            <label className="field-label">完成要求</label>
            <textarea
              value={form.requirements}
              onChange={(event) => setForm({ ...form, requirements: event.target.value })}
            />
            <label className="field-label">标签</label>
            <input value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} />

            <div className="bank-actionbar">
              <label className="inline-check">
                <input type="checkbox" checked={publishNow} onChange={(event) => setPublishNow(event.target.checked)} />
                创建后立即发布
              </label>
              <button className="iconbutton primary" type="button" onClick={createItem} disabled={loading !== ""}>
                <Plus size={16} /> 创建
              </button>
              <button
                className="iconbutton"
                type="button"
                onClick={saveSelected}
                disabled={!selected?.actions.canEdit || loading !== ""}
              >
                <Pencil size={16} /> 保存选中题目
              </button>
            </div>
          </section>

          <section className="authoring-section">
            <div className="authoring-title">
              <CalendarClock size={17} />
              <h2>发布窗口</h2>
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
            <div className="bank-actionbar">
              <button
                className="iconbutton primary"
                type="button"
                onClick={publishSelected}
                disabled={!selected?.actions.canPublish || loading !== ""}
              >
                <UploadCloud size={16} /> 发布
              </button>
              <button
                className="iconbutton"
                type="button"
                onClick={unpublishSelected}
                disabled={!selected?.actions.canUnpublish || loading !== ""}
              >
                <ArchiveRestore size={16} /> 下架
              </button>
              <button
                className="iconbutton"
                type="button"
                onClick={deleteSelected}
                disabled={!selected?.actions.canDelete || loading !== ""}
              >
                <Trash2 size={16} /> 删除
              </button>
              <button
                className="iconbutton"
                type="button"
                onClick={restoreSelected}
                disabled={!selected?.actions.canRestore || loading !== ""}
              >
                <ArchiveRestore size={16} /> 恢复
              </button>
            </div>
          </section>

          {selected ? (
            <section className="authoring-section">
              <h3>选中题目</h3>
              <div className="intent-grid">
                <span>状态</span>
                <strong>{selected.status} / {stateLabel(selected.publishState)}</strong>
                <span>作业</span>
                <strong>{selected.assignmentId ?? "未创建"}</strong>
                <span>版本</span>
                <strong>{selected.version.title}@{selected.version.semver}</strong>
                <span>验证</span>
                <strong>{selected.version.validationStatus}</strong>
              </div>
            </section>
          ) : null}
        </aside>
      </section>
    </main>
  );
}

function initialForm() {
  return {
    courseId: DEFAULT_COURSE_ID,
    challengeVersionId: DEFAULT_VERSION_ID,
    title: "Web 登录认证绕过实践",
    summary: "通过终端访问目标 Web 服务，观察登录接口在异常输入下的认证边界。",
    description:
      "本题会为每位学生启动独立的 Web 目标服务。进入题目后先获取容器环境，再打开题目给出的目标地址。建议从健康检查接口开始确认服务可访问，然后围绕登录接口构造请求，观察正常账号、错误密码和特殊输入的返回差异。",
    requirements:
      "完成时需要提交根因解释，说明认证逻辑为什么会被绕过、哪些输入会触发问题、应如何改成参数化查询或等价的安全实现。学生提交后系统会结合外部 Oracle、终端事件和答案解释给出证据化成绩。",
    tags: "Web安全, 认证, SQL注入, 终端实践"
  };
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

function formatDate(value: string | null): string {
  if (!value) return "未设置";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function stateLabel(value: string): string {
  if (value === "ACTIVE") return "进行中";
  if (value === "NOT_STARTED") return "未开始";
  if (value === "ENDED") return "已结束";
  if (value === "DELETED") return "已删除";
  return "未发布";
}

function readError(err: unknown): string {
  return err instanceof Error ? err.message : "UNKNOWN_ERROR";
}
