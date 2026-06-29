"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArchiveRestore,
  BookOpenCheck,
  CalendarClock,
  Eye,
  Plus,
  RefreshCw,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import {
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
import { TeacherWorkspaceShell } from "./TeacherWorkspaceShell";

const DEFAULT_COURSE_ID = "course_websec";

type BankView = "active" | "trash";

export function TeacherChallengeBankPage() {
  const [view, setView] = useState<BankView>("active");
  const [courseId, setCourseId] = useState(DEFAULT_COURSE_ID);
  const [items, setItems] = useState<ChallengeBankItemResponse[]>([]);
  const [detailId, setDetailId] = useState("");
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
      return;
    }
    const createdId = new URLSearchParams(window.location.search).get("created") ?? "";
    if (createdId) {
      setMessage("题目已创建，已为你定位到新题目。");
    }
    void loadItems("active", createdId);
  }, []);

  const detailItem = useMemo(
    () => items.find((item) => item.itemId === detailId) ?? null,
    [items, detailId]
  );

  async function loadItems(nextView = view, preferredDetailId = "") {
    setError("");
    setLoading("list");
    try {
      const result =
        nextView === "trash"
          ? await fetchTeacherChallengeBankTrash(courseId)
          : await fetchTeacherChallengeBank(courseId);
      setItems(result.items);
      setView(nextView);
      setDetailId((current) => {
        const targetId = preferredDetailId || current;
        return result.items.some((item) => item.itemId === targetId) ? targetId : "";
      });
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function saveItem(item: ChallengeBankItemResponse, form: DetailFormState) {
    setError("");
    setMessage("");
    setLoading("save");
    try {
      await updateChallengeBankItem(item.itemId, {
        courseId: form.courseId.trim(),
        title: form.title.trim(),
        summary: form.summary.trim(),
        description: form.description.trim(),
        requirements: form.requirements.trim(),
        tags: parseTags(form.tags),
        openAt: toIso(form.openAt),
        dueAt: toIso(form.dueAt)
      });
      setMessage("题目内容已保存。");
      await loadItems(view);
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function publishItem(item: ChallengeBankItemResponse, openAt: string, dueAt: string) {
    setError("");
    setMessage("");
    setLoading("publish");
    try {
      await publishChallengeBankItem(item.itemId, toIso(openAt), toIso(dueAt));
      setMessage("题目已发布，学生端会按时间窗口显示。");
      await loadItems("active");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function unpublishItem(item: ChallengeBankItemResponse) {
    setError("");
    setMessage("");
    setLoading("unpublish");
    try {
      await unpublishChallengeBankItem(item.itemId);
      setMessage("题目已下架，可以继续编辑。");
      await loadItems("active");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function deleteItem(item: ChallengeBankItemResponse) {
    setError("");
    setMessage("");
    setLoading("delete");
    try {
      await deleteChallengeBankItem(item.itemId);
      setMessage("题目已移入回收站。");
      setDetailId("");
      await loadItems("active");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function restoreItem(item: ChallengeBankItemResponse) {
    setError("");
    setMessage("");
    setLoading("restore");
    try {
      await restoreChallengeBankItem(item.itemId);
      setMessage("题目已恢复为未发布状态。");
      setDetailId("");
      await loadItems("trash");
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  return (
    <TeacherWorkspaceShell active="bank">
      <main className="teacher-main">
        <header className="teacher-page-header">
          <div>
            <h1>题库</h1>
            <span>{items.length} 个题目 · {view === "trash" ? "回收站" : "当前列表"}</span>
          </div>
          <div className="registry-actions">
            <Link className="iconbutton" href="/teacher/challenges/registry">
              <BookOpenCheck size={16} /> 版本 Registry
            </Link>
            <Link className="iconbutton primary" href="/teacher/challenge-bank/new">
              <Plus size={16} /> 创建题目
            </Link>
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
        </section>

        <section className="teacher-bank-grid">
          {items.map((item) => (
            <button className="bank-row" key={item.itemId} type="button" onClick={() => setDetailId(item.itemId)}>
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
          {items.length === 0 ? (
            <div className="empty-state">{loading === "list" ? "加载中" : "暂无题目"}</div>
          ) : null}
        </section>
      </main>

      {detailItem ? (
        <ChallengeDetailModal
          key={detailItem.itemId}
          item={detailItem}
          loading={loading}
          onClose={() => setDetailId("")}
          onDelete={deleteItem}
          onPublish={publishItem}
          onRestore={restoreItem}
          onSave={saveItem}
          onUnpublish={unpublishItem}
        />
      ) : null}
    </TeacherWorkspaceShell>
  );
}

type DetailFormState = {
  courseId: string;
  title: string;
  summary: string;
  description: string;
  requirements: string;
  tags: string;
  openAt: string;
  dueAt: string;
};

function ChallengeDetailModal({
  item,
  loading,
  onClose,
  onDelete,
  onPublish,
  onRestore,
  onSave,
  onUnpublish
}: {
  item: ChallengeBankItemResponse;
  loading: string;
  onClose: () => void;
  onDelete: (item: ChallengeBankItemResponse) => Promise<void>;
  onPublish: (item: ChallengeBankItemResponse, openAt: string, dueAt: string) => Promise<void>;
  onRestore: (item: ChallengeBankItemResponse) => Promise<void>;
  onSave: (item: ChallengeBankItemResponse, form: DetailFormState) => Promise<void>;
  onUnpublish: (item: ChallengeBankItemResponse) => Promise<void>;
}) {
  const [form, setForm] = useState<DetailFormState>(() => ({
    courseId: item.courseId,
    title: item.title,
    summary: item.summary,
    description: item.description,
    requirements: item.requirements,
    tags: item.tags.join(", "),
    openAt: toLocalInput(item.openAt),
    dueAt: toLocalInput(item.dueAt)
  }));
  const [windowValue, setWindowValue] = useState(() => ({
    openAt: toLocalInput(item.openAt),
    dueAt: toLocalInput(item.dueAt)
  }));
  const editable = item.actions.canEdit;
  const publishWindowReady = form.openAt !== "" && form.dueAt !== "";

  useEffect(() => {
    const fallback = defaultWindow();
    setForm((current) => ({
      ...current,
      openAt: current.openAt || fallback.openAt,
      dueAt: current.dueAt || fallback.dueAt
    }));
    setWindowValue((current) => ({
      openAt: current.openAt || fallback.openAt,
      dueAt: current.dueAt || fallback.dueAt
    }));
  }, []);

  return (
    <div className="modal-backdrop" role="presentation">
      <article className="challenge-detail-modal" role="dialog" aria-modal="true" aria-label="题目详细信息">
        <header className="modal-header">
          <div>
            <span className={`pill ${item.publishState === "ACTIVE" ? "good" : "warn"}`}>
              {stateLabel(item.publishState)}
            </span>
            <h2>{item.title}</h2>
          </div>
          <button className="iconbutton" type="button" onClick={onClose}>
            <X size={16} /> 关闭
          </button>
        </header>

        <div className="modal-body-grid">
          <section className="modal-section">
            <h3>题目内容</h3>
            {editable ? (
              <>
                <label className="field-label">课程 ID</label>
                <input
                  value={form.courseId}
                  onChange={(event) => setForm({ ...form, courseId: event.target.value })}
                />
                <label className="field-label">标题</label>
                <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
                <label className="field-label">列表摘要</label>
                <input
                  value={form.summary}
                  onChange={(event) => setForm({ ...form, summary: event.target.value })}
                />
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
                <div className="status-note">
                  保存这些展示信息不会修改题目环境、代码、镜像或已开启的学生容器。
                </div>
              </>
            ) : (
              <div className="detail-copy">
                <p>{item.summary}</p>
                <h4>题目说明</h4>
                <p>{item.description}</p>
                <h4>完成要求</h4>
                <p>{item.requirements}</p>
              </div>
            )}
          </section>

          <section className="modal-section">
            <h3>发布与版本</h3>
            <div className="intent-grid">
              <span>状态</span>
              <strong>{item.status} / {stateLabel(item.publishState)}</strong>
              <span>作业</span>
              <strong>{item.assignmentId ?? "未创建"}</strong>
              <span>版本</span>
              <strong>{item.version.title}@{item.version.semver}</strong>
              <span>验证</span>
              <strong>{item.version.validationStatus}</strong>
              <span>标签</span>
              <strong>{item.tags.join("、") || "未设置"}</strong>
            </div>

            <div className="publish-grid">
              <label>
                开始时间
                <input
                  type="datetime-local"
                  value={editable ? form.openAt : windowValue.openAt}
                  onChange={(event) => {
                    setForm({ ...form, openAt: event.target.value });
                    setWindowValue({ ...windowValue, openAt: event.target.value });
                  }}
                  disabled={!editable}
                />
              </label>
              <label>
                结束时间
                <input
                  type="datetime-local"
                  value={editable ? form.dueAt : windowValue.dueAt}
                  onChange={(event) => {
                    setForm({ ...form, dueAt: event.target.value });
                    setWindowValue({ ...windowValue, dueAt: event.target.value });
                  }}
                  disabled={!editable}
                />
              </label>
            </div>
          </section>
        </div>

        <footer className="modal-actions">
          <button
            className="iconbutton"
            type="button"
            onClick={() => onSave(item, form)}
            disabled={!item.actions.canEdit || loading !== "" || !publishWindowReady}
          >
            保存修改
          </button>
          <button
            className="iconbutton primary"
            type="button"
            onClick={() => onPublish(item, form.openAt, form.dueAt)}
            disabled={!item.actions.canPublish || loading !== "" || !publishWindowReady}
          >
            <UploadCloud size={16} /> 发布
          </button>
          <button
            className="iconbutton"
            type="button"
            onClick={() => onUnpublish(item)}
            disabled={!item.actions.canUnpublish || loading !== ""}
          >
            <ArchiveRestore size={16} /> 下架
          </button>
          <button
            className="iconbutton"
            type="button"
            onClick={() => onDelete(item)}
            disabled={!item.actions.canDelete || loading !== ""}
          >
            <Trash2 size={16} /> 删除
          </button>
          <button
            className="iconbutton"
            type="button"
            onClick={() => onRestore(item)}
            disabled={!item.actions.canRestore || loading !== ""}
          >
            <ArchiveRestore size={16} /> 恢复
          </button>
        </footer>
      </article>
    </div>
  );
}

function defaultWindow() {
  const openAt = new Date();
  const dueAt = new Date(openAt.getTime() + 2 * 60 * 60 * 1000);
  return { openAt: toLocalInput(openAt.toISOString()), dueAt: toLocalInput(dueAt.toISOString()) };
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
