"use client";

import { TeacherWorkspaceShell } from "./TeacherWorkspaceShell";

export function TeacherPlaceholderPage({
  active,
  title,
  description
}: {
  active: "grading" | "profile";
  title: string;
  description: string;
}) {
  return (
    <TeacherWorkspaceShell active={active}>
      <main className="teacher-main">
        <header className="teacher-page-header">
          <div>
            <h1>{title}</h1>
            <span>{description}</span>
          </div>
        </header>
        <section className="empty-state">该页面入口已保留，后续会接入完整功能。</section>
      </main>
    </TeacherWorkspaceShell>
  );
}
