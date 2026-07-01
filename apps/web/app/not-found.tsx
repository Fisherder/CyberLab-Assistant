export default function NotFound() {
  return (
    <main className="error-shell">
      <section className="error-panel">
        <h1>页面不存在</h1>
        <p>没有找到这个页面，请从题库或登录页重新进入。</p>
        <div className="error-actions">
          <a href="/student/challenge-bank">学生题库</a>
          <a href="/teacher/challenge-bank">教师题库</a>
        </div>
      </section>
    </main>
  );
}
