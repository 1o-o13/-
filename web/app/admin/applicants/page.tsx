"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { SESSION, VALUE } from "@/lib/labels";

type Posting = { id: number; title: string };
type Row = {
  id: number; status: string; name: string; email: string; gender: string; age: number; test_level: string | null; doc_status: string | null;
  stage: string; ai_conclusion: string | null; deficit_value: string | null; q3_tier: string | null; interview_status: string | null;
};
type Detail = {
  application: { resume_snapshot: Record<string, any>; submitted_at: string };
  document: { criteria_scores: Record<string, unknown>; rationale: string; handoff: Record<string, string>; status: string } | null;
  coding: { session_id: number; p1: string; p2: string; q3_tier: string; q3_converted: string; weakness_summary: { algorithms: string[]; failed_groups: number[]; weakness_tags: string[] } } | null;
};

// 상세 단계 11종 (DB TRD 11-08, api/stage.py LABEL과 같음)
const STAGE: Record<string, string> = { submitted: "서류 접수", screen_passed: "1차 합격", screen_rejected: "1차 불합격",
  coding_waiting: "합격 후 단계 끝", scheduled: "응시 안내 발송", coding: "코딩 테스트", interview: "화상 면접", final_pass: "최종 합격", final_fail: "최종 불합격", withdrawn: "지원 취소" };
const APP: Record<string, string> = { submitted: "서류 심사", doc_passed: "서류 합격", doc_failed: "서류 불합격", stage2: "2차 대상", stage2_done: "2차 완료", final_passed: "최종 합격", reserve: "예비", final_failed: "최종 불합격", withdrawn: "취소", abandoned: "응시 포기" };
const BAND: Record<string, string> = { 골드2: "상", 골드3: "상", 골드4: "중", 골드5: "하", 실버1: "하" };

