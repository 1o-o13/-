"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { EVAL, SESSION } from "@/lib/labels";

type Posting = { id: number; title: string };
type Row = {
  id: number; attempt_no: number; exam_code: string; status: string; candidate_name: string; ended_at: string | null;
  version_no: number | null; total_score: string | null; evaluation_status: string | null; confirmed_at: string | null; open_suspicions: number;
};
/** IV-00003-1 → IV-3 (앞자리 0과 차수는 뺌, 차수는 옆 칸에 따로 보임) */
const shortCode = (c: string) => c.replace(/^(\w+)-0*(\d+)-\d+$/, "$1-$2");

// AI 면접 결과 목록 (공고별)
export default function Interviews() {
  const router = useRouter();
  const [postings, setPostings] = useState<Posting[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Posting[]>("/admin/postings").then(
      (p) => (setPostings(p), setPid(p[0]?.id ?? null)),
      (e) => setErr(errorText(e, router.push, true)),
    );
  }, [router]);
  useEffect(() => {
    if (pid) api<Row[]>(`/admin/interviews?posting_id=${pid}`).then(setRows, (e) => setErr(e.message));
  }, [pid]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">AI 면접 결과</h1>
        <select className="input w-auto" value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))}>
          {postings.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
      </div>
      {err && <p className="err">{err}</p>}
      {pid && <Accommodations pid={pid} />}
      <table className="card w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr><th>응시 번호</th><th>지원자</th><th>차수</th><th>상태</th><th>면접 점수</th><th>AI 검증</th><th>확정</th><th>미결 의심 건</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-slate-100">
              <td><Link className="text-brand-700" href={`/admin/interviews/${r.id}`}>{shortCode(r.exam_code)}</Link></td>
              <td>{r.candidate_name}</td>
              <td>{r.attempt_no}차</td>
              <td>{SESSION[r.status] ?? r.status}</td>
              <td>{r.total_score == null ? "-" : Number(r.total_score).toFixed(1)}</td>
              <td>{r.evaluation_status ? EVAL[r.evaluation_status] : "-"}</td>
              <td>{r.confirmed_at ? "확정" : "-"}</td>
              <td>{r.open_suspicions || "-"}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={8} className="py-4 text-center text-slate-500">응시가 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

type Acc = { id: number; application_id: number; name: string; reason: string; status: "requested" | "approved" | "rejected";
  decision_note: string | null; decided_by: string | null; decided_at: string | null };
const ACC = { requested: "확인 대기", approved: "승인", rejected: "거절" } as const;

/** 글로 답하기 신청 (응시 편의, 11/12): 담당관이 사유를 보고 승인·거절. 면접을 시작한 뒤에는 바꿀 수 없음 */
function Accommodations({ pid }: { pid: number }) {
  const [rows, setRows] = useState<Acc[]>([]);
  const [msg, setMsg] = useState("");
  const load = () => api<Acc[]>(`/admin/accommodations?posting_id=${pid}`).then(setRows, (e) => setMsg(e.message));
  useEffect(() => { load(); }, [pid]); // eslint-disable-line react-hooks/exhaustive-deps
  async function decide(id: number, approve: boolean) {
    const note = approve ? null : prompt("거절 사유 (지원자에게 보입니다)") ?? null;
    try {
      await api(`/admin/accommodations/${id}/decision`, { method: "POST", json: { approve, note } });
      load();
    } catch (e) { setMsg(e instanceof Error ? e.message : "처리하지 못했습니다"); }
  }
  if (!rows.length) return null;
  return (
    <div className="card space-y-2 text-sm" data-testid="accommodations">
      <h2 className="font-semibold">글로 답하기 신청 ({rows.filter((r) => r.status === "requested").length}건 대기)</h2>
      <table className="w-full">
        <thead className="text-left text-slate-500"><tr><th className="py-1">지원자</th><th>사유</th><th>상태</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-slate-100 align-top">
              <td className="py-1.5"><Link className="text-brand-700 underline" href={`/admin/applicants/${r.application_id}`}>{r.name}</Link></td>
              <td className="max-w-md">{r.reason}</td>
              <td>{ACC[r.status]}{r.decided_by && <span className="block text-xs text-slate-500">{r.decided_by}{r.decision_note && ` · ${r.decision_note}`}</span>}</td>
              <td className="whitespace-nowrap">
                {r.status === "requested" && (
                  <>
                    <button className="btn mr-1 px-3 py-1" onClick={() => decide(r.id, true)}>승인</button>
                    <button className="btn-line px-3 py-1" onClick={() => decide(r.id, false)}>거절</button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {msg && <p className="err">{msg}</p>}
    </div>
  );
}
