"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpenCheck,
  Clock,
  ExternalLink,
  Play,
  RefreshCw,
  TerminalSquare,
  Trash2
} from "lucide-react";
import {
  destroyStudentChallengeBankEnvironment,
  fetchStudentChallengeBank,
  hasAuthToken,
  startStudentChallengeBankItem,
  type StartChallengeBankItemResponse,
  type StudentChallengeBankItemResponse
} from "../lib/api";

export function StudentChallengeBankPage() {
  const [items, setItems] = useState<StudentChallengeBankItemResponse[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [started, setStarted] = useState<Record<string, StartChallengeBankItemResponse>>({});
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
    void loadItems();
  }, []);

  const selected = useMemo(
    () => items.find((item) => item.itemId === selectedId) ?? items[0] ?? null,
    [items, selectedId]
  );
  const selectedStart = selected ? started[selected.itemId] : null;
  const hasEnvironment = Boolean(selectedStart || selected?.hasEnvironment);

  async function loadItems() {
    setError("");
    setLoading("list");
    try {
      const result = await fetchStudentChallengeBank();
      setItems(result.items);
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

  async function startSelected() {
    if (!selected) return;
    setError("");
    setMessage("");
    setLoading("start");
    try {
      const result = await startStudentChallengeBankItem(selected.itemId);
      setStarted((current) => ({ ...current, [selected.itemId]: result }));
      setMessage(result.reusedAttempt ? "已连接到你之前创建的环境。" : "容器环境已创建。");
      await loadItems();
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  async function destroySelected() {
    if (!selected) return;
    setError("");
    setMessage("");
    setLoading("destroy");
    try {
      await destroyStudentChallengeBankEnvironment(selected.itemId);
      setStarted((current) => {
        const next = { ...current };
        delete next[selected.itemId];
        return next;
      });
      setMessage("容器环境已销毁。");
      await loadItems();
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoading("");
    }
  }

  return (
    <main className="student-bank-shell">
      <header className="registry-header">
        <div>
          <Link className="backlink" href="/">
            <ArrowLeft size={16} /> Workbench
          </Link>
          <h1>学生题库</h1>
          <span>{items.length} 个可见题目</span>
        </div>
        <button className="iconbutton" type="button" onClick={loadItems} disabled={loading !== ""}>
          <RefreshCw size={16} /> 刷新
        </button>
      </header>

      {error ? <div className="error banner">{error}</div> : null}
      {message ? <div className="status-note">{message}</div> : null}

      <section className="student-bank-layout">
        <div className="registry-list">
          {items.map((item) => (
            <button
              className={item.itemId === selected?.itemId ? "bank-row selected" : "bank-row"}
              key={item.itemId}
              type="button"
              onClick={() => setSelectedId(item.itemId)}
            >
              <div>
                <strong>{item.title}</strong>
                <span>{item.summary}</span>
              </div>
              <div className="registry-row-meta">
                <span className={`pill ${item.publishState === "ACTIVE" ? "good" : "warn"}`}>
                  {stateLabel(item.publishState)}
                </span>
                <span>
                  {formatDate(item.openAt)} - {formatDate(item.dueAt)}
                </span>
                {item.hasEnvironment ? <span className="pill good">已获取环境</span> : null}
              </div>
            </button>
          ))}
          {items.length === 0 ? <div className="empty-state">{loading === "list" ? "加载中" : "暂无可见题目"}</div> : null}
        </div>

        <aside className="student-bank-detail">
          {selected ? (
            <>
              <section className="authoring-section">
                <div className="authoring-title">
                  <BookOpenCheck size={17} />
                  <h2>{selected.title}</h2>
                </div>
                <div className="registry-row-meta">
                  <span className={`pill ${selected.publishState === "ACTIVE" ? "good" : "warn"}`}>
                    {stateLabel(selected.publishState)}
                  </span>
                  {selected.tags.map((tag) => (
                    <span className="pill" key={tag}>{tag}</span>
                  ))}
                </div>
                <div className="student-time">
                  <Clock size={16} />
                  <span>{formatDate(selected.openAt)} - {formatDate(selected.dueAt)}</span>
                </div>
                <h3>题目说明</h3>
                <p>{selected.description}</p>
                <h3>完成要求</h3>
                <p>{selected.requirements}</p>
              </section>

              <section className="authoring-section">
                <div className="authoring-title">
                  <TerminalSquare size={17} />
                  <h2>实验环境</h2>
                </div>
                {!selected.clickable ? (
                  <div className="empty-state">{selected.disabledReason ?? "当前不能开始"}</div>
                ) : hasEnvironment ? (
                  <div className="bank-actionbar">
                    <button className="iconbutton" type="button" onClick={destroySelected} disabled={loading !== ""}>
                      <Trash2 size={16} /> 销毁容器
                    </button>
                  </div>
                ) : (
                  <div className="bank-actionbar">
                    <button className="iconbutton primary" type="button" onClick={startSelected} disabled={loading !== ""}>
                      <Play size={16} /> 获取容器
                    </button>
                  </div>
                )}

                <div className="student-targets">
                  <TargetLink
                    label="目标网站"
                    href={selectedStart?.targetUrl ?? selected.targetUrl}
                  />
                  <TargetLink
                    label="进入终端"
                    href={selectedStart?.workspaceUrl ?? selected.terminalUrl}
                  />
                  <div>
                    <span>Session</span>
                    <strong>{selectedStart?.sessionId ?? selected.sessionId ?? "尚未创建"}</strong>
                  </div>
                  <div>
                    <span>状态</span>
                    <strong>{selectedStart?.sessionStatus ?? selected.sessionStatus ?? "无运行环境"}</strong>
                  </div>
                  <div>
                    <span>Attempt</span>
                    <strong>{selectedStart?.attemptId ?? selected.attemptId ?? "尚未创建"}</strong>
                  </div>
                </div>
              </section>
            </>
          ) : (
            <div className="empty-state">请选择一个题目</div>
          )}
        </aside>
      </section>
    </main>
  );
}

function TargetLink({ label, href }: { label: string; href?: string | null }) {
  if (!href) {
    return (
      <div>
        <span>{label}</span>
        <strong>获取容器后显示</strong>
      </div>
    );
  }
  return (
    <div>
      <span>{label}</span>
      <Link className="evidence-link" href={href} target={href.startsWith("http") ? "_blank" : undefined}>
        <ExternalLink size={15} /> 打开
      </Link>
    </div>
  );
}

function formatDate(value: string): string {
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
  return "不可用";
}

function readError(err: unknown): string {
  return err instanceof Error ? err.message : "UNKNOWN_ERROR";
}
