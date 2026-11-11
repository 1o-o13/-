"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Logo } from "@/lib/brand";

type Posting = { id: number; title: string };
const ROLE: Record<string, string> = { super_admin: "최고관리자", sys_admin: "시스템 관리자", recruiter: "채용 담당", dept_member: "부서원" };

// 채용 관리 화면 공통: 왼쪽 메뉴 (로그인·가입 신청 화면 제외)
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [postings, setPostings] = useState<Posting[]>([]);
  const [role, setRole] = useState("");
  const isLogin = path === "/admin/login" || path === "/admin/signup"; // 로그인 전 화면

  useEffect(() => {
    if (isLogin) return;
    api<Posting[]>("/admin/postings").then(setPostings, () => router.push("/admin/login"));
    api<{ role: string }>("/auth/me?as=admin").then((m) => setRole(m.role), () => {});
  }, [isLogin, router]);

  if (isLogin)
    return (
      <>
        <header className="border-b border-slate-200 bg-white"><div className="mx-auto max-w-6xl px-6 py-3"><Logo sub="채용 관리" /></div></header>
        <main className="px-6 py-16">{children}</main>
      </>
    );

  const pid = postings[0]?.id;
  const menu: [string, string | undefined][] = [
    ["채용 공고", "/admin/postings"],
    ["지원자 현황", "/admin/applicants"],
    ["1차 서류 결정", "/admin/documents"],
    ["AI 면접 설정", pid ? `/admin/postings/${pid}/interview-setting` : undefined],
    ["AI 면접 결과", "/admin/interviews"],
    ["최종 합격 결정", "/admin/final"],
    ...(role === "super_admin" ? ([["관리자 승인", "/admin/users"]] as [string, string][]) : []),
  ];

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 bg-brand-900 text-brand-100 print:hidden">
        <div className="px-5 py-4">
          <p className="text-lg font-bold text-white">새벽소프트</p>
          <p className="text-xs">채용 관리</p>
        </div>
        <nav className="flex flex-col gap-0.5 px-2 text-sm">
          {menu.map(([label, href]) =>
            href ? (
              <Link key={label} href={href} className={`rounded-lg px-3 py-2.5 transition-colors hover:bg-white/10 ${path === href || (path.startsWith(href + "/") && !path.endsWith("/interview-setting")) || (href.endsWith("/interview-setting") && path.endsWith("/interview-setting")) ? "bg-white/15 font-semibold text-white" : ""}`}>
                {label}
              </Link>
            ) : (
              <span key={label} className="px-3 py-2.5 text-brand-100/50">{label}</span>
            ),
          )}
        </nav>
      </aside>
      <div className="flex-1">
        <header className="flex items-center justify-end gap-3 border-b border-slate-200 bg-white px-6 py-3 text-sm print:hidden">
          {role && <span className="badge">{ROLE[role] ?? role}</span>}
          <button
            className="text-slate-500 hover:text-slate-800"
            onClick={async () => {
              await api("/auth/logout?as=admin", { method: "POST" });
              router.push("/admin/login");
            }}
          >
            로그아웃
          </button>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  );
}
