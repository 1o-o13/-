"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { SESSION } from "@/lib/labels";

type Posting = { id: number; title: string };
type Row = {
  id: number; status: string; name: string; interview_score: string | null; coding_score: string | null; total_score: string | null;
  fail_cut: boolean | null; ai_rank: number | null; ai_recommendation: string | null; q3_tier: string | null; sid: number | null;
  interview_status: string | null; coding_status: string | null; reserve_rank: number | null; decided_by: string | null; open_suspicions: number;
  announced: boolean;
};
type Board = { posting: { id: number; title: string; headcount: number; final_announce_at: string }; counts: { total: number; doc_failed: number; doc_passed: number }; rows: Row[];
  announcement: { published_at: string; published_by: string | null } | null };

const REC: Record<string, [string, string]> = { pass: ["합격 추천", "bg-emerald-100 text-emerald-800"], none: ["추천 없음", "bg-slate-100 text-slate-600"] };
const n = (v: string | null) => (v == null ? "-" : Number(v).toFixed(1));

/** 2차를 아직 마치지 않은 사람의 진행 상황 */
function progress(r: Row): string {
  if (r.coding_status !== "completed") return r.coding_status === "in_progress" ? "코딩 테스트 중" : "코딩 테스트 전";
  if (!r.interview_status || r.interview_status === "ready" || r.interview_status === "prechecked") return "AI 면접 전";
  if (r.interview_status === "completed") return "면접 끝 · 결과 확정 전";
  return SESSION[r.interview_status] ?? r.interview_status;
}

