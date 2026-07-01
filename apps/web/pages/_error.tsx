import type { NextPageContext } from "next";
import type { CSSProperties } from "react";

type ErrorPageProps = {
  statusCode?: number;
};

export default function ErrorPage({ statusCode }: ErrorPageProps) {
  return (
    <main style={shellStyle}>
      <section style={panelStyle}>
        <h1>页面异常</h1>
        <p>
          {statusCode ? `请求返回 ${statusCode}。` : "页面运行时出现异常。"}
          请重试，或从题库重新进入。
        </p>
        <div style={actionsStyle}>
          <a style={linkStyle} href="/student/challenge-bank">学生题库</a>
          <a style={linkStyle} href="/teacher/challenge-bank">教师题库</a>
        </div>
      </section>
    </main>
  );
}

ErrorPage.getInitialProps = ({ res, err }: NextPageContext): ErrorPageProps => {
  const statusCode = res?.statusCode ?? err?.statusCode ?? 404;
  return { statusCode };
};

const shellStyle: CSSProperties = {
  alignItems: "center",
  background: "#f5f7fb",
  display: "flex",
  minHeight: "100vh",
  padding: 24
};

const panelStyle: CSSProperties = {
  background: "#fff",
  border: "1px solid #dbe3ee",
  borderRadius: 8,
  boxShadow: "0 18px 50px rgba(15, 23, 42, 0.08)",
  color: "#182235",
  display: "grid",
  gap: 14,
  margin: "0 auto",
  maxWidth: 560,
  padding: 28,
  width: "100%"
};

const actionsStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10
};

const linkStyle: CSSProperties = {
  alignItems: "center",
  background: "#fff",
  border: "1px solid #dbe3ee",
  borderRadius: 8,
  color: "#182235",
  display: "inline-flex",
  fontWeight: 700,
  minHeight: 40,
  padding: "8px 12px",
  textDecoration: "none"
};
