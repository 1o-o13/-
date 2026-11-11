"use client";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { CAREER, ROLES, STATUS } from "@/lib/posting";

// 공고 작성·수정 (ADM-022~024). /admin/postings/new(?request=요청 번호) 이면 새로 작성
type Form = {
  title: string; job_role: string; job_category: string; career_level: string; headcount: number; description: string;
  apply_start: string; apply_end: string; doc_announce_at: string; stage2_start: string; stage2_end: string; final_announce_at: string;
  languages: string[]; coding_minutes: number; hiring_request_id: number | null;
};
type Detail = {
  posting: Record<string, string | number | null> & { status: string; hiring_request_id: number | null; request_dept_name: string | null; request_dept: number | null };
  coding: { languages: string[]; time_limit_min: number } | null;
  assignees: { id: number; name: string; role: string }[];
  reviews: { decision: string; comment: string | null; created_at: string; reviewer: string }[];
  history: { change: { action: string; fields?: Record<string, [string, string]> }; created_at: string; by: string }[];
  applicants: number; can_review: boolean;
};
type Req = { id: number; title: string; job_role: string; headcount: number; career_level: string; reason: string | null; department: string };

const DATES: [keyof Form, string][] = [["apply_start", "접수 시작"], ["apply_end", "접수 마감"], ["doc_announce_at", "1차 발표"],
  ["stage2_start", "2차 응시 시작"], ["stage2_end", "2차 응시 마감"], ["final_announce_at", "최종 발표"]];
const LABEL: Record<string, string> = { title: "제목", job_role: "직무", job_category: "직군", career_level: "경력", headcount: "모집 인원", description: "설명",
  ...Object.fromEntries(DATES.map(([k, v]) => [k, v])) };
const local = (iso: string) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const at = (days: number, h = 10) => { const d = new Date(); d.setDate(d.getDate() + days); d.setHours(h, 0, 0, 0); return local(d.toISOString()); };
const BLANK: Form = { title: "", job_role: ROLES[0], job_category: "dev", career_level: "new", headcount: 1, description: "",
  apply_start: at(1), apply_end: at(15, 18), doc_announce_at: at(18), stage2_start: at(19), stage2_end: at(25, 18), final_announce_at: at(28),
  languages: ["python", "java"], coding_minutes: 90, hiring_request_id: null };

export default function Page() {
  return <Suspense><PostingEdit /></Suspense>;
}

