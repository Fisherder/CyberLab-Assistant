"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Ban,
  BookOpenCheck,
  FileText,
  Lightbulb,
  Play,
  RefreshCcw,
  RefreshCw,
  Send,
  TerminalSquare,
  ThumbsUp
} from "lucide-react";
import {
  ensureSession,
  fetchGrade,
  fetchMe,
  fetchStudentChallengeBank,
  fetchTutorState,
  hasAuthToken,
  requestHint,
  resetSession,
  sendHintFeedback,
  setDevToken,
  submitAnswer,
  terminalTicket,
  type GradeResponse,
  type StudentChallengeBankItemResponse,
  type TutorStateResponse
} from "../lib/api";
import { StudentWorkspaceShell } from "./StudentWorkspaceShell";

type ConnectionState = "idle" | "provisioning" | "connected" | "closed" | "error";

const CLIENT_STDIN = 0x01;
const CLIENT_RESIZE = 0x02;
const CLIENT_ACK = 0x03;
const CLIENT_HEARTBEAT = 0x04;
const SERVER_STDOUT = 0x11;
const SERVER_STATUS = 0x12;
const SERVER_REPLAY = 0x13;
const SERVER_ERROR = 0x1f;

export function TerminalWorkbench() {
  const terminalRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const cleanupConnectionRef = useRef<(() => void) | null>(null);
  const lastServerSequenceRef = useRef<number | null>(null);
  const selectedAttemptRef = useRef("");
  const contextRequestRef = useRef(0);
  const [items, setItems] = useState<StudentChallengeBankItemResponse[]>([]);
  const [selectedAttemptId, setSelectedAttemptId] = useState("");
  const [session, setSession] = useState("");
  const [state, setState] = useState<ConnectionState>("idle");
  const [answerByAttempt, setAnswerByAttempt] = useState<Record<string, string>>({});
  const [grade, setGrade] = useState<GradeResponse | null>(null);
  const [tutor, setTutor] = useState<TutorStateResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [loadingEnvironments, setLoadingEnvironments] = useState(false);
  const [loadingContext, setLoadingContext] = useState(false);

  const runningItems = useMemo(
    () => items.filter((item) => item.hasEnvironment && item.attemptId),
    [items]
  );
  const selectedItem = useMemo(
    () => runningItems.find((item) => item.attemptId === selectedAttemptId) ?? null,
    [runningItems, selectedAttemptId]
  );
  const answer = selectedAttemptId ? answerByAttempt[selectedAttemptId] ?? "" : "";

  useEffect(() => {
    selectedAttemptRef.current = selectedAttemptId;
  }, [selectedAttemptId]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const devToken = params.get("claDevToken");
    if (devToken) {
      setDevToken(devToken);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
      return undefined;
    }
    void fetchMe()
      .then((me) => {
        if (me.roles.includes("teacher") && !me.roles.includes("student")) {
          window.location.replace("/teacher/challenge-bank");
        }
      })
      .catch(() => {
        window.location.replace(
          `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
        );
      });

    const query = new URLSearchParams(window.location.search);
    void loadRunningItems(query.get("attemptId") ?? "");
    return () => closeTerminalSurface();
  }, []);

  useEffect(() => {
    closeTerminalSurface();
    lastServerSequenceRef.current = null;
    setError("");
    setMessage("");
    if (!selectedAttemptId) {
      setState("idle");
      setSession("");
      setGrade(null);
      setTutor(null);
      setLoadingContext(false);
      replaceAttemptQuery("");
      return;
    }
    setState("idle");
    setSession(formatSession(selectedItem));
    replaceAttemptQuery(selectedAttemptId);
    void loadAttemptContext(selectedAttemptId);
  }, [selectedAttemptId]);

  useEffect(() => {
    if (selectedAttemptId && selectedItem) {
      setSession(formatSession(selectedItem));
    }
  }, [selectedAttemptId, selectedItem?.sessionId, selectedItem?.sessionStatus]);

  async function loadRunningItems(preferredAttemptId = "") {
    setError("");
    setLoadingEnvironments(true);
    try {
      const result = await fetchStudentChallengeBank();
      const nextRunning = result.items.filter((item) => item.hasEnvironment && item.attemptId);
      setItems(result.items);
      setSelectedAttemptId((current) => {
        const preferred = preferredAttemptId || current;
        if (preferred && nextRunning.some((item) => item.attemptId === preferred)) {
          return preferred;
        }
        return nextRunning[0]?.attemptId ?? "";
      });
    } catch (err) {
      setError(readError(err));
    } finally {
      setLoadingEnvironments(false);
    }
  }

  async function loadAttemptContext(nextAttemptId: string) {
    const requestNo = contextRequestRef.current + 1;
    contextRequestRef.current = requestNo;
    setLoadingContext(true);
    setGrade(null);
    setTutor(null);
    const [tutorResult, gradeResult] = await Promise.allSettled([
      fetchTutorState(nextAttemptId),
      fetchGrade(nextAttemptId)
    ]);
    if (contextRequestRef.current !== requestNo || selectedAttemptRef.current !== nextAttemptId) {
      return;
    }
    if (tutorResult.status === "fulfilled") {
      setTutor(tutorResult.value);
    } else {
      setError(readError(tutorResult.reason));
    }
    if (gradeResult.status === "fulfilled") {
      setGrade(gradeResult.value);
    } else if (readError(gradeResult.reason) !== "NOT_FOUND") {
      setError(readError(gradeResult.reason));
    }
    setLoadingContext(false);
  }

  function chooseAttempt(nextAttemptId: string) {
    if (nextAttemptId === selectedAttemptId) return;
    setSelectedAttemptId(nextAttemptId);
  }

  function updateAnswer(value: string) {
    if (!selectedAttemptId) return;
    setAnswerByAttempt((current) => ({ ...current, [selectedAttemptId]: value }));
  }

  async function start() {
    if (!selectedAttemptId) {
      setError("请先在题库获取容器，然后回到终端界面选择题目。");
      return;
    }
    setError("");
    setMessage("");
    setState("provisioning");
    try {
      const currentAttemptId = selectedAttemptId;
      const lab = await ensureSession(currentAttemptId);
      if (selectedAttemptRef.current !== currentAttemptId) return;
      setSession(`${lab.sessionId} / epoch ${lab.sessionEpoch}`);
      const nextTutor = await fetchTutorState(currentAttemptId);
      if (selectedAttemptRef.current !== currentAttemptId) return;
      setTutor(nextTutor);
      const ticket = await terminalTicket(currentAttemptId);
      if (selectedAttemptRef.current !== currentAttemptId) return;
      await connect(ticket.websocketUrl, ticket.ticket);
    } catch (err) {
      setState("error");
      setError(readError(err));
    }
  }

  async function resetLab() {
    if (!selectedAttemptId) return;
    setError("");
    setMessage("");
    setState("provisioning");
    try {
      const currentAttemptId = selectedAttemptId;
      lastServerSequenceRef.current = null;
      const lab = await resetSession(currentAttemptId);
      if (selectedAttemptRef.current !== currentAttemptId) return;
      setSession(`${lab.sessionId} / epoch ${lab.sessionEpoch}`);
      const nextTutor = await fetchTutorState(currentAttemptId);
      if (selectedAttemptRef.current !== currentAttemptId) return;
      setTutor(nextTutor);
      await loadRunningItems(currentAttemptId);
      const ticket = await terminalTicket(currentAttemptId);
      if (selectedAttemptRef.current !== currentAttemptId) return;
      await connect(ticket.websocketUrl, ticket.ticket);
    } catch (err) {
      setState("error");
      setError(readError(err));
    }
  }

  async function connect(url: string, ticket: string) {
    const { Terminal } = await import("@xterm/xterm");
    const { FitAddon } = await import("@xterm/addon-fit");
    const target = terminalRef.current;
    if (!target) return;
    closeTerminalSurface();
    const term = new Terminal({ convertEol: true, cursorBlink: true, fontSize: 13 });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(target);
    fit.fit();
    const wsUrl = resolveBrowserWebSocketUrl(url);
    wsUrl.searchParams.set("ticket", ticket);
    if (lastServerSequenceRef.current !== null) {
      wsUrl.searchParams.set("last_server_sequence", String(lastServerSequenceRef.current));
    }
    const ws = new WebSocket(wsUrl.toString());
    ws.binaryType = "arraybuffer";
    let heartbeatId: number | undefined;
    let resizeId: number | undefined;
    let cleaned = false;
    const sendResize = () => {
      if (ws.readyState !== WebSocket.OPEN) return;
      fit.fit();
      sendJsonFrame(ws, CLIENT_RESIZE, { cols: term.cols, rows: term.rows });
    };
    const onResize = () => {
      window.clearTimeout(resizeId);
      resizeId = window.setTimeout(sendResize, 150);
    };
    const cleanupConnection = () => {
      if (cleaned) return;
      cleaned = true;
      if (heartbeatId !== undefined) window.clearInterval(heartbeatId);
      window.clearTimeout(resizeId);
      window.removeEventListener("resize", onResize);
      term.dispose();
      if (cleanupConnectionRef.current === cleanupConnection) {
        cleanupConnectionRef.current = null;
      }
    };
    cleanupConnectionRef.current = cleanupConnection;
    ws.onopen = () => {
      setState("connected");
      term.focus();
      sendResize();
      heartbeatId = window.setInterval(() => {
        sendJsonFrame(ws, CLIENT_HEARTBEAT, { clientTime: new Date().toISOString() });
      }, 15000);
      window.addEventListener("resize", onResize);
    };
    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        return;
      }
      const bytes = new Uint8Array(event.data);
      if (bytes[0] === SERVER_STDOUT) {
        const sequence = readServerSequence(bytes);
        lastServerSequenceRef.current = sequence;
        term.write(bytes.slice(9));
        sendJsonFrame(ws, CLIENT_ACK, { serverSequence: sequence });
      } else if (bytes[0] === SERVER_STATUS) {
        const status = readJsonFrame(bytes);
        if (status.state === "CONNECTED") setState("connected");
        if (status.state === "DEGRADED") setState("error");
      } else if (bytes[0] === SERVER_REPLAY) {
        const replay = readJsonFrame(bytes);
        if (replay.state === "REPLAY_BEGIN") setState("connected");
      } else if (bytes[0] === SERVER_ERROR) {
        const errorFrame = readJsonFrame(bytes);
        setError(String(errorFrame.code ?? "TERMINAL_ERROR"));
        if (errorFrame.fullRefreshRequired) setState("error");
      }
    };
    ws.onclose = () => {
      cleanupConnection();
      if (wsRef.current === ws) wsRef.current = null;
      setState("closed");
    };
    ws.onerror = () => {
      cleanupConnection();
      if (wsRef.current === ws) wsRef.current = null;
      setState("error");
    };
    term.onData((data) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      const payload = new TextEncoder().encode(data);
      const frame = new Uint8Array(payload.length + 1);
      frame[0] = CLIENT_STDIN;
      frame.set(payload, 1);
      ws.send(frame);
    });
    wsRef.current = ws;
  }

  function closeTerminalSurface() {
    const ws = wsRef.current;
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.close();
      wsRef.current = null;
    }
    cleanupConnectionRef.current?.();
    cleanupConnectionRef.current = null;
    if (terminalRef.current) terminalRef.current.innerHTML = "";
  }

  async function submit() {
    if (!selectedAttemptId || answer.trim().length === 0) return;
    setError("");
    setMessage("");
    try {
      await submitAnswer(selectedAttemptId, answer);
      setGrade(await fetchGrade(selectedAttemptId));
      setTutor(await fetchTutorState(selectedAttemptId));
      await loadRunningItems(selectedAttemptId);
      setMessage("提交完成，成绩已刷新。");
    } catch (err) {
      setError(readError(err));
    }
  }

  async function askHint(level: "L1" | "L2" | "L3") {
    if (!selectedAttemptId) return;
    setError("");
    setMessage("");
    try {
      await requestHint(selectedAttemptId, level);
      setTutor(await fetchTutorState(selectedAttemptId));
    } catch (err) {
      setError(readError(err));
    }
  }

  async function giveHintFeedback(feedback: "ACCEPTED" | "LATER" | "MISJUDGED" | "AUTO_DISABLED") {
    if (!tutor?.latestHint) return;
    setError("");
    setMessage("");
    try {
      await sendHintFeedback(tutor.latestHint.hintId, feedback);
      setTutor(await fetchTutorState(tutor.attemptId));
    } catch (err) {
      setError(readError(err));
    }
  }

  return (
    <StudentWorkspaceShell active="terminal">
      <main className="student-terminal-main">
        <section className="student-terminal-workspace">
          <header className="terminal-topline">
            <div>
              <div className="label">终端连接题目</div>
              <h1>{selectedItem?.title ?? "请选择已开启的题目环境"}</h1>
            </div>
            <div className="terminal-selector">
              <label htmlFor="runningChallenge">题目环境</label>
              <select
                id="runningChallenge"
                className="select"
                value={selectedAttemptId}
                onChange={(event) => chooseAttempt(event.target.value)}
                disabled={loadingEnvironments || runningItems.length === 0}
              >
                {runningItems.length === 0 ? (
                  <option value="">暂无已开启容器</option>
                ) : (
                  runningItems.map((item) => (
                    <option key={item.attemptId ?? item.itemId} value={item.attemptId ?? ""}>
                      {item.title} · {item.sessionStatus ?? "UNKNOWN"}
                    </option>
                  ))
                )}
              </select>
              <button
                className="iconbutton"
                type="button"
                onClick={() => loadRunningItems(selectedAttemptId)}
                disabled={loadingEnvironments}
              >
                <RefreshCw size={16} /> 刷新
              </button>
            </div>
          </header>

          {message ? <div className="status-note">{message}</div> : null}

          <div className="terminal-selected-meta">
            <span className={`pill ${state === "connected" ? "good" : "warn"}`}>{state}</span>
            <span className="pill">{session || "no session"}</span>
            {selectedItem ? (
              <>
                <span className={`pill ${selectedItem.completed ? "good" : "warn"}`}>
                  {selectedItem.completed ? `已完成 · ${formatScore(selectedItem.latestScore)}` : "未完成"}
                </span>
                <span className="pill">Attempt {selectedItem.attemptId}</span>
              </>
            ) : null}
          </div>

          {runningItems.length === 0 ? (
            <div className="empty-state terminal-empty">
              <TerminalSquare size={28} />
              <strong>还没有可连接的题目环境</strong>
              <span>请先到题库打开题目详情，点击“获取容器”。</span>
              <Link className="evidence-link" href="/student/challenge-bank">
                <BookOpenCheck size={16} /> 前往题库
              </Link>
            </div>
          ) : (
            <>
              <section className="terminalwrap">
                <div className="terminal" ref={terminalRef} />
              </section>
              <footer className="actions">
                <button className="toolbutton primary" type="button" onClick={start} disabled={!selectedAttemptId}>
                  <Play size={16} /> 连接终端
                </button>
                <button className="toolbutton" type="button" onClick={start} disabled={!selectedAttemptId}>
                  <RefreshCcw size={16} /> 重连
                </button>
                <button className="toolbutton" type="button" onClick={resetLab} disabled={!selectedAttemptId}>
                  <RefreshCcw size={16} /> 重置
                </button>
              </footer>
            </>
          )}
        </section>

        <aside className="assist student-terminal-assist">
          <div className="stack">
            <section className="panel">
              <h3>辅助</h3>
              <div className="tutor-state">
                <span className={`pill ${tutor?.assessment.state === "CONFIRMED" ? "warn" : "good"}`}>
                  {loadingContext
                    ? "加载中"
                    : tutor
                      ? `${tutor.assessment.state} · ${Math.round(tutor.assessment.score * 100)}%`
                      : "未评估"}
                </span>
                <span className="meta">
                  {tutor?.autoHintsEnabled === false ? "自动提示已关闭" : "自动提示开启"}
                </span>
              </div>
              <div className="hint-buttons">
                <button className="toolbutton" type="button" onClick={() => askHint("L1")} disabled={!selectedAttemptId}>
                  <Lightbulb size={16} /> L1
                </button>
                <button className="toolbutton" type="button" onClick={() => askHint("L2")} disabled={!selectedAttemptId}>
                  <Lightbulb size={16} /> L2
                </button>
                <button className="toolbutton" type="button" onClick={() => askHint("L3")} disabled={!selectedAttemptId}>
                  <Lightbulb size={16} /> L3
                </button>
              </div>
              {tutor?.latestHint ? (
                <div className="hint-card">
                  <div className="hint-card-title">
                    <strong>
                      {tutor.latestHint.level} · {tutor.latestHint.status}
                    </strong>
                    <span>{tutor.latestHint.tutorVersion}</span>
                  </div>
                  <p>{tutor.latestHint.content}</p>
                  <div className="hint-evidence">
                    {tutor.latestHint.evidenceRefs.map((ref) => (
                      <code key={ref}>{ref}</code>
                    ))}
                  </div>
                  <div className="hint-actions">
                    <button type="button" onClick={() => giveHintFeedback("ACCEPTED")}>
                      <ThumbsUp size={14} /> 接受
                    </button>
                    <button type="button" onClick={() => giveHintFeedback("LATER")}>
                      稍后
                    </button>
                    <button type="button" onClick={() => giveHintFeedback("MISJUDGED")}>
                      这不是卡住
                    </button>
                    <button type="button" onClick={() => giveHintFeedback("AUTO_DISABLED")}>
                      <Ban size={14} /> 关闭自动提示
                    </button>
                  </div>
                </div>
              ) : null}
            </section>
            <section className="panel">
              <h2>提交</h2>
              <textarea
                className="answer"
                value={answer}
                onChange={(event) => updateAnswer(event.target.value)}
                disabled={!selectedAttemptId}
              />
              <button
                className="toolbutton primary"
                type="button"
                onClick={submit}
                disabled={!selectedAttemptId || answer.trim().length === 0}
              >
                <Send size={16} /> 提交
              </button>
            </section>
            <section className="panel">
              <h3>成绩证据</h3>
              <div className="evidence">
                {grade ? (
                  <>
                    <div>
                      <span>Total</span>
                      <strong>{grade.totalScore.toFixed(1)}</strong>
                    </div>
                    {grade.criteria.map((criterion) => (
                      <div key={criterion.criterionId}>
                        <span>{criterion.criterionId}</span>
                        <strong>
                          {criterion.score}/{criterion.maxScore}
                        </strong>
                      </div>
                    ))}
                    <Link className="evidence-link" href={`/student/grades/${selectedAttemptId}`}>
                      <FileText size={16} /> 完整证据页
                    </Link>
                  </>
                ) : (
                  <span className="meta">{loadingContext ? "加载中" : "暂无成绩"}</span>
                )}
              </div>
            </section>
            {error ? <div className="error">{error}</div> : null}
          </div>
        </aside>
      </main>
    </StudentWorkspaceShell>
  );
}

function sendJsonFrame(ws: WebSocket, frameType: number, payload: Record<string, unknown>) {
  if (ws.readyState !== WebSocket.OPEN) return;
  const body = new TextEncoder().encode(JSON.stringify(payload));
  const frame = new Uint8Array(body.length + 1);
  frame[0] = frameType;
  frame.set(body, 1);
  ws.send(frame);
}

function resolveBrowserWebSocketUrl(url: string): URL {
  const wsUrl = new URL(url);
  const pageHost = window.location.hostname;
  const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);

  if (localHosts.has(wsUrl.hostname) && pageHost && !localHosts.has(pageHost)) {
    wsUrl.hostname = pageHost;
    wsUrl.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  }

  return wsUrl;
}

function readJsonFrame(bytes: Uint8Array): Record<string, unknown> {
  return JSON.parse(new TextDecoder().decode(bytes.slice(1))) as Record<string, unknown>;
}

function readServerSequence(bytes: Uint8Array): number {
  const view = new DataView(bytes.buffer, bytes.byteOffset + 1, 8);
  return Number(view.getBigUint64(0, false));
}

function formatSession(item: StudentChallengeBankItemResponse | null): string {
  if (!item?.sessionId) return "no session";
  return `${item.sessionId} / ${item.sessionStatus ?? "UNKNOWN"}`;
}

function formatScore(score?: number | null): string {
  return typeof score === "number" ? `${score.toFixed(1)} / 100` : "--";
}

function replaceAttemptQuery(attemptId: string) {
  const suffix = attemptId ? `?attemptId=${encodeURIComponent(attemptId)}` : "";
  window.history.replaceState(null, "", `/student/terminal${suffix}`);
}

function readError(err: unknown): string {
  return err instanceof Error ? err.message : "UNKNOWN_ERROR";
}
