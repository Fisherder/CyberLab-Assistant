"use client";

export default function AppError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="error-shell">
      <section className="error-panel">
        <h1>页面加载失败</h1>
        <p>当前页面遇到异常，请重试；如果仍然失败，请返回题库重新进入。</p>
        <code>{error.digest ?? error.message}</code>
        <div className="error-actions">
          <button type="button" onClick={reset}>
            重试
          </button>
          <a href="/teacher/challenge-bank">返回教师题库</a>
        </div>
      </section>
    </main>
  );
}
