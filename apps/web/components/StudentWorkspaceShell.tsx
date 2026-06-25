"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { BookOpenCheck, LogOut, TerminalSquare, UserRound } from "lucide-react";
import { clearAuthToken } from "../lib/api";

type StudentWorkspaceShellProps = {
  active: "bank" | "terminal" | "profile";
  children: ReactNode;
};

export function StudentWorkspaceShell({ active, children }: StudentWorkspaceShellProps) {
  function logout() {
    clearAuthToken();
    window.location.href = "/login";
  }

  return (
    <div className="teacher-app-shell student-app-shell">
      <aside className="teacher-sidebar student-sidebar">
        <div className="brand">
          <strong>CLA 学生端</strong>
          <span>课程实践工作台</span>
        </div>
        <nav className="teacher-nav student-nav" aria-label="学生端导航">
          <Link className={active === "bank" ? "active" : ""} href="/student/challenge-bank">
            <BookOpenCheck size={17} /> 题库
          </Link>
          <Link className={active === "terminal" ? "active" : ""} href="/student/terminal">
            <TerminalSquare size={17} /> 终端界面
          </Link>
          <Link className={active === "profile" ? "active" : ""} href="/student/profile">
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
