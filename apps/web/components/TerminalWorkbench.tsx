"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Ban,
  BookOpenCheck,
  Cable,
  ClipboardCheck,
  FileText,
  Lightbulb,
  LogOut,
  Play,
  RefreshCcw,
  Send,
  ShieldCheck,
  ThumbsUp
} from "lucide-react";
import {
  createAttempt,
  clearAuthToken,
  ensureSession,
  fetchGrade,
  fetchMe,
  fetchTutorState,
  hasAuthToken,
  requestHint,
  resetSession,
  sendHintFeedback,
  submitAnswer,
  setDevToken,
  terminalTicket,
  type GradeResponse,
  type TutorStateResponse
} from "../lib/api";

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
  const lastServerSequenceRef = useRef<number | null>(null);
  const [attemptId, setAttemptId] = useState<string>("");
  const [session, setSession] = useState<string>("");
  const [state, setState] = useState<ConnectionState>("idle");
  const [answer, setAnswer] = useState("");
  const [grade, setGrade] = useState<GradeResponse | null>(null);
  const [tutor, setTutor] = useState<TutorStateResponse | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const devToken = params.get("claDevToken");
    if (devToken) {
      setDevToken(devToken);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    const query = new URLSearchParams(window.location.search);
    const queryAttemptId = query.get("attemptId");
    if (queryAttemptId) {
      setAttemptId(queryAttemptId);
    }
    if (!hasAuthToken()) {
      window.location.replace(
        `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
      );
      return;
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
    return () => wsRef.current?.close();
  }, []);

  function logout() {
    clearAuthToken();
    window.location.href = "/login";
  }

  async function start() {
    setError("");
    setState("provisioning");
    try {
      const isReconnect = Boolean(attemptId);
      if (!isReconnect) lastServerSequenceRef.current = null;
      const attempt = isReconnect ? { attemptId } : await createAttempt();
      setAttemptId(attempt.attemptId);
      const lab = await ensureSession(attempt.attemptId);
      setSession(`${lab.sessionId} / epoch ${lab.sessionEpoch}`);
      setTutor(await fetchTutorState(attempt.attemptId));
      const ticket = await terminalTicket(attempt.attemptId);
      await connect(ticket.websocketUrl, ticket.ticket);
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    }
  }

  async function resetLab() {
    if (!attemptId) return;
    setError("");
    setState("provisioning");
    try {
      lastServerSequenceRef.current = null;
      const lab = await resetSession(attemptId);
      setSession(`${lab.sessionId} / epoch ${lab.sessionEpoch}`);
      setTutor(await fetchTutorState(attemptId));
      const ticket = await terminalTicket(attemptId);
      await connect(ticket.websocketUrl, ticket.ticket);
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    }
  }

  async function connect(url: string, ticket: string) {
    const { Terminal } = await import("@xterm/xterm");
    const { FitAddon } = await import("@xterm/addon-fit");
    const target = terminalRef.current;
    if (!target) return;
    wsRef.current?.close();
    target.innerHTML = "";
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
    const sendResize = () => {
      if (ws.readyState !== WebSocket.OPEN) return;
      fit.fit();
      sendJsonFrame(ws, CLIENT_RESIZE, { cols: term.cols, rows: term.rows });
    };
    const onResize = () => {
      window.clearTimeout(resizeId);
      resizeId = window.setTimeout(sendResize, 150);
    };
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
      if (heartbeatId !== undefined) window.clearInterval(heartbeatId);
      window.clearTimeout(resizeId);
      window.removeEventListener("resize", onResize);
      term.dispose();
      setState("closed");
    };
    ws.onerror = () => {
      if (heartbeatId !== undefined) window.clearInterval(heartbeatId);
      window.clearTimeout(resizeId);
      window.removeEventListener("resize", onResize);
      setState("error");
    };
    term.onData((data) => {
      const payload = new TextEncoder().encode(data);
      const frame = new Uint8Array(payload.length + 1);
      frame[0] = CLIENT_STDIN;
      frame.set(payload, 1);
      ws.send(frame);
    });
    wsRef.current = ws;
  }

  async function submit() {
    if (!attemptId) return;
    setError("");
    try {
      await submitAnswer(attemptId, answer);
      setGrade(await fetchGrade(attemptId));
      setTutor(await fetchTutorState(attemptId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    }
  }

  async function askHint(level: "L1" | "L2" | "L3") {
    if (!attemptId) return;
    setError("");
    try {
      await requestHint(attemptId, level);
      setTutor(await fetchTutorState(attemptId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    }
  }

  async function giveHintFeedback(feedback: "ACCEPTED" | "LATER" | "MISJUDGED" | "AUTO_DISABLED") {
    if (!tutor?.latestHint) return;
    setError("");
    try {
      await sendHintFeedback(tutor.latestHint.hintId, feedback);
      setTutor(await fetchTutorState(tutor.attemptId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "UNKNOWN_ERROR");
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>CLA</strong>
          <span>WEBSEC-101 · web-sqli-auth</span>
        </div>
        <div className="nav">
          <button className="active" type="button">
            <Cable size={16} /> Terminal
          </button>
          <button type="button">
            <ClipboardCheck size={16} /> Evidence
          </button>
          <button type="button">
            <ShieldCheck size={16} /> Appeal
          </button>
          <Link className="navlink" href="/student/challenge-bank">
            <BookOpenCheck size={16} /> 题库
          </Link>
        </div>
        <div className="sidebar-actions">
          <button type="button" onClick={logout}>
            <LogOut size={16} /> 退出登录
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topline">
          <div>
            <div className="label">当前 Attempt</div>
            <strong>{attemptId || "未创建"}</strong>
          </div>
          <div className="statusline">
            <span className={`pill ${state === "connected" ? "good" : "warn"}`}>{state}</span>
            <span className="pill">{session || "no session"}</span>
          </div>
        </header>
        <section className="terminalwrap">
          <div className="terminal" ref={terminalRef} />
        </section>
        <footer className="actions">
          <button className="toolbutton primary" type="button" onClick={start}>
            <Play size={16} /> {attemptId ? "连接终端" : "启动"}
          </button>
          <button className="toolbutton" type="button" onClick={start}>
            <RefreshCcw size={16} /> 重连
          </button>
          <button className="toolbutton" type="button" onClick={resetLab} disabled={!attemptId}>
            <RefreshCcw size={16} /> 重置
          </button>
        </footer>
      </main>
      <aside className="assist">
        <div className="stack">
          <section className="panel">
            <h3>辅助</h3>
            <div className="tutor-state">
              <span className={`pill ${tutor?.assessment.state === "CONFIRMED" ? "warn" : "good"}`}>
                {tutor ? `${tutor.assessment.state} · ${Math.round(tutor.assessment.score * 100)}%` : "未评估"}
              </span>
              <span className="meta">
                {tutor?.autoHintsEnabled === false ? "自动提示已关闭" : "自动提示开启"}
              </span>
            </div>
            <div className="hint-buttons">
              <button className="toolbutton" type="button" onClick={() => askHint("L1")} disabled={!attemptId}>
                <Lightbulb size={16} /> L1
              </button>
              <button className="toolbutton" type="button" onClick={() => askHint("L2")} disabled={!attemptId}>
                <Lightbulb size={16} /> L2
              </button>
              <button className="toolbutton" type="button" onClick={() => askHint("L3")} disabled={!attemptId}>
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
            <textarea className="answer" value={answer} onChange={(event) => setAnswer(event.target.value)} />
            <button className="toolbutton primary" type="button" onClick={submit}>
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
                    <strong>{grade.totalScore}</strong>
                  </div>
                  {grade.criteria.map((criterion) => (
                    <div key={criterion.criterionId}>
                      <span>{criterion.criterionId}</span>
                      <strong>
                        {criterion.score}/{criterion.maxScore}
                      </strong>
                    </div>
                  ))}
                  <Link className="evidence-link" href={`/student/grades/${attemptId}`}>
                    <FileText size={16} /> 完整证据页
                  </Link>
                </>
              ) : (
                <span className="meta">no grade</span>
              )}
            </div>
          </section>
          {error ? <div className="error">{error}</div> : null}
        </div>
      </aside>
    </div>
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
