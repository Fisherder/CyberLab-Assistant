"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Database,
  FileSearch,
  RefreshCw,
  Rocket,
  Search,
  ShieldCheck
} from "lucide-react";
import {
  approveChallengeVersion,
  createChallengeDraft,
  fetchChallengeCandidates,
  fetchChallengeRegistry,
  generateChallengeVersion,
  hasAuthToken,
  importLocalChallenges,
  type ChallengeCandidateSearchResponse,
  type ChallengeDraftResponse,
  type ChallengeGeneratedVersionResponse,
  type ChallengeRegistryResponse
} from "../lib/api";

const DEFAULT_COURSE_ID = "course_websec";

export function ChallengeRegistryPage() {
  const [registry, setRegistry] = useState<ChallengeRegistryResponse | null>(null);
  const [query, setQuery] = useState("");
  const [brief, setBrief] = useState(
    "创建一个终端 Web 登录安全实践题，学生使用 curl 验证认证影响，并解释输入信任边界和参数化查询修复思路，预计 75 分钟，禁止访问公网。"
  );
  const [courseId, setCourseId] = useState(DEFAULT_COURSE_ID);
  const [internetDenied, setInternetDenied] = useState(true);
  const [maxDifficulty, setMaxDifficulty] = useState(3);
  const [draft, setDraft] = useState<ChallengeDraftResponse | null>(null);
  const [candidateSearch, setCandidateSearch] = useState<ChallengeCandidateSearchResponse | null>(null);
  const [generated, setGenerated] = useState<ChallengeGeneratedVersionResponse | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
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
    void loadRegistry("");
  }, []);

  const selectedCandidate = useMemo(() => {
    return candidateSearch?.candidates.find((item) => item.candidateId === selectedCandidateId) ?? null;
  }, [candidateSearch, selectedCandidateId]);

  async function loadRegistry(nextQuery = query) {
    setError("");
    setLoading("registry");
    try {
      setRegistry(await fetchChallengeRegistry(nextQuery));
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading("");
    }
  }

  async function importChallenges() {
    setError("");
    setMessage("");
    setLoading("import");
    try {
      const result = await importLocalChallenges();
      setMessage(`导入完成：${result.imported.length} 个版本，跳过 ${result.skipped.length} 个目录`);
      await loadRegistry();
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading("");
    }
  }

  async function createDraft() {
    setError("");
    setMessage("");
    setGenerated(null);
    setLoading("draft");
    try {
      const nextDraft = await createChallengeDraft(courseId, brief, {
        internet: !internetDenied,
        maxDifficulty,
        workspaceType: "TERMINAL"
      });
      setDraft(nextDraft);
      const candidates = await fetchChallengeCandidates(nextDraft.candidatesUrl);
      setCandidateSearch(candidates);
      setSelectedCandidateId(candidates.candidates[0]?.candidateId ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading("");
    }
  }

  async function generateVersion() {
    if (!draft || !selectedCandidateId) return;
    setError("");
    setMessage("");
    setLoading("generate");
    try {
      const result = await generateChallengeVersion(draft.draftId, selectedCandidateId);
      setGenerated(result);
      setMessage(`已生成待审批版本：${result.challengeVersionId}`);
      await loadRegistry();
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading("");
    }
  }

  async function approveGenerated() {
    if (!generated) return;
    setError("");
    setLoading("approve");
    try {
      const approval = await approveChallengeVersion(generated.challengeVersionId);
      setMessage(approval.alreadyPublished ? "版本已发布" : "审批已发布");
      await loadRegistry();
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    } finally {
      setLoading("");
    }
  }

  return (
    <main className="registry-shell">
      <header className="registry-header">
        <div>
          <Link className="backlink" href="/">
            <ArrowLeft size={16} /> Workbench
          </Link>
          <h1>题库 Registry</h1>
          <span>{registry ? `${registry.count} 个版本 · ${registry.retrieval.mode}` : "加载中"}</span>
        </div>
        <div className="registry-actions">
          <button className="iconbutton" type="button" onClick={() => loadRegistry()} disabled={loading !== ""}>
            <RefreshCw size={16} /> 刷新
          </button>
          <button className="iconbutton primary" type="button" onClick={importChallenges} disabled={loading !== ""}>
            <Database size={16} /> 导入本地题目
          </button>
        </div>
      </header>

      {error ? <div className="error">{error}</div> : null}
      {message ? <div className="status-note">{message}</div> : null}

      <section className="registry-toolbar">
        <label>
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void loadRegistry(query);
            }}
            placeholder="搜索题目、目标、知识点"
          />
        </label>
        <button className="iconbutton" type="button" onClick={() => loadRegistry(query)} disabled={loading !== ""}>
          <FileSearch size={16} /> 检索
        </button>
      </section>

      <section className="registry-layout">
        <div className="registry-list">
          {(registry?.versions ?? []).map((version) => (
            <article className="registry-row" key={version.challengeVersionId}>
              <div>
                <strong>{version.title}</strong>
                <span>{version.slug}@{version.semver}</span>
              </div>
              <div className="registry-row-meta">
                <span className={`pill ${version.status === "PUBLISHED" ? "good" : "warn"}`}>
                  {version.status}
                </span>
                <span className={`pill ${version.validationStatus === "PASS" ? "good" : "warn"}`}>
                  {version.validationStatus}
                </span>
                <span>{version.category}</span>
                <span>{version.workspaceType}</span>
                <span>{version.expectedMinutes || "-"} 分钟</span>
              </div>
              <div className="registry-row-actions">
                <Link className="evidence-link" href={`/teacher/challenges/${version.challengeVersionId}/validation`}>
                  <ShieldCheck size={15} /> 验证报告
                </Link>
                <code>{version.artifactDigest}</code>
              </div>
            </article>
          ))}
          {loading === "registry" ? <div className="empty-state">加载中</div> : null}
        </div>

        <aside className="authoring-panel">
          <div className="authoring-section">
            <div className="authoring-title">
              <Bot size={17} />
              <h2>模型辅助出题</h2>
            </div>
            <label className="field-label">课程</label>
            <input value={courseId} onChange={(event) => setCourseId(event.target.value)} />
            <label className="field-label">Brief</label>
            <textarea value={brief} onChange={(event) => setBrief(event.target.value)} />
            <div className="authoring-controls">
              <label>
                <input
                  type="checkbox"
                  checked={internetDenied}
                  onChange={(event) => setInternetDenied(event.target.checked)}
                />
                禁止公网
              </label>
              <label>
                难度上限
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={maxDifficulty}
                  onChange={(event) => setMaxDifficulty(Number(event.target.value))}
                />
              </label>
            </div>
            <button className="iconbutton primary" type="button" onClick={createDraft} disabled={loading !== ""}>
              <FileSearch size={16} /> 解析并检索
            </button>
          </div>

          {draft ? (
            <div className="authoring-section">
              <h3>结构化意图</h3>
              <div className="intent-grid">
                <span>类别</span>
                <strong>{draft.courseIntent.category}</strong>
                <span>目标</span>
                <strong>{draft.courseIntent.target}</strong>
                <span>工作区</span>
                <strong>{draft.courseIntent.workspaceType}</strong>
                <span>置信度</span>
                <strong>{Math.round(draft.courseIntent.confidence * 100)}%</strong>
              </div>
            </div>
          ) : null}

          {candidateSearch ? (
            <div className="authoring-section">
              <h3>候选题目</h3>
              <div className="candidate-list">
                {candidateSearch.candidates.map((candidate) => (
                  <button
                    className={candidate.candidateId === selectedCandidateId ? "candidate-item selected" : "candidate-item"}
                    key={candidate.candidateId}
                    type="button"
                    onClick={() => setSelectedCandidateId(candidate.candidateId)}
                  >
                    <strong>{candidate.title}</strong>
                    <span>{candidate.semver} · 匹配 {Math.round(candidate.score * 100)}%</span>
                  </button>
                ))}
              </div>
              <button
                className="iconbutton primary"
                type="button"
                onClick={generateVersion}
                disabled={!selectedCandidate || loading !== ""}
              >
                <Rocket size={16} /> 生成版本草稿
              </button>
            </div>
          ) : null}

          {generated ? (
            <div className="authoring-section">
              <div className="generated-head">
                <CheckCircle2 size={17} />
                <strong>{generated.challengeVersionId}</strong>
              </div>
              <span className="meta">生成来源：{generated.generatedBy}</span>
              <p>{String(generated.modelDraft.summary ?? "")}</p>
              <div className="registry-row-actions">
                <Link className="evidence-link" href={`/teacher/challenges/${generated.challengeVersionId}/validation`}>
                  <ShieldCheck size={15} /> 验证报告
                </Link>
                <button className="iconbutton primary" type="button" onClick={approveGenerated} disabled={loading !== ""}>
                  <ShieldCheck size={16} /> 审批发布
                </button>
              </div>
            </div>
          ) : null}
        </aside>
      </section>
    </main>
  );
}
