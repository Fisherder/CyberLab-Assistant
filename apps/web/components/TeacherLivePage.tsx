"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Gauge,
  RefreshCw,
  ShieldAlert,
  Users
} from "lucide-react";
import { fetchAssignmentLive, type AssignmentLiveResponse } from "../lib/api";

type TeacherLivePageProps = {
  assignmentId: string;
};

export function TeacherLivePage({ assignmentId }: TeacherLivePageProps) {
  const [live, setLive] = useState<AssignmentLiveResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void loadLive();
  }, [assignmentId]);

  const sortedSessions = useMemo(() => {
    return [...(live?.sessions ?? [])].sort((left, right) => {
      const leftAlert = left.alerts.resource + left.alerts.security;
      const rightAlert = right.alerts.resource + right.alerts.security;
      const leftScore = left.latestAssessment?.score ?? 0;
      const rightScore = right.latestAssessment?.score ?? 0;
      return rightAlert - leftAlert || rightScore - leftScore || left.studentDisplayName.localeCompare(right.studentDisplayName);
    });
  }, [live]);

  async function loadLive() {
    setError("");
    setLoading(true);
    try {
      setLive(await fetchAssignmentLive(assignmentId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="teacher-live-shell">
      <header className="teacher-live-header">
        <div>
          <Link className="backlink" href="/">
            <ArrowLeft size={16} /> Workbench
          </Link>
          <h1>{live?.title ?? "Assignment Live"}</h1>
          <span>{live ? `更新 ${formatDate(live.generatedAt)}` : assignmentId}</span>
        </div>
        <button className="iconbutton" type="button" onClick={loadLive} disabled={loading}>
          <RefreshCw size={16} /> 刷新
        </button>
      </header>

      <section className="monitor-grid" aria-label="live summary">
        <MonitorStat icon={<Users size={18} />} label="Attempts" value={live?.summary.totalAttempts ?? 0} />
        <MonitorStat icon={<Activity size={18} />} label="Ready" value={live?.summary.readySessions ?? 0} />
        <MonitorStat icon={<Gauge size={18} />} label="Stuck" value={live?.summary.stuckSuspected ?? 0} />
        <MonitorStat icon={<AlertTriangle size={18} />} label="Resource" value={live?.summary.resourceAlerts ?? 0} />
        <MonitorStat icon={<ShieldAlert size={18} />} label="Security" value={live?.summary.securityAlerts ?? 0} />
      </section>

      {error ? <div className="error">{error}</div> : null}
      {loading ? <div className="empty-state">加载中</div> : null}
      {!loading && sortedSessions.length === 0 ? <div className="empty-state">暂无活动会话</div> : null}

      {sortedSessions.length > 0 ? (
        <section className="session-table" aria-label="live sessions">
          <div className="session-table-head">
            <span>学生</span>
            <span>会话</span>
            <span>辅助</span>
            <span>告警</span>
            <span>最近事件</span>
          </div>
          {sortedSessions.map((session) => (
            <article className="session-row" key={session.attemptId}>
              <div>
                <strong>{session.studentDisplayName}</strong>
                <code>{session.attemptId}</code>
              </div>
              <div>
                <span className={`pill ${session.sessionStatus === "READY" ? "good" : "warn"}`}>
                  {session.sessionStatus ?? "NO_SESSION"}
                </span>
                <span>epoch {session.sessionEpoch ?? "-"}</span>
              </div>
              <div>
                <span
                  className={`pill ${
                    session.latestAssessment?.state === "CONFIRMED" ? "warn" : "good"
                  }`}
                >
                  {session.latestAssessment
                    ? `${session.latestAssessment.state} · ${Math.round(session.latestAssessment.score * 100)}%`
                    : "未评估"}
                </span>
                <span>
                  {session.latestHint
                    ? `${session.latestHint.level} · ${session.latestHint.status}`
                    : "无提示"}
                </span>
              </div>
              <div className="alert-pair">
                <span>资源 {session.alerts.resource}</span>
                <span>安全 {session.alerts.security}</span>
              </div>
              <div>
                <span>{session.latestEventAt ? formatDate(session.latestEventAt) : "--"}</span>
              </div>
            </article>
          ))}
        </section>
      ) : null}
    </main>
  );
}

function MonitorStat({
  icon,
  label,
  value
}: {
  icon: ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="monitor-stat">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}