function PostingEdit() {
  const pid = useParams<{ pid: string }>().pid;
  const isNew = pid === "new";
  const reqId = useSearchParams().get("request");
  const router = useRouter();
  const [f, setF] = useState<Form | null>(isNew ? BLANK : null);
  const [d, setD] = useState<Detail | null>(null);
  const [req, setReq] = useState<Req | null>(null);
  const [role, setRole] = useState("");
  const [msg, setMsg] = useState("");
  const [comment, setComment] = useState("");

  const load = useCallback(() => {
    if (isNew) return;
    api<Detail>(`/admin/postings/${pid}`).then((x) => {
      setD(x);
      const p = x.posting;
      setF({ ...(Object.fromEntries(Object.keys(BLANK).map((k) => [k, p[k] ?? (BLANK as Record<string, unknown>)[k]])) as Form),
        ...Object.fromEntries(DATES.map(([k]) => [k, local(String(p[k]))])),
        languages: x.coding?.languages ?? BLANK.languages, coding_minutes: x.coding?.time_limit_min ?? 90 });
    }, (e) => setMsg(errorText(e, router.push, true)));
  }, [isNew, pid, router]);
  useEffect(() => {
    api<{ role: string }>("/auth/me?as=admin").then((m) => setRole(m.role), () => {});
    load();
  }, [load]);
  useEffect(() => {                                       // 부서 요청에서 만들기: 요청 내용으로 채운다
    if (!isNew || !reqId) return;
    api<Req[]>("/admin/hiring-requests").then((rs) => {
      const r = rs.find((x) => String(x.id) === reqId);
      if (!r) return;
      setReq(r);
      setF((x) => ({ ...x!, title: r.title, job_role: r.job_role, headcount: r.headcount, career_level: r.career_level,
        description: r.reason ? `${r.reason}\n` : "", hiring_request_id: r.id }));
    }, () => {});
  }, [isNew, reqId]);

  const write = role === "super_admin" || role === "recruiter";
  const status = d?.posting.status ?? "draft";
  const editable = write && (isNew || (status !== "closed" && status !== "finished"));
  const lockedKind = !!d?.applicants;                   // 지원자가 있으면 직무·직군·경력은 못 바꿈
  const fromRequest = isNew ? !!f?.hiring_request_id : !!d?.posting.hiring_request_id;
  const lastReview = d?.reviews.at(-1);
  const canReview = !!d?.can_review;

  async function act(path: string, done: string, json?: object) {
    try {
      await api(`/admin/postings/${pid}${path}`, { method: "POST", ...(json ? { json } : {}) });
      setMsg(done);
      setComment("");
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }
  async function save() {
    const body = { ...f!, headcount: Number(f!.headcount), coding_minutes: Number(f!.coding_minutes),
      ...Object.fromEntries(DATES.map(([k]) => [k, new Date(String(f![k])).toISOString()])) };
    try {
      if (isNew) {
        const r = await api<{ id: number }>("/admin/postings", { method: "POST", json: body });
        router.replace(`/admin/postings/${r.id}`);
      } else {
        const r = await api<{ changed: string[] }>(`/admin/postings/${pid}`, { method: "PUT", json: body });
        setMsg(r.changed.length ? `저장했습니다 (바뀐 칸: ${r.changed.map((k) => LABEL[k] ?? k).join(", ")})` : "바뀐 내용이 없습니다.");
        load();
      }
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }
  async function remove() {
    if (!confirm("작성 중인 공고를 지울까요? 되돌릴 수 없습니다.")) return;
    try {
      await api(`/admin/postings/${pid}`, { method: "DELETE" });
      router.push("/admin/postings");
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  if (!f) return <p className="text-slate-500">{msg || "불러오는 중…"}</p>;
  const set = (k: keyof Form, v: unknown) => setF({ ...f, [k]: v });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link className="text-sm text-brand-700 underline" href="/admin/postings">← 공고 목록</Link>
        <h1 className="text-xl font-bold">{isNew ? "새 공고 작성" : f.title}</h1>
        {!isNew && <span className={`rounded px-2 py-0.5 text-xs ${STATUS[status][1]}`}>{STATUS[status][0]}</span>}
        <span className="flex-1" />
        {!isNew && write && status === "draft" && fromRequest && <button className="btn-line" onClick={() => act("/submit-review", "요청 부서에 확인을 요청했습니다.")}>부서 확인 요청</button>}
        {!isNew && write && ((status === "draft" && !fromRequest) || (status === "dept_review" && lastReview?.decision === "approved")) && (
          <button className="btn" onClick={() => confirm("공고를 게시할까요? 채용 홈에 보이고 접수 기간에 지원을 받습니다.") && act("/publish", "게시했습니다. 채용 홈에 보입니다.")}>게시</button>
        )}
        {!isNew && write && status === "published" && <button className="btn-line" onClick={() => confirm("공고를 마감할까요?") && act("/close", "마감했습니다.")}>마감</button>}
        {!isNew && write && (status === "draft" || status === "dept_review") && <button className="text-sm text-red-700 underline" onClick={remove}>삭제</button>}
      </div>
      {msg && <p className="text-sm">{msg}</p>}
      {req && <p className="card text-sm">부서 요청에서 만듭니다: <b>{req.department}</b> · {req.title} · {req.headcount}명 {req.reason && `· ${req.reason}`}</p>}
      {status === "draft" && lastReview?.decision === "changes_requested" && (
        <p className="card border-amber-200 bg-amber-50 text-sm">요청 부서 수정 요청 ({lastReview.reviewer}): {lastReview.comment} — 고친 뒤 다시 확인을 요청하세요.</p>
      )}
      {canReview && (
        <div className="card space-y-2 text-sm" data-testid="review-box">
          <p className="font-semibold">요청 부서 확인 ({d!.posting.request_dept_name})</p>
          <textarea className="input h-16 w-full" placeholder="의견 (수정 요청이면 필수)" value={comment} onChange={(e) => setComment(e.target.value)} />
          <span className="flex gap-2">
            <button className="btn" onClick={() => act("/review", "승인했습니다. 채용 담당이 게시합니다.", { decision: "approved", comment: comment || null })}>승인</button>
            <button className="btn-line" onClick={() => act("/review", "수정을 요청했습니다.", { decision: "changes_requested", comment })}>수정 요청</button>
          </span>
        </div>
      )}

      <fieldset disabled={!editable} className="card grid grid-cols-2 gap-3 text-sm" data-testid="posting-form">
        <label className="col-span-2">제목<input className="input" name="title" value={f.title} onChange={(e) => set("title", e.target.value)} /></label>
        <label>직무<select className="input" name="job_role" disabled={lockedKind} value={f.job_role} onChange={(e) => set("job_role", e.target.value)}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></label>
        <label>직군<select className="input" name="job_category" disabled={lockedKind} value={f.job_category} onChange={(e) => set("job_category", e.target.value)}>
          <option value="dev">개발 (코딩 테스트 + AI 면접)</option><option value="non_dev">비개발 (AI 면접만)</option></select></label>
        <label>경력<select className="input" name="career_level" disabled={lockedKind} value={f.career_level} onChange={(e) => set("career_level", e.target.value)}>
          {Object.entries(CAREER).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>모집 인원<input className="input" type="number" name="headcount" min={1} value={f.headcount} onChange={(e) => set("headcount", e.target.value)} /></label>
        <label className="col-span-2">설명 (자격·우대 사항. 1차 평가 기준과 AI 면접 회사 요구사항의 출발점)
          <textarea className="input h-32" name="description" value={f.description} onChange={(e) => set("description", e.target.value)} /></label>
        {DATES.map(([k, l]) => (
          <label key={k}>{l}<input className="input" type="datetime-local" name={k} value={String(f[k])} onChange={(e) => set(k, e.target.value)} /></label>
        ))}
        {f.job_category === "dev" && (
          <>
            <span>코딩 테스트 언어
              <span className="mt-1 flex gap-3">{["python", "java"].map((l) => (
                <label key={l} className="flex items-center gap-1"><input type="checkbox" checked={f.languages.includes(l)}
                  onChange={() => set("languages", f.languages.includes(l) ? f.languages.filter((x) => x !== l) : [...f.languages, l])} />{l === "python" ? "Python" : "Java"}</label>
              ))}</span>
            </span>
            <label>코딩 테스트 시간 (분)<input className="input" type="number" min={10} max={300} value={f.coding_minutes} onChange={(e) => set("coding_minutes", e.target.value)} /></label>
          </>
        )}
        {editable && <span className="col-span-2"><button type="button" className="btn" onClick={save}>{isNew ? "작성 (작성 중으로 저장)" : "저장"}</button>
          {lockedKind && <span className="ml-2 text-xs text-slate-500">지원자가 있어 직무·직군·경력은 바꿀 수 없습니다</span>}</span>}
      </fieldset>

      {d && (
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="card space-y-1">
            <p className="font-semibold">설정 · 담당</p>
            <p>담당자: {d.assignees.map((a) => `${a.name} (${a.role === "main" ? "정" : "부"})`).join(", ") || "-"}</p>
            <p>지원자 {d.applicants}명 {fromRequest && `· 요청 부서 ${d.posting.request_dept_name}`}</p>
            <p className="space-x-3">
              <Link className="text-brand-700 underline" href={`/admin/postings/${pid}/interview-setting`}>AI 면접 설정</Link>
              <Link className="text-brand-700 underline" href="/admin/documents">1차 서류 결정</Link>
            </p>
          </div>
          <div className="card space-y-1">
            <p className="font-semibold">기록</p>
            {d.reviews.map((r, i) => <p key={`r${i}`} className="text-xs">{new Date(r.created_at).toLocaleString("ko-KR")} {r.reviewer} 부서 확인: {r.decision === "approved" ? "승인" : "수정 요청"}{r.comment && ` · ${r.comment}`}</p>)}
            {d.history.map((h, i) => (
              <p key={i} className="text-xs text-slate-600">{new Date(h.created_at).toLocaleString("ko-KR")} {h.by} {h.change.action}
                {h.change.fields && ` · ${Object.entries(h.change.fields).map(([k, [a, b]]) => `${LABEL[k] ?? k} ${k.endsWith("_at") || k.startsWith("apply") || k.startsWith("stage") ? "" : `${a} → ${b}`}`).join(", ")}`}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