// ADM-042 최종 합격 결정: 1차 합격자를 2차 종합 점수 순으로 보고 AI 추천을 참고해 합격할 사람을 체크하고
// '결과 확정'을 한 번 누르면 체크한 사람은 합격, 나머지는 불합격으로 정해지고 모두에게 알림이 간다 (11/11, 예비 합격 없음)
export default function Final() {
  const router = useRouter();
  const [postings, setPostings] = useState<Posting[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [b, setB] = useState<Board | null>(null);
  const [msg, setMsg] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());   // 체크한 합격자 (화면에만, '결과 확정'을 눌러야 저장·알림)

  useEffect(() => {
    api<Posting[]>("/admin/postings").then((p) => (setPostings(p), setPid(p[0]?.id ?? null)), (e) => setMsg(errorText(e, router.push, true)));
  }, [router]);
  const load = useCallback(() => {
    if (pid) api<Board>(`/admin/postings/${pid}/final`).then((x) => (setB(x), setSel(new Set())), (e) => setMsg(e.message));
  }, [pid]);
  useEffect(load, [load]);

  const can = (r: Row) => !r.announced && !r.fail_cut && r.open_suspicions === 0;   // 합격으로 체크할 수 있는 사람
  function toggle(id: number) {
    setSel((x) => { const y = new Set(x); if (y.has(id)) y.delete(id); else y.add(id); return y; });
  }

  async function confirmAll() {
    const fail = open.length - picked;
    if (!confirm(`최종 결과를 확정하고 지원자에게 알릴까요?
체크한 ${picked}명 합격 · 나머지 ${fail}명 불합격
확정하면 메일·문자·홈페이지 알림이 가고 바꿀 수 없습니다.${waiting.length ? `
2차 진행 중인 ${waiting.length}명은 이번 확정에서 빠집니다 (점수가 확정되면 다시 확정).` : ""}`)) return;
    try {
      const r = await api<{ announced: number; passed: number; notifications: number }>(`/admin/postings/${pid}/final/announce`, { method: "POST", json: { pass_ids: [...sel] } });
      setMsg(`확정했습니다. 합격 ${r.passed}명 · 불합격 ${r.announced - r.passed}명, ${r.announced}명에게 알림 ${r.notifications}건을 보냈습니다 (메일·문자는 가짜 발송 기록).`);
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  const scored = b?.rows.filter((r) => r.ai_rank != null) ?? [];
  const waiting = b?.rows.filter((r) => r.ai_rank == null) ?? [];
  const decided = (s: string) => scored.filter((r) => r.announced && r.status === s).length;
  const open = scored.filter((r) => !r.announced);             // 아직 알리지 않은 사람 = 이번 확정 대상
  const picked = open.filter((r) => sel.has(r.id)).length;
  const eligible = open.filter(can);
  const all = eligible.length > 0 && eligible.every((r) => sel.has(r.id));
  const confirmBtn = (
    <button className="btn" disabled={!open.length} onClick={confirmAll} title={open.length ? undefined : "확정할 지원자가 없습니다"}>
      결과 확정 (합격 {picked}명 · 불합격 {open.length - picked}명)
    </button>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">최종 합격 결정</h1>
        <select className="input w-auto" value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))}>
          {postings.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
        <span className="ml-auto">
          {b?.announcement && !open.length ? (
            <span className="rounded bg-emerald-50 px-3 py-1.5 text-sm text-emerald-800">
              확정·알림 완료 · {new Date(b.announcement.published_at).toLocaleString("ko-KR")}{b.announcement.published_by && ` · ${b.announcement.published_by}`}
            </span>
          ) : open.length > 0 && confirmBtn}
        </span>
      </div>
      {msg && <p className="text-sm">{msg}</p>}
      {b && (
        <>
          <div className="grid grid-cols-5 gap-3">
            {([["지원자", b.counts.total], ["1차 합격", b.counts.doc_passed], ["2차 점수 확정", scored.length], ["모집 인원", b.posting.headcount],
               ["결정 (합격·불합격)", `${decided("final_passed")} · ${decided("final_failed")}`]] as [string, string | number][]).map(([l, v]) => (
              <div key={l} className="card"><p className="text-sm text-slate-500">{l}</p><p className="text-xl font-bold">{v}</p></div>
            ))}
          </div>
          <p className="text-xs text-slate-500">
            2차 종합 = 면접 60% + 코딩 40%. 과락(면접 50 미만 또는 코딩 40 미만)은 추천하지 않습니다.
            AI 추천(임시 규칙): 과락이 아닌 사람 중 위에서 모집 인원({b.posting.headcount}명)의 2배까지 합격 추천 (예비 합격 없음, 넉넉하게 뽑아 거름). 결정은 담당자가 합니다.
            합격할 사람만 체크하고 목록 위·아래의 &apos;결과 확정&apos;을 한 번 누르면 체크한 사람은 합격, 나머지는 모두 불합격으로 확정되고 알림이 갑니다.
          </p>

          <table className="card w-full text-sm">
            <thead className="text-left text-slate-500">
              <tr><th className="w-8 py-1">
                {open.length > 0 && <input type="checkbox" aria-label="전체 선택" checked={all} disabled={!eligible.length}
                  onChange={() => setSel(all ? new Set() : new Set(eligible.map((r) => r.id)))} />}
              </th><th className="py-1">순위</th><th>이름</th><th>면접</th><th>코딩</th><th>2차 종합</th><th>AI 추천</th><th>결정</th><th>결과 보기</th></tr>
            </thead>
            <tbody>
              {scored.map((r) => (
                <tr key={r.id} className="border-t border-slate-100" data-testid={`final-row-${r.id}`}>
                  <td className="py-2">
                    {!r.announced && <input type="checkbox" aria-label={`${r.name} 합격`} checked={sel.has(r.id)} disabled={!can(r)} onChange={() => toggle(r.id)}
                      title={can(r) ? undefined : r.fail_cut ? "과락이라 합격으로 고를 수 없습니다" : "처리하지 않은 의심 건이 있습니다"} />}
                  </td>
                  <td className="py-2 font-bold">{r.ai_rank}</td>
                  <td><Link className="text-brand-700 underline" href={`/admin/applicants/${r.id}`}>{r.name}</Link></td>
                  <td className={r.fail_cut && Number(r.interview_score) < 50 ? "font-semibold text-red-600" : ""}>{n(r.interview_score)}</td>
                  <td className={r.fail_cut && Number(r.coding_score) < 40 ? "font-semibold text-red-600" : ""}>{n(r.coding_score)} <span className="text-xs text-slate-400">{r.q3_tier}</span></td>
                  <td className="font-semibold">{n(r.total_score)}{r.fail_cut && <span className="ml-1 rounded bg-red-100 px-1 text-xs text-red-700">과락</span>}</td>
                  <td><span className={`rounded px-2 py-0.5 text-xs ${REC[r.ai_recommendation ?? "none"][1]}`}>{REC[r.ai_recommendation ?? "none"][0]}</span></td>
                  <td>
                    {r.announced ? (
                      <span className={`rounded px-2 py-0.5 text-xs text-white ${r.status === "final_passed" ? "bg-emerald-600" : "bg-slate-500"}`}>
                        {r.status === "final_passed" ? "합격" : "불합격"}
                      </span>
                    ) : (
                      <span className={`text-xs ${sel.has(r.id) ? "font-semibold text-emerald-700" : "text-slate-400"}`}>{sel.has(r.id) ? "합격" : "불합격 예정"}</span>
                    )}
                    {r.announced && r.decided_by && (
                      <span className="mt-0.5 block text-xs text-slate-500">
                        {r.decided_by ? `${r.decided_by} 결정` : ""}
                      </span>
                    )}
                    {r.open_suspicions > 0 && <span className="mt-0.5 block text-xs text-red-600">의심 건 {r.open_suspicions}건 처리 전 (합격 불가)</span>}
                  </td>
                  <td className="space-x-2 text-xs">
                    {r.sid && <Link className="text-brand-700 underline" href={`/admin/interviews/${r.sid}`}>면접</Link>}
                    <Link className="text-brand-700 underline" href={`/admin/applicants/${r.id}`}>이력서</Link>
                  </td>
                </tr>
              ))}
              {!scored.length && <tr><td colSpan={9} className="py-4 text-center text-slate-500">아직 2차 점수가 확정된 지원자가 없습니다.</td></tr>}
            </tbody>
          </table>
          {open.length > 0 && <div className="flex justify-end">{confirmBtn}</div>}

          {waiting.length > 0 && (
            <div className="card text-sm">
              <p className="mb-2 font-semibold">2차 진행 중 ({waiting.length}명) · 점수가 확정되면 위 순위에 들어갑니다</p>
              {waiting.map((r) => (
                <p key={r.id} className="py-0.5">
                  <Link className="text-brand-700 underline" href={`/admin/applicants/${r.id}`}>{r.name}</Link>
                  <span className="ml-2 text-slate-500">{progress(r)}</span>
                  {r.sid && r.interview_status === "completed" && <Link className="ml-2 text-xs text-brand-700 underline" href={`/admin/interviews/${r.sid}`}>결과 확정하러 가기</Link>}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
