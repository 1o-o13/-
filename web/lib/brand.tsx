"use client";
// 가상 회사 '새벽소프트' 채용 사이트 공통: 로고·머리글·바닥글
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export const COMPANY = "새벽소프트";

export function Logo({ sub = "채용" }: { sub?: string }) {
  return (
    <Link href="/" className="flex shrink-0 items-center gap-2 whitespace-nowrap">
      <span className="relative h-8 w-8 overflow-hidden rounded-full bg-linear-to-b from-brand-900 to-brand-700 shadow-sm">
        <span className="absolute -bottom-2 left-1/2 h-5 w-5 -translate-x-1/2 rounded-full bg-dawn-400" />
      </span>
      <span className="text-lg font-bold text-brand-900">{COMPANY}</span>
      <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">{sub}</span>
    </Link>
  );
}

type Me = { type: string; exp: number };
type Notice = { id: number; stage: string; published_at: string; posting_id: number; title: string; label: string };
const SEEN = "seen-notices";   // 임시: 읽음 칸이 DB에 없어 이 브라우저에 읽은 알림 번호를 기억

function seen(): number[] {
  try { return JSON.parse(localStorage.getItem(SEEN) ?? "[]"); } catch { return []; }
}

const NAV_BTN = "rounded-full px-3.5 py-1.5 font-medium text-slate-700 transition hover:bg-brand-50 hover:text-brand-700";   // 머리글 오른쪽 버튼 (11/17)

/** 알림 버튼: 발표된 전형 결과 목록. 안 읽은 수를 빨간 숫자로. 누르면 결과 화면으로 */
function Bell({ path }: { path: string }) {
  const router = useRouter();
  const [items, setItems] = useState<Notice[]>([]);
  const [open, setOpen] = useState(false);
  const [read, setRead] = useState<number[]>([]);
  useEffect(() => {
    api<Notice[]>("/me/notifications").then(setItems, () => {});
    setRead(seen());
  }, [path]);
  const unread = items.filter((n) => !read.includes(n.id)).length;
  function go(n: Notice) {
    const next = [...new Set([...seen(), n.id])];
    try { localStorage.setItem(SEEN, JSON.stringify(next)); } catch { /* 저장 못 해도 이동은 한다 */ }
    setRead(next);
    setOpen(false);
    router.push(n.stage === "document" ? `/me/results/${n.posting_id}` : "/me/applications");
  }
  return (
    <span className="relative">
      <button className={`${NAV_BTN} relative`} aria-label={`알림 ${unread}건`} onClick={() => setOpen(!open)}>
        알림
        {unread > 0 && <span className="absolute -right-1.5 -top-1.5 rounded-full bg-dawn-500 px-1.5 text-xs font-semibold text-white shadow-sm" data-testid="bell-count">{unread}</span>}
      </button>
      {open && (
        <span className="absolute right-0 z-10 mt-2 block w-80 whitespace-normal rounded-2xl border border-slate-100 bg-white p-2 shadow-lg">
          {items.length === 0 && <span className="block p-2 text-slate-500">새 알림이 없습니다.</span>}
          {items.map((n) => (
            <button key={n.id} onClick={() => go(n)} className="block w-full rounded p-2 text-left hover:bg-slate-50">
              <span className="flex items-center gap-1.5 font-medium">{!read.includes(n.id) && <span className="h-2 w-2 rounded-full bg-red-600" />}{n.label}</span>
              <span className="block text-xs text-slate-500">{n.title} · {new Date(n.published_at).toLocaleString("ko-KR")}</span>
            </button>
          ))}
        </span>
      )}
    </span>
  );
}

/** 지원자 사이트 머리글. 로그인한 지원자면 남은 로그인 시간(1시간, 쓰는 동안 자동 연장)·연장·내 정보·지원 현황·로그아웃.
 *  면접 화면(app/interview)은 이 머리글을 쓰지 않아 시간 표시·자동 로그아웃이 없다 */
const SITE_MENU = [["회사 소개", "/#about"], ["채용 공고", "/#jobs"], ["복지", "/#perks"], ["채용 절차", "/#process"], ["자주 묻는 질문", "/#faq"]];

