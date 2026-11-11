"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { CAREER, ROLES, STATUS } from "@/lib/posting";

// 채용 공고 관리 (ADM-020~024, 임시: 공고 파트 정식 기능이 오면 교체)
// 부서 채용 요청 → 채용 담당이 공고로 작성 → 요청 부서 확인 → 게시 → 마감. 부서 요청 없이 바로 만든 공고는 확인 없이 게시
type Posting = {
  id: number; title: string; job_role: string; job_category: string; career_level: string; headcount: number; status: string;
  apply_start: string; apply_end: string; applicants: number; main_assignee: string | null; request_dept: string | null; review: string | null;
};
type Req = {
  id: number; title: string; job_role: string; headcount: number; career_level: string; reason: string | null; status: string;
  department: string; requested_by: string; handled_by: string | null; posting_id: number | null; created_at: string;
};

const REQ: Record<string, string> = { draft: "작성 중", submitted: "접수", accepted: "접수", rejected: "반려", converted: "공고로 만듦" };
const day = (s: string) => new Date(s).toLocaleDateString("ko-KR");

export default function Postings() {
  const router = useRouter();
  const [rows, setRows] = useState<Posting[]>([]);
  const [reqs, setReqs] = useState<Req[]>([]);
  const [role, setRole] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState<{ title: string; job_role: string; headcount: number; career_level: string; reason: string } | null>(null);

  const load = useCallback(() => {
    api<Posting[]>("/admin/postings/all").then(setRows, (e) => setMsg(errorText(e, router.push, true)));
    api<Req[]>("/admin/hiring-requests").then(setReqs, () => {});
  }, [router]);
  useEffect(() => {
    api<{ role: string }>("/auth/me?as=admin").then((m) => setRole(m.role), () => {});
    load();
  }, [load]);
  const write = role === "super_admin" || role === "recruiter";

  async function request() {
    try {
      await api("/admin/hiring-requests", { method: "POST", json: { ...form, headcount: Number(form!.headcount) } });
      setForm(null);
      setMsg("채용 요청을 올렸습니다. 채용 담당이 공고로 만듭니다.");
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }
  async function reject(r: Req) {
    if (!confirm(`'${r.title}' 요청을 반려할까요?`)) return;
    try {
      await api(`/admin/hiring-requests/${r.id}/reject`, { method: "POST" });
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">채용 공고</h1>
        <span className="flex-1" />
        {write && <Link className="btn" href="/admin/postings/new">새 공고 작성</Link>}
      </div>
      {msg && <p className="text-sm">{msg}</p>}
      <p className="text-xs text-slate-500">
        부서가 채용을 요청하면 채용 담당이 공고로 작성하고, 요청 부서의 확인(승인)을 받은 뒤 게시합니다. 부서 요청 없이 바로 만든 공고는 확인 없이 게시합니다.
        공고를 만들면 AI 면접 설정·코딩 테스트 설정(개발 직군)이 기본값으로 함께 만들어집니다.
      </p>

      <table className="card w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr><th className="py-2">번호</th><th>공고</th><th>직무 · 경력</th><th>모집</th><th>접수 기간</th><th>지원자</th><th>담당 · 요청 부서</th><th>상태</th></tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id} className="border-t border-slate-100" data-testid={`posting-${p.id}`}>
              <td className="py-2 font-bold">{p.id}</td>
              <td><Link className="text-brand-700 underline" href={`/admin/postings/${p.id}`}>{p.title}</Link></td>
              <td>{p.job_role} · {p.job_category === "dev" ? "개발" : "비개발"} · {CAREER[p.career_level]}</td>
              <td>{p.headcount}명</td>
              <td className="text-xs">{day(p.apply_start)} ~ {day(p.apply_end)}</td>
              <td>{p.applicants}명</td>
              <td className="text-xs">{p.main_assignee ?? "-"}{p.request_dept && ` · ${p.request_dept}`}</td>
              <td>
                <span className={`rounded px-2 py-0.5 text-xs ${STATUS[p.status][1]}`}>{STATUS[p.status][0]}</span>
                {p.review === "changes_requested" && p.status === "draft" && <span className="ml-1 text-xs text-amber-700">수정 요청 받음</span>}
              </td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={8} className="py-4 text-center text-slate-500">공고가 없습니다.</td></tr>}
        </tbody>
      </table>

      <div className="card space-y-3 text-sm">
        <div className="flex items-center">
          <h2 className="font-semibold">부서 채용 요청</h2>
          <span className="flex-1" />
          {role !== "sys_admin" && !form && (
            <button className="btn-line text-xs" onClick={() => setForm({ title: "", job_role: ROLES[0], headcount: 1, career_level: "new", reason: "" })}>채용 요청하기</button>
          )}
        </div>
        {form && (
          <div className="grid grid-cols-2 gap-2" data-testid="request-form">
            <label>요청 제목<input className="input" name="req_title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
            <label>직무<select className="input" value={form.job_role} onChange={(e) => setForm({ ...form, job_role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></label>
            <label>인원<input className="input" type="number" min={1} value={form.headcount} onChange={(e) => setForm({ ...form, headcount: Number(e.target.value) })} /></label>
            <label>경력<select className="input" value={form.career_level} onChange={(e) => setForm({ ...form, career_level: e.target.value })}>{Object.entries(CAREER).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="col-span-2">이유<textarea className="input h-20" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
            <span className="col-span-2 flex gap-2"><button className="btn" onClick={request}>요청 올리기</button><button className="btn-line" onClick={() => setForm(null)}>취소</button></span>
          </div>
        )}
        <table className="w-full">
          <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">요청</th><th>부서 · 요청자</th><th>직무 · 인원</th><th>이유</th><th>상태</th><th /></tr></thead>
          <tbody>
            {reqs.map((r) => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="py-1.5">{r.title}</td>
                <td className="text-xs">{r.department} · {r.requested_by}</td>
                <td className="text-xs">{r.job_role} · {r.headcount}명 · {CAREER[r.career_level]}</td>
                <td className="max-w-xs text-xs text-slate-600">{r.reason}</td>
                <td className="text-xs">{REQ[r.status]}{r.handled_by && ` (${r.handled_by})`}</td>
                <td className="space-x-2 text-xs">
                  {r.posting_id && <Link className="text-brand-700 underline" href={`/admin/postings/${r.posting_id}`}>공고 보기</Link>}
                  {write && (r.status === "submitted" || r.status === "accepted") && (
                    <>
                      <Link className="text-brand-700 underline" href={`/admin/postings/new?request=${r.id}`}>공고로 만들기</Link>
                      <button className="text-red-700 underline" onClick={() => reject(r)}>반려</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!reqs.length && <tr><td colSpan={6} className="py-3 text-center text-slate-500">요청이 없습니다.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
