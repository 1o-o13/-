"use client";
// 개발용 바로 로그인 버튼 (API의 DEV_QUICK_LOGIN=1일 때만 보임·동작. 웹이 운영 빌드여도 같음, 11/10). 계정은 seed/demo_accounts.sql
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const ACCOUNTS = {
  candidate: [["cand1", "김하늘 · 2차 면접 대상 (상)"], ["cand2", "오세훈 · 2차 면접 대상 (하)"], ["cand3", "박지민 · 아직 지원 안 함"], ["cand4", "이준서 · 코딩 테스트 전"]],
  admin: [["admin", "최고관리자 (admin)"], ["hr01", "채용 담당 김인사 (hr01)"]],
} as const;

/** 개발용 기능(바로 로그인·응시 기록 초기화·설정 잠금 풀기·카메라 점검)을 보일지: API의 DEV_QUICK_LOGIN=1 (운영 .env에는 넣지 않음) */
export function useDevTools(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    api<{ enabled: boolean }>("/auth/dev/enabled").then((r) => setOn(r.enabled), () => setOn(false));
  }, []);
  return on;
}

export function QuickLogin({ kind }: { kind: "candidate" | "admin" }) {
  const router = useRouter();
  const [err, setErr] = useState("");
  const on = useDevTools();
  if (!on) return null;

  async function go(who: string) {
    try {
      await api(`/auth/dev/login/${who}`, { method: "POST" });
      router.push(kind === "candidate" ? "/" : "/admin/interviews");
    } catch (e) {
      setErr((e as Error).message === "Not Found" ? "바로 로그인이 꺼져 있습니다 (.env DEV_QUICK_LOGIN=1)" : (e as Error).message);
    }
  }

  return (
    <div className="space-y-2 rounded border border-dashed border-slate-300 p-3">
      <p className="text-xs text-slate-500">개발용 · 시험 계정으로 바로 로그인 (비밀번호 Test1234!)</p>
      {ACCOUNTS[kind].map(([who, label]) => (
        <button key={who} type="button" className="btn-line w-full text-sm" onClick={() => go(who)}>
          {label}
        </button>
      ))}
      {err && <p className="err">{err}</p>}
    </div>
  );
}
