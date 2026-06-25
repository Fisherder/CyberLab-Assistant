"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  FileSearch,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  XCircle
} from "lucide-react";
import {
  approveChallengeVersion,
  fetchChallengeValidation,
  hasAuthToken,
  type ChallengeValidationResponse
} from "../lib/api";

type ChallengeValidationPageProps = {
  versionId: string;
};

export function ChallengeValidationPage({ versionId }: ChallengeValidationPageProps) {
  const [report, setReport] = useState<ChallengeValidationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");

  useEffect(() => {
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
      return;
    }
    void loadReport();
  }, [versionId]);

  const groupedChecks = useMemo(() => {
    return (report?.checks ?? []).reduce<Record<string, ChallengeValidationResponse["checks"]>>(
      (groups, check) => {
        groups[check.category] = groups[check.category] ?? [];
        groups[check.category].push(check);
        return groups;
      },
      {}
    );
  }, [report]);

  const canApprove =
    report !== null && report.overallStatus !== "BLOCK" && report.summary.blocked === 0;

  async function loadReport() {
    setError("");
    setLoading(true);
    try {
      setReport(await fetchChallengeValidation(versionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading(false);
    }
  }

  async function approveVersion() {
    if (!report || !canApprove) return;
    setError("");
    setActionMessage("");
    setApproving(true);
    try {
      const approval = await approveChallengeVersion(versionId);
      setActionMessage(approval.alreadyPublished ? "版本已发布" : "审批已发布");
      await loadReport();
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setApproving(false);
    }
  }

  return (
    <main className="validation-shell">
      <header className="validation-header">
        <div>
          <Link className="backlink" href="/">
            <ArrowLeft size={16} /> Workbench
          </Link>
          <h1>验证报告</h1>
          <span>{report ? `${report.challengeVersionId} · ${report.semver}` : versionId}</span>
        </div>
        <div className="validation-actions">
          <button
            className="iconbutton primary"
            type="button"
            onClick={approveVersion}
            disabled={!report || !canApprove || approving || report.versionStatus === "PUBLISHED"}
          >
            <ShieldCheck size={16} />
            {report?.versionStatus === "PUBLISHED" ? "已发布" : approving ? "发布中" : "审批发布"}
          </button>
          <button className="iconbutton" type="button" onClick={loadReport} disabled={loading}>
            <RefreshCw size={16} /> 刷新
          </button>
        </div>
      </header>

      {error ? <div className="error">{error}</div> : null}
      {actionMessage ? <div className="status-note">{actionMessage}</div> : null}
      {loading ? <div className="empty-state">加载中</div> : null}

      {report ? (
        <>
          <section className="validation-summary">
            <ValidationMetric
              icon={<ShieldCheck size={18} />}
              label="Overall"
              value={report.overallStatus}
              tone={report.overallStatus}
            />
            <ValidationMetric icon={<CheckCircle2 size={18} />} label="Pass" value={report.summary.passed} />
            <ValidationMetric icon={<TriangleAlert size={18} />} label="Warn" value={report.summary.warnings} />
            <ValidationMetric icon={<XCircle size={18} />} label="Block" value={report.summary.blocked} />
          </section>

          <section className="validation-meta">
            <div>
              <span>Artifact</span>
              <strong>{report.artifactDigest}</strong>
            </div>
            <div>
              <span>Workflow</span>
              <strong>{report.workflowId}</strong>
            </div>
            <div>
              <span>Started</span>
              <strong>{formatDate(report.startedAt)}</strong>
            </div>
            <div>
              <span>Ended</span>
              <strong>{report.endedAt ? formatDate(report.endedAt) : "--"}</strong>
            </div>
          </section>

          <section className="validation-groups">
            {Object.entries(groupedChecks).map(([category, checks]) => (
              <div className="validation-group" key={category}>
                <div className="validation-group-title">
                  <FileSearch size={17} />
                  <h2>{category}</h2>
                </div>
                <div className="validation-checks">
                  {checks.map((check) => (
                    <article className="validation-check" key={check.id}>
                      <span className={`pill ${check.status === "PASS" ? "good" : "warn"}`}>
                        {check.status}
                      </span>
                      <div>
                        <strong>{check.title}</strong>
                        <code>{check.id}</code>
                        <div className="evidence-refs">
                          {check.evidenceRefs.map((ref) => (
                            <code key={ref}>{ref}</code>
                          ))}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            ))}
          </section>

          <section className="validation-policy">
            <span>Forbidden disclosure classes checked</span>
            <div className="evidence-refs">
              {report.forbiddenDisclosuresChecked.map((item) => (
                <code key={item}>{item}</code>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}

function ValidationMetric({
  icon,
  label,
  value,
  tone
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
  tone?: string;
}) {
  return (
    <div className={`validation-metric ${tone === "BLOCK" ? "blocked" : tone === "WARN" ? "warn" : ""}`}>
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