export function SiteHeader() {
  const router = useRouter();
  const path = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [menu, setMenu] = useState(false);   // 좁은 화면에서 가운데 메뉴 펼침 (11/17)
  const load = () => api<Me>("/auth/me?as=candidate").then(setMe, () => setMe(null));
  useEffect(() => {
    load();
    setMenu(false);
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps

  // 1초마다 남은 시간. 0이 되면 서버에 한 번 더 물어보고(다른 요청으로 연장됐을 수 있음) 끝났으면 로그인 화면으로
  useEffect(() => {
    if (me?.type !== "candidate") return;
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [me]);
  const left = me ? Math.max(0, Math.floor(me.exp - now)) : 0;
  useEffect(() => {
    if (me?.type !== "candidate" || left > 0) return;
    api<Me>("/auth/me?as=candidate").then(setMe, () => (setMe(null), router.push("/login?expired=1")));
  }, [left, me, router]);

  async function extend() {
    await api("/auth/refresh?as=candidate", { method: "POST" }).then(load, () => router.push("/login?expired=1"));
  }

  async function logout() {
    await api("/auth/logout?as=candidate", { method: "POST" });
    setMe(null);
    router.push("/login");
  }

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-white/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center gap-4 whitespace-nowrap px-6 py-2.5">
        <Logo />
        <nav className="flex items-center gap-0.5 text-sm text-slate-600 max-[1120px]:hidden">
          {SITE_MENU.map(([label, href]) => (
            <Link key={href} href={href} className="rounded-full px-3 py-1.5 transition hover:bg-brand-50 hover:text-brand-700">{label}</Link>
          ))}
        </nav>
        <button type="button" className="hidden rounded-full p-2 text-slate-600 transition hover:bg-brand-50 hover:text-brand-700 max-[1120px]:block"
                aria-label="메뉴" aria-expanded={menu} onClick={() => setMenu(!menu)}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            {menu ? <path d="M4 4l10 10M14 4L4 14" /> : <path d="M2.5 4.5h13M2.5 9h13M2.5 13.5h13" />}
          </svg>
        </button>
        <div className="ml-auto flex items-center gap-1 text-sm">
          {me?.type === "candidate" ? (
            <>
              <span className={`mr-1 flex items-center gap-1.5 rounded-full py-1 pl-3 pr-1 text-xs ${left < 300 ? "bg-red-50 text-red-600" : "bg-slate-100 text-slate-500"}`}
                    data-testid="login-left" title="로그인 유지 시간">
                <span className="max-xl:hidden">로그인 유지</span>
                <b className="font-mono tabular-nums">{String(Math.floor(left / 60)).padStart(2, "0")}:{String(left % 60).padStart(2, "0")}</b>
                <button className="rounded-full bg-white px-2 py-0.5 font-medium text-slate-600 shadow-sm transition hover:text-brand-700" onClick={extend}>연장</button>
              </span>
              <Bell path={path} />
              <Link className={NAV_BTN} href="/me">내 정보</Link>
              <Link className={NAV_BTN} href="/me/applications">지원 현황</Link>
              <button className="btn-line ml-1 px-3.5 py-1.5" onClick={logout}>로그아웃</button>
            </>
          ) : (
            <>
              <Link className={NAV_BTN} href="/login">로그인</Link>
              <Link className="btn ml-1 px-4 py-1.5" href="/signup">회원가입</Link>
            </>
          )}
        </div>
      </div>
      {menu && (
        <nav className="border-t border-slate-200/70 px-4 py-2 text-sm text-slate-700 min-[1121px]:hidden" data-testid="site-menu">
          {SITE_MENU.map(([label, href]) => (
            <Link key={href} href={href} onClick={() => setTimeout(() => setMenu(false), 0)}   /* 이동이 먼저 (바로 닫으면 링크가 사라져 이동이 취소됨) */
                  className="block rounded-xl px-3 py-2.5 transition hover:bg-brand-50 hover:text-brand-700">{label}</Link>
          ))}
        </nav>
      )}
    </header>
  );
}

export type Contact = { team: string; phone: string; email: string; hours: string; onsite: string; assignee: string | null };

export function useContact(postingId?: number) {
  const [c, setC] = useState<Contact | null>(null);
  useEffect(() => {
    api<Contact>(`/site/contact${postingId ? `?posting_id=${postingId}` : ""}`).then(setC, () => {});
  }, [postingId]);
  return c;
}

/** 문의하기: 담당자 연락처 + 회사 방문 면접 안내 (사전 점검·응시 완료 화면에만. 면접 중에는 없음) */
export function ContactButton({ postingId, className = "btn-line" }: { postingId?: number; className?: string }) {
  const [open, setOpen] = useState(false);
  const c = useContact(postingId);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>문의하기</button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setOpen(false)}>
          <div className="card w-full max-w-md space-y-2 text-left text-slate-800" role="dialog" data-testid="contact" onClick={(e) => e.stopPropagation()}>
            <h2 className="font-semibold">채용 담당자 연락처</h2>
            {c ? (
              <>
                <p>{c.team}{c.assignee && ` · 담당 ${c.assignee}`}</p>
                <p>전화 <b>{c.phone}</b> · 메일 <b>{c.email}</b> ({c.hours})</p>
                <p className="rounded bg-amber-50 p-2 text-sm text-amber-900">{c.onsite}</p>
              </>
            ) : <p>불러오는 중…</p>}
            <div className="text-right"><button type="button" className="btn" onClick={() => setOpen(false)}>닫기</button></div>
          </div>
        </div>
      )}
    </>
  );
}

export function SiteFooter() {
  const c = useContact();
  return (
    <footer className="mt-16 border-t border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-6 py-6 text-xs text-slate-500">
        <span>© 2026 {COMPANY} (가상 회사 · 개발 시험용)</span>
        <span data-testid="footer-contact">채용 담당 {c ? `${c.team} · ${c.phone} · ${c.email} (${c.hours})` : "recruit@saebyeoksoft.example"}</span>
        <span>AI 화상면접은 영상을 저장하지 않고, 답변 음성은 텍스트로 바꾼 뒤 지웁니다.</span>
        <Link className="ml-auto text-slate-400 hover:text-slate-600" href="/admin/login">채용 담당자</Link>
      </div>
    </footer>
  );
}