// 지원자 현황: 지원자 목록(성별·나이·1차·코딩) → 이력서 원본 (관리자에게는 인적사항이 그대로 보임, P-02)
export default function Applicants() {
  const router = useRouter();
  const [postings, setPostings] = useState<Posting[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [open, setOpen] = useState<{ row: Row; d: Detail } | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Posting[]>("/admin/postings").then(
      (p) => (setPostings(p), setPid(p[0]?.id ?? null)),
      (e) => setErr(errorText(e, router.push, true)),
    );
  }, [router]);
  useEffect(() => {
    if (pid) api<Row[]>(`/admin/applications?posting_id=${pid}`).then(setRows, (e) => setErr(e.message));
  }, [pid]);

  async function show(row: Row) {
    setOpen({ row, d: await api<Detail>(`/admin/applications/${row.id}`) });
  }

  const men = rows.filter((r) => r.gender === "남").length;
  const ages = rows.map((r) => r.age);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">지원자 현황</h1>
        <select className="input w-auto" value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))}>
          {postings.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
      </div>
      {err && <p className="err">{err}</p>}
      {rows.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          {[["지원자", `${rows.length}명`], ["성별", `남 ${men} · 여 ${rows.length - men}`], ["나이", `${Math.min(...ages)} ~ ${Math.max(...ages)}세`], ["2차 대상", `${rows.filter((r) => r.status === "stage2").length}명`]].map(([l, v]) => (
            <div key={l} className="card"><p className="text-sm text-slate-500">{l}</p><p className="text-xl font-bold">{v}</p></div>
          ))}
        </div>
      )}
      <div className="flex gap-4">
        <table className="card h-fit flex-1 text-sm">
          <thead className="text-left text-slate-500">
            <tr><th>이름</th><th>성별·나이</th><th>지원 상태</th><th>상세 단계</th><th>1차</th><th>결핍 가치</th><th>코딩 등급</th><th>면접</th><th>시험용 수준</th><th>이력서</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${open?.row.id === r.id ? "bg-brand-50" : ""}`} onClick={() => show(r)}>
                <td className="py-1.5">{r.name}</td>
                <td>{r.gender} · {r.age}</td>
                <td>{APP[r.status] ?? r.status}</td>
                <td className="text-xs">{STAGE[r.stage] ?? r.stage}</td>
                <td>{r.ai_conclusion ? `AI ${r.ai_conclusion}(참고)` : r.doc_status === "passed" ? "검토됨" : r.doc_status ?? "-"}</td>
                <td>{r.deficit_value ? VALUE[r.deficit_value] ?? r.deficit_value : "-"}</td>
                <td>{r.q3_tier ? `${r.q3_tier} (${BAND[r.q3_tier]})` : "-"}</td>
                <td>{r.interview_status ? SESSION[r.interview_status] : "-"}</td>
                <td>{r.test_level ?? "-"}</td>
                <td><Link className="text-brand-700 underline" href={`/admin/applicants/${r.id}`} onClick={(e) => e.stopPropagation()}>열기</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
        {open && <Resume row={open.row} d={open.d} onClose={() => setOpen(null)} />}
      </div>
    </div>
  );
}

function Resume({ row, d, onClose }: { row: Row; d: Detail; onClose: () => void }) {
  const r = d.application.resume_snapshot;
  const p = r["인적사항"] ?? {};
  return (
    <div className="card max-h-[calc(100vh-8rem)] w-[34rem] shrink-0 space-y-3 overflow-y-auto text-sm">
      <div className="flex items-center justify-between">
        <p className="text-lg font-bold">{row.name} 이력서</p>
        <span className="flex items-center gap-3">
          <Link className="btn-line px-3 py-1 text-sm" href={`/admin/applicants/${row.id}`}>이력서 전체 보기</Link>
          <button className="text-slate-500" onClick={onClose}>닫기</button>
        </span>
      </div>
      <div className="grid grid-cols-[5rem_1fr] gap-y-1">
        {["이름", "성별", "생년월일", "나이", "연락처", "이메일", "주소"].map((k) => (
          <Fragment2 key={k} k={k} v={String(p[k] ?? "-")} />
        ))}
        <Fragment2 k="지원 직무" v={r["지원직무"] ?? "-"} />
        <Fragment2 k="학력" v={r["학력"]} />
        <Fragment2 k="경력" v={r["경력"]} />
        <Fragment2 k="기술" v={(r["기술"] ?? []).join(", ")} />
      </div>
      <div><p className="font-semibold">소개</p>{(r["소개"] ?? [r["자기소개"]]).map((x: string) => <p key={x}>{x}</p>)}</div>
      {(r["보유기술"] ?? []).length > 0 && (
        <div>
          <p className="font-semibold">보유기술</p>
          {r["보유기술"].map((x: { 분야: string; 기술내역: string; 설명: string }) => (
            <p key={x.분야}>· <b>{x.분야}</b> <span className="rounded bg-slate-100 px-1 text-xs">{x.기술내역}</span> {x.설명}</p>
          ))}
        </div>
      )}
      <div>
        <p className="font-semibold">프로젝트 소개서</p>
        {(r["프로젝트소개서"] ?? []).map((x: Record<string, string>) => (
          <div key={x.이름} className="mt-1.5 rounded-md bg-slate-50 p-2">
            <p><b>{x.주제} / {x.이름}</b> <span className="text-xs text-slate-500">{x.기간} · {x.인원} · {x.담당역할}</span></p>
            <p className="text-xs text-slate-500">{x.개발환경}</p>
            <p className="mt-0.5 whitespace-pre-line">{x.작업과정성과}</p>
          </div>
        ))}
      </div>
      {(r["보유자격증"] ?? []).length > 0 && (
        <div>
          <p className="font-semibold">보유자격증</p>
          {r["보유자격증"].map((x: { 자격증명: string; 발급기관: string; 취득일: string }) => <p key={x.자격증명}>· {x.자격증명} <span className="text-slate-500">({x.발급기관}, {x.취득일})</span></p>)}
        </div>
      )}
      {[...(r["수상경력"] ?? []), ...(r["교육활동"] ?? [])].length > 0 && (
        <div>
          <p className="font-semibold">수상·교육·활동</p>
          {(r["수상경력"] ?? []).map((x: Record<string, string>) => <p key={x.수상명}>· {x.수상명} <span className="text-slate-500">({x.수상일})</span> {x.내용}</p>)}
          {(r["교육활동"] ?? []).map((x: Record<string, string>) => <p key={x.과정}>· {x.과정} <span className="text-slate-500">({x.기간})</span> {x.내용}</p>)}
        </div>
      )}
      {r["자기소개서"] && (
        <div className="space-y-2">
          <p className="font-semibold">자기소개서</p>
          {(r["자기소개서"] as { 문항: string; 질문: string; 답: string }[]).map((x, i) => (
            <div key={x.문항}>
              <p className="text-xs font-semibold text-slate-600" title={x.질문}>{i + 1}. {x.문항} <span className="font-normal text-slate-400">({x.답.length}자)</span></p>
              <p className="whitespace-pre-line">{x.답}</p>
            </div>
          ))}
        </div>
      )}
      {d.document && (
        <div className="rounded-md bg-slate-50 p-3">
          <p className="font-semibold">1차 결과 · {d.document.status === "passed" ? "통과" : d.document.status} (AI 결론 {String(d.document.criteria_scores?.["결론"] ?? "없음")} · 참고)</p>
          <p>결핍 가치 {VALUE[d.document.handoff?.deficit_value] ?? d.document.handoff?.deficit_value}: {d.document.handoff?.deficit_reason}</p>
        </div>
      )}
      {d.coding && (
        <div className="rounded-md bg-slate-50 p-3">
          <p className="font-semibold">코딩 결과 · {d.coding.q3_tier} ({BAND[d.coding.q3_tier]}) · 3번 환산 {d.coding.q3_converted}</p>
          <p>약점: {[...d.coding.weakness_summary.algorithms, ...d.coding.weakness_summary.weakness_tags].join(", ")}</p>
          <Link href={`/admin/coding/${d.coding.session_id}`} className="text-brand-700 underline">코딩 결과 자세히</Link>
        </div>
      )}
      <p className="text-xs text-slate-500">인적사항은 담당자 화면에만 보이고, AI 질문 생성·판정에는 가린 이력서만 들어갑니다.</p>
    </div>
  );
}

function Fragment2({ k, v }: { k: string; v: string }) {
  return (
    <>
      <span className="text-slate-500">{k}</span>
      <span>{v}</span>
    </>
  );
}
