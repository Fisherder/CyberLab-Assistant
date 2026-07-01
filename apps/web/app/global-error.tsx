"use client";

export default function GlobalError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <main className="error-shell">
          <section className="error-panel">
            <h1>系统页面异常</h1>
            <p>页面运行时状态异常，请先重试；如果仍然失败，请回到登录页重新进入。</p>
            <code>{error.digest ?? error.message}</code>
            <div className="error-actions">
              <button type="button" onClick={reset}>
                重试
              </button>
              <a href="/login">返回登录页</a>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
