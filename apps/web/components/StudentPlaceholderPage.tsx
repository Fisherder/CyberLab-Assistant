"use client";

import { StudentWorkspaceShell } from "./StudentWorkspaceShell";

export function StudentPlaceholderPage({
  active,
  title,
  description
}: {
  active: "profile";
  title: string;
  description: string;
}) {
  return (
    <StudentWorkspaceShell active={active}>
      <main className="teacher-main student-placeholder-main">
        <header className="teacher-page-header">
          <div>
            <h1>{title}</h1>
            <span>{description}</span>
          </div>
        </header>
        <section className="empty-state">该页面入口已保留，后续会接入完整功能。</section>
      </main>
    </StudentWorkspaceShell>
  );
}
