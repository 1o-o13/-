"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";

type Item = {
  id: number; slot: number; tier: string; type: string; origin: string; statement: string; language: string;
  assigned_reason: Record<string, any> | null; solution_python: string; solution_java: string; submissions: number; paste_attempts: number;
  best: { language: string; code: string; group_scores: Record<string, number>; partial_score: string; submitted_at: string } | null;
  review: { rubric: Record<string, string>; summary: { algorithms: string[]; failed_groups: number[]; weakness_tags: string[] }; quality_level: string; model: string } | null;
};
type Detail = {
  session: { id: number; status: string; started_at: string; ended_at: string | null; application_id: number; name: string; posting: string };
  result: { p1: string; p2: string; q3_base_tier: string; q3_tier: string; q3_partial: string; q3_converted: string; score_table_version: string;
    fallback_flags: Record<string, any> | null; weakness_summary: { algorithms: string[]; failed_groups: number[]; weakness_tags: string[] } } | null;
  items: Item[];
};
const STATUS: Record<string, string> = { in_progress: "진행 중", completed: "완료", abandoned: "포기", system_error: "시스템 오류" };
const ORIGIN: Record<string, string> = { collected: "문제 모음", generated: "AI 출제(검증 통과)" };

// ADM-034 코딩 테스트 결과: 3번 환산 점수 먼저, 문항별 문제·제출 코드·그룹별 결과·리뷰
export default function CodingDetail() {
  const csid = useParams<{ csid: string }>().csid;
  const router = useRouter();
  const [d, setD] = useState<Detail | null>(null);
  const [msg, setMsg] = useState("");
  const [sol, setSol] = useState<Record<number, string>>({}); // 문항 → 보고 있는 코드 (제출 / 정답 Python / 정답 Java)
  const [role, setRole] = useState("");

  useEffect(() => {
    api<Detail>(`/admin/coding/${csid}`).then(setD, (e) => setMsg(errorText(e, router.push, true)));
    api<{ role: string }>("/auth/me?as=admin").then((m) => setRole(m.role), () => {});
  }, [csid, router]);

  async function reset() {
    if (!confirm("개발용: 이 코딩 응시 기록을 지우고 처음부터 다시 볼 수 있게 할까요?")) return;
    try {
      await api(`/admin/coding/${csid}/reset`, { method: "POST" });
      router.push("/admin/applicants");
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  if (msg && !d) return <p className="err">{msg}</p>;
  if (!d) return <p>불러오는 중…</p>;
  const { session: s, result: r } = d;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link href="/admin/applicants" className="text-sm text-slate-500">← 지원자 현황</Link>
        <h1 className="text-xl font-bold">코딩 테스트 결과 · {s.name}</h1>
        <span className="text-sm text-slate-500">{s.posting} · {STATUS[s.status] ?? s.status}</span>
        {role === "super_admin" && <button className="btn-line ml-auto" onClick={reset}>코딩 기록 초기화(개발용)</button>}
      </div>
      {msg && <p className="err">{msg}</p>}

      {r ? (
        <div className="grid gap-3 md:grid-cols-4">
          <div className="card">
            <p className="text-sm text-slate-500">코딩 점수 (3번 환산)</p>
            <p className="text-3xl font-bold">{Number(r.q3_converted)}</p>
            <p className="text-xs text-slate-500">점수표 {r.score_table_version}</p>
          </div>
          <div className="card text-sm">
            <p className="font-semibold">3번 등급</p>
            <p>{r.q3_tier}{r.q3_base_tier !== r.q3_tier ? ` (기본 ${r.q3_base_tier})` : ""}</p>
            <p className="text-slate-500">1·2번 평균 {(Number(r.p1) + Number(r.p2)) / 2}점으로 정함</p>
          </div>
          <div className="card text-sm">
            <p className="font-semibold">부분 점수</p>
            <p>1번 {Number(r.p1)} · 2번 {Number(r.p2)} · 3번 {Number(r.q3_partial)}</p>
          </div>
          <div className="card text-sm">
            <p className="font-semibold">약점 요약 (면접 3번 질문 입력)</p>
            <p>{[...r.weakness_summary.algorithms, ...r.weakness_summary.weakness_tags].join(" · ") || "-"}</p>
            <p className="text-slate-500">틀린 입력 단계: {r.weakness_summary.failed_groups.join(", ") || "없음"}</p>
          </div>
          {r.fallback_flags && (
            <p className="text-xs text-amber-700 md:col-span-4">대체 경로: {r.fallback_flags.q3}</p>
          )}
        </div>
      ) : (
        <p className="card text-sm">아직 끝나지 않은 응시입니다.</p>
      )}

      {d.items.map((it) => {
        const view = sol[it.slot] ?? "best";
        const code = view === "python" ? it.solution_python : view === "java" ? it.solution_java : it.best?.code ?? "(제출 없음)";
        const reason = it.assigned_reason ?? {};
        return (
          <div key={it.id} className="card space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-bold">{it.slot}번 · {it.statement.split("\n")[0].replace(/^# /, "")}</h2>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{it.tier} · {it.type}</span>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{ORIGIN[it.origin] ?? it.origin}</span>
              <span className="text-xs text-slate-500">
                제출 {it.submissions}번 · 붙여넣기 시도 {it.paste_attempts}번 · 가장 좋은 제출 {it.best ? `${Number(it.best.partial_score)}점 (${it.best.language})` : "-"}
              </span>
            </div>
            <p className="text-xs text-slate-500">
              배정: {reason.rule ?? "-"}{reason.model ? ` · 출제 모델 ${reason.model}` : ""}{reason.fallback ? ` · ${reason.fallback.q3}` : ""}
            </p>
            {it.best && (
              <p className="text-sm">
                입력 단계별: {Object.entries(it.best.group_scores).map(([g, v]) => `${g}단계 ${v}/20`).join(" · ")}
              </p>
            )}
            {it.review && (
              <div className="rounded-md bg-slate-50 p-3 text-sm">
                <p className="font-semibold">코드 리뷰 · 수준 {it.review.quality_level} <span className="rounded bg-slate-100 px-1.5 text-xs font-normal text-slate-600">점수 미반영 · 근거 텍스트로만</span> <span className="text-xs font-normal text-slate-500">({it.review.model === "stub" ? "채점 결과 기반 임시 리뷰" : it.review.model})</span></p>
                {Object.entries(it.review.rubric).map(([k, v]) => <p key={k}>{k}: {v}</p>)}
              </div>
            )}
            <div className="flex items-center gap-2 text-sm">
              <select value={view} onChange={(e) => setSol({ ...sol, [it.slot]: e.target.value })} className="rounded border border-slate-300 px-2 py-1" aria-label="코드 보기">
                <option value="best">지원자 제출 코드</option>
                <option value="python">정답 코드 (Python)</option>
                <option value="java">정답 코드 (Java)</option>
              </select>
              <details className="ml-2"><summary className="cursor-pointer text-slate-500">지문 보기</summary>
                <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-3 text-xs">{it.statement}</pre>
              </details>
            </div>
            <pre className="max-h-96 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{code}</pre>
          </div>
        );
      })}
    </div>
  );
}
