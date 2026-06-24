import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CLA Workbench",
  description: "CLA terminal practice workbench"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

