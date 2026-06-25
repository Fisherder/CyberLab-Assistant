"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { BookOpenCheck, ClipboardCheck, LogOut, UserRound } from "lucide-react";
import { clearAuthToken } from "../lib/api";

type TeacherWorkspaceShellProps = {
  active: "bank" | "grading" | "profile";
  children: ReactNode;
};

export function TeacherWorkspaceShell({ active, children }: TeacherWorkspaceShellProps) {
  function logout() {
    clearAuthToken();
    window.location.href = "/login";
  }

  return (
    <div className="teacher-app-shell">
      <aside className="teacher-sidebar">
        <div className="brand">
          <strong>CLA 教师端</strong>
          <span>课程实践管理</span>
        </div>
        <nav className="teacher-nav" aria-label="教师端导航">
          <Link className={active === "bank" ? "active" : ""} href="/teacher/challenge-bank">
            <BookOpenCheck size={17} /> 题库
          </Link>
          <Link className={active === "grading" ? "active" : ""} href="/teacher/grading">
            <ClipboardCheck size={17} /> 评分系统
          </Link>
          <Link className={active === "profile" ? "active" : ""} href="/teacher/profile">
            <UserRound size={17} /> 个人页面
          </Link>
        </nav>
        <button className="teacher-logout" type="button" onClick={logout}>
          <LogOut size={16} /> 退出登录
        </button>
      </aside>
      {children}
    </div>
  );
}
