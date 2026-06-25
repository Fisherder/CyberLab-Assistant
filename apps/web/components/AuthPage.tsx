"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpenCheck, GraduationCap, KeyRound, LogIn, UserPlus } from "lucide-react";
import {
  hasAuthToken,
  loginLocalAccount,
  registerLocalAccount,
  setAuthToken,
  type AuthTokenResponse
} from "../lib/api";

type Mode = "login" | "register";
type AccountRole = "STUDENT" | "TEACHER";

export function AuthPage() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AccountRole>("STUDENT");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const nextUrl = useMemo(() => {
    if (typeof window === "undefined") return "/";
    const params = new URLSearchParams(window.location.search);
    return safeNext(params.get("next"));
  }, []);

  useEffect(() => {
    if (hasAuthToken()) {
      window.location.replace(nextUrl);
    }
  }, [nextUrl]);

  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      const result =
        mode === "login"
          ? await loginLocalAccount(email.trim(), password)
          : await registerLocalAccount(email.trim(), password, displayName.trim(), role);
      setAuthToken(result.accessToken);
      window.location.href = destinationFor(result, nextUrl);
    } catch (err) {
      setError(readableAuthError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    email.trim().length >= 3 &&
    password.length >= (mode === "login" ? 1 : 8) &&
    (mode === "login" || displayName.trim().length > 0);

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-label="CLA 账号登录">
        <div className="auth-brand">
          <div className="auth-logo">C</div>
          <div>
            <strong>CyberLab Assistant</strong>
            <span>课程实践入口</span>
          </div>
        </div>

        <div className="auth-switch" role="tablist" aria-label="账号操作">
          <button
            className={mode === "login" ? "active" : ""}
            type="button"
            onClick={() => setMode("login")}
          >
            <LogIn size={16} /> 登录
          </button>
          <button
            className={mode === "register" ? "active" : ""}
            type="button"
            onClick={() => setMode("register")}
          >
            <UserPlus size={16} /> 注册
          </button>
        </div>

        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmit && !submitting) void submit();
          }}
        >
          <label>
            邮箱
            <input
              autoComplete="email"
              name="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@example.edu"
            />
          </label>

          {mode === "register" ? (
            <label>
              姓名
              <input
                autoComplete="name"
                name="name"
                type="text"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="课堂中显示的姓名"
              />
            </label>
          ) : null}

          <label>
            密码
            <input
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === "login" ? "输入密码" : "至少 8 位"}
            />
          </label>

          {mode === "register" ? (
            <fieldset className="role-select">
              <legend>账号类型</legend>
              <button
                className={role === "STUDENT" ? "selected" : ""}
                type="button"
                onClick={() => setRole("STUDENT")}
              >
                <BookOpenCheck size={17} />
                <span>学生</span>
              </button>
              <button
                className={role === "TEACHER" ? "selected" : ""}
                type="button"
                onClick={() => setRole("TEACHER")}
              >
                <GraduationCap size={17} />
                <span>教师</span>
              </button>
            </fieldset>
          ) : null}

          <button className="auth-submit" type="submit" disabled={!canSubmit || submitting}>
            <KeyRound size={16} />
            {submitting ? "处理中" : mode === "login" ? "登录" : "创建账号并进入"}
          </button>
        </form>

        {error ? <div className="auth-error">{error}</div> : null}
      </section>
    </main>
  );
}

function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}

function destinationFor(result: AuthTokenResponse, nextUrl: string): string {
  if (nextUrl !== "/") return nextUrl;
  if (result.user.roles.includes("teacher") && !result.user.roles.includes("student")) {
    return "/teacher/challenges/cv_web_sqli_auth_1_3_0/validation";
  }
  return "/";
}

function readableAuthError(err: unknown): string {
  const code = err instanceof Error ? err.message : "UNKNOWN_ERROR";
  if (code === "INVALID_CREDENTIALS") return "邮箱或密码不正确。";
  if (code === "ACCOUNT_ALREADY_EXISTS") return "这个邮箱已经注册，请直接登录。";
  if (code === "INVALID_EMAIL") return "请输入有效邮箱。";
  if (code === "LOCAL_AUTH_DISABLED") return "当前系统没有开启本地账号登录。";
  return code;
}
