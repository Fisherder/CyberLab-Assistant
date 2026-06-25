"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, FileCheck2, RefreshCw, Scale, Send, ShieldCheck } from "lucide-react";
import {
  createAppeal,
  fetchGrade,
  hasAuthToken,
  type AppealResponse,
  type GradeResponse
} from "../lib/api";
import { StudentWorkspaceShell } from "./StudentWorkspaceShell";

type GradeEvidencePageProps = {
  attemptId: string;
};

export function GradeEvidencePage({ attemptId }: GradeEvidencePageProps) {
  const [grade, setGrade] = useState<GradeResponse | null>(null);
  const [selectedCriterionId, setSelectedCriterionId] = useState("");
  const [reason, setReason] = useState("");
  const [appeal, setAppeal] = useState<AppealResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
      return;
    }
    void loadGrade();
  }, [attemptId]);

  useEffect(() => {
    if (grade && !selectedCriterionId) {
      setSelectedCriterionId(grade.criteria[0]?.criterionId ?? "");
    }
  }, [grade, selectedCriterionId]);

  const selectedCriterion = useMemo(
    () => grade?.criteria.find((criterion) => criterion.criterionId === selectedCriterionId),
    [grade, selectedCriterionId]
  );

  async function loadGrade() {
    setError("");
    setLoading(true);
    try {
      const nextGrade = await fetchGrade(attemptId);
      setGrade(nextGrade);
      setSelectedCriterionId(nextGrade.criteria[0]?.criterionId ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading(false);
    }
  }

  async function submitAppeal() {
    if (!grade || !selectedCriterionId || reason.trim().length < 3) return;
    setSubmitting(true);
    setError("");
    try {
      setAppeal(await createAppeal(grade.gradeRevisionId, selectedCriterionId, reason.trim()));
      setReason("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <StudentWorkspaceShell active="terminal">
      <main className="grade-shell">
      <section className="grade-summary">
        <div className="grade-topbar">
          <Link className="backlink" href={`/student/terminal?attemptId=${attemptId}`}>
            <ArrowLeft size={16} /> 返回终端
          </Link>
          <button className="iconbutton" type="button" onClick={loadGrade} disabled={loading}>
            <RefreshCw size={16} /> 刷新
          </button>
        </div>
        <div className="grade-score">
          <span>总分</span>
          <strong>{grade ? `${grade.totalScore.toFixed(1)} / 100` : loading ? "加载中" : "--"}</strong>
        </div>
        <div className="grade-independence">
          <div>
            <span>独立完成指数</span>
            <strong>{grade ? formatPercent(grade.independenceIndex) : loading ? "加载中" : "--"}</strong>
          </div>
          <p>提示使用只影响该指数，不改变总分。</p>
        </div>
        <div className="grade-facts">
          <div>
            <span>Attempt</span>
            <strong>{attemptId}</strong>
          </div>
          <div>
            <span>Revision</span>
            <strong>{grade ? `${grade.revisionNo} · ${grade.status}` : "--"}</strong>
          </div>
          <div>
            <span>Rubric</span>
            <strong>{grade?.rubricVersion ?? "--"}</strong>
          </div>
          <div>
            <span>Grader</span>
            <strong>{grade?.graderVersion ?? "--"}</strong>
          </div>
          <div>
            <span>Published</span>
            <strong>{grade ? formatDate(grade.publishedAt) : "--"}</strong>
          </div>
        </div>
      </section>

      <section className="grade-main">
        <div className="grade-section-title">
          <FileCheck2 size={18} />
          <h1>成绩证据</h1>
        </div>
        {loading ? <div className="empty-state">加载中</div> : null}
        {!loading && !grade ? <div className="empty-state">暂无成绩</div> : null}
        {grade ? (
          <div className="criterion-list">
            {grade.criteria.map((criterion) => (
              <button
                className={`criterion-row ${
                  criterion.criterionId === selectedCriterionId ? "selected" : ""
                }`}
                key={criterion.criterionId}
                type="button"
                onClick={() => setSelectedCriterionId(criterion.criterionId)}
              >
                <span className="criterion-name">{criterion.criterionId}</span>
                <span className="criterion-score">
                  {criterion.score.toFixed(1)} / {criterion.maxScore.toFixed(1)}
                </span>
                <span className="criterion-meta">
                  {criterion.graderType} · {formatPercent(criterion.confidence)}
                </span>
                <span className="criterion-explanation">{criterion.explanation}</span>
                <span className="evidence-refs">
                  {criterion.evidenceRefs.map((ref) => (
                    <code key={ref}>{ref}</code>
                  ))}
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      <aside className="appeal-panel">
        <div className="grade-section-title">
          <Scale size={18} />
          <h2>申诉</h2>
        </div>
        <label className="field-label" htmlFor="criterion">
          标准
        </label>
        <select
          className="select"
          id="criterion"
          value={selectedCriterionId}
          onChange={(event) => setSelectedCriterionId(event.target.value)}
        >
          {grade?.criteria.map((criterion) => (
            <option key={criterion.criterionId} value={criterion.criterionId}>
              {criterion.criterionId}
            </option>
          ))}
        </select>
        {selectedCriterion ? (
          <div className="selected-evidence">
            <ShieldCheck size={16} />
            <span>
              {selectedCriterion.score.toFixed(1)} / {selectedCriterion.maxScore.toFixed(1)} ·{" "}
              {selectedCriterion.graderType}
            </span>
          </div>
        ) : null}
        <label className="field-label" htmlFor="appealReason">
          理由
        </label>
        <textarea
          className="answer appeal-textarea"
          id="appealReason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <button
          className="toolbutton primary"
          type="button"
          disabled={!grade || !selectedCriterionId || reason.trim().length < 3 || submitting}
          onClick={submitAppeal}
        >
          <Send size={16} /> 提交申诉
        </button>
        {appeal ? (
          <div className="success">
            {appeal.status} · {appeal.criterionId} · {appeal.appealId}
          </div>
        ) : null}
        {error ? <div className="error">{error}</div> : null}
      </aside>
      </main>
    </StudentWorkspaceShell>
  );
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}
