import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CLA Workbench",
  description: "CLA 终端实践工作台",
  other: {
    "darkreader-lock": "true"
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
