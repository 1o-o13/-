"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { VALUE } from "@/lib/labels";

type Essay = { 문항: string; 질문: string; 답: string };
type Row = Record<string, string>;
type Resume = {
  인적사항?: Record<string, string | number | null>; 지원직무?: string; 소개?: string[]; 학력?: string; 경력?: string; 기술?: string[];
  학력사항?: Row[]; 수상경력?: Row[]; 경력사항?: Row[]; 보유자격증?: Row[]; 교육활동?: Row[]; 경력직무상세?: Row[]; 보유기술?: Row[]; 프로젝트소개서?: Row[];
  자기소개서?: Essay[];
  "시험용 수준"?: string;
};
type Detail = {
  application: { id: number; status: string; resume_snapshot: Resume; submitted_at: string; posting: string; interview_session_id: number | null };
  document: { criteria_scores: { 결론?: string | null } | null; rationale: string; handoff: Record<string, string>; status: string } | null;
  coding: { session_id: number; q3_tier: string; q3_converted: string; weakness_summary: { algorithms: string[]; weakness_tags: string[] } } | null;
};

const APP: Record<string, string> = { submitted: "서류 심사", doc_passed: "서류 합격", doc_failed: "서류 불합격", stage2: "2차 대상", stage2_done: "2차 완료", final_passed: "최종 합격", reserve: "예비", final_failed: "최종 불합격", withdrawn: "취소", abandoned: "응시 포기" };
const PROJECT: [string, string][] = [["주제", "프로젝트주제 / 명"], ["주소", "프로젝트주소"], ["기간", "수행기간 / 인원"], ["동기목표", "동기 / 목표"],
  ["개발환경", "개발환경"], ["담당역할", "담당역할"], ["작업과정성과", "작업과정 및 성과"], ["느낀점", "느낀점 / 성장점"]];
const show = (v: unknown) => (v == null || v === "" ? "-" : String(v));

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 border-b border-slate-200 pb-1.5 text-base font-bold text-brand-900">{children}</h2>;
}

/** 팀 이력서 양식의 표 항목 (없으면 '기재사항 없음') */
function Table({ title, rows, cols }: { title: string; rows?: Row[]; cols: [string, string][] }) {
  return (
    <section>
      <H>{title}</H>
      {(rows ?? []).length ? (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500"><tr>{cols.map(([k, l]) => <th key={k} className="pb-1 pr-3">{l}</th>)}</tr></thead>
          <tbody>
            {rows!.map((x, i) => (
              <tr key={i} className="border-t border-slate-100 align-top">
                {cols.map(([k], j) => <td key={k} className={`py-1.5 pr-3 ${j === 1 ? "font-medium" : ""}`}>{x[k] || "-"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="text-sm text-slate-500">기재사항 없음</p>}
    </section>
  );
}

// 지원서(이력서) 전체 보기: 담당자가 실제 문서처럼 읽는 화면. 인적사항은 담당자에게만 보인다 (AI 평가에는 가린 내용만, P-02)
export default function ResumeView() {
  const appId = useParams<{ appId: string }>().appId;
  const router = useRouter();
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Detail>(`/admin/applications/${appId}`).then(setD, (e) => setErr(errorText(e, router.push, true)));
  }, [appId, router]);

  if (err) return <p className="err">{err}</p>;
  if (!d) return <p>불러오는 중…</p>;
  const a = d.application;
  const r = a.resume_snapshot;
  const p = r.인적사항 ?? {};
  return (
    <div className="mx-auto max-w-4xl space-y-4 print:max-w-none">
      <div className="flex items-center gap-3 print:hidden">
        <Link href="/admin/applicants" className="text-sm text-slate-500">← 지원자 현황</Link>
        <span className="ml-auto flex gap-2">
          {d.coding && <Link className="btn-line" href={`/admin/coding/${d.coding.session_id}`}>코딩 결과</Link>}
          {a.interview_session_id && <Link className="btn-line" href={`/admin/interviews/${a.interview_session_id}`}>면접 결과</Link>}
          <button className="btn" onClick={() => window.print()}>인쇄·PDF 저장</button>
        </span>
      </div>

      <article className="card space-y-7 p-8 print:border-0 print:shadow-none">
        <header className="flex items-end justify-between border-b-2 border-brand-900 pb-3">
          <div>
            <p className="text-sm text-slate-500">{a.posting} · 이력서</p>
            <h1 className="text-2xl font-bold">{String(p["이름"] ?? "-")} <span className="text-base font-medium text-brand-700">{r.지원직무}</span></h1>
            {(r.소개 ?? []).map((x) => <p key={x} className="text-slate-600">{x}</p>)}
          </div>
          <div className="text-right text-sm text-slate-500">
            <p>지원 상태 <b className="text-slate-800">{APP[a.status] ?? a.status}</b></p>
            <p>제출 {new Date(a.submitted_at).toLocaleString("ko-KR")}</p>
          </div>
        </header>

        <section>
          <H>인적사항 <span className="ml-1 text-xs font-normal text-slate-500">담당자에게만 보임 · AI 평가에는 가려서 넣음</span></H>
          <dl className="grid grid-cols-[7rem_1fr_7rem_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-slate-500">성명 / 성별</dt><dd>{show(p["이름"])} / {show(p["성별"])}</dd>
            <dt className="text-slate-500">생년월일</dt><dd>{show(p["생년월일"])}{p["나이"] != null && ` (만 ${p["나이"]}세)`}</dd>
            <dt className="text-slate-500">휴대전화 / E-mail</dt><dd>{show(p["연락처"])} / {show(p["이메일"])}</dd>
            <dt className="text-slate-500">Github</dt><dd>{p["Github"] ? String(p["Github"]) : "등록 계정 없음"}</dd>
            <dt className="text-slate-500">주소</dt><dd className="col-span-3">{show(p["주소"])}</dd>
          </dl>
        </section>

        <Table title="학력사항" rows={r.학력사항} cols={[["기간", "기간"], ["학교", "학교"], ["학과", "학과"], ["학점", "학점"], ["상태", "졸업 여부"]]} />
        <Table title="수상경력" rows={r.수상경력} cols={[["수상일", "수상일"], ["수상명", "수상명"], ["수여기관", "수여기관"], ["내용", "수상 내용"]]} />
        <Table title="경력사항" rows={r.경력사항} cols={[["기간", "기간"], ["회사", "회사"], ["직무", "직무"], ["총기간", "총 기간"], ["요약", "요약"]]} />
        <Table title="보유자격증" rows={r.보유자격증} cols={[["취득일", "취득일"], ["자격증명", "자격증명"], ["발급기관", "발급기관"]]} />
        <Table title="교육사항 & 활동사항" rows={r.교육활동} cols={[["기간", "기간"], ["기관", "기관"], ["과정", "교육과정"], ["내용", "내용"]]} />

        <section>
          <H>경력직무 상세</H>
          {(r.경력직무상세 ?? []).length ? (r.경력직무상세 ?? []).map((x) => (
            <div key={x.회사} className="mb-2 text-sm">
              <p><b>{x.회사}</b> <span className="text-slate-500">{x.기간}</span></p>
              <p className="mt-1 leading-relaxed">{x.수행직무}</p>
            </div>
          )) : <p className="text-sm text-slate-500">기재사항 없음</p>}
        </section>

        <Table title="보유기술" rows={r.보유기술} cols={[["분야", "분야"], ["기술내역", "기술내역"], ["설명", "설명"]]} />

        <section>
          <H>프로젝트 소개서</H>
          {(r.프로젝트소개서 ?? []).map((x) => (
            <dl key={x.이름} className="mb-3 grid grid-cols-[8rem_1fr] gap-y-1.5 rounded-md border border-slate-200 p-3 text-sm">
              {PROJECT.map(([k, label]) => (
                <div key={k} className="contents">
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="whitespace-pre-line leading-relaxed">{k === "주제" ? `${x.주제} / ${x.이름}` : k === "기간" ? `${x.기간} / ${x.인원}` : show(x[k])}</dd>
                </div>
              ))}
            </dl>
          ))}
          {!(r.프로젝트소개서 ?? []).length && <p className="text-sm text-slate-500">기재사항 없음</p>}
        </section>

        <section>
          <H>자기소개서</H>
          <div className="space-y-5">
            {(r.자기소개서 ?? []).map((x, i) => (
              <div key={x.문항} className="break-inside-avoid">
                <p className="text-sm font-semibold">{i + 1}. {x.문항} <span className="font-normal text-slate-500">— {x.질문}</span></p>
                <p className="mt-1.5 whitespace-pre-line rounded-md bg-slate-50 p-3 text-sm leading-7">{x.답}</p>
                <p className="mt-0.5 text-right text-xs text-slate-400">{x.답.length}자 (공백 포함)</p>
              </div>
            ))}
            {!(r.자기소개서 ?? []).length && <p className="text-sm text-slate-500">자기소개서 없음</p>}
          </div>
        </section>
      </article>

      {(d.document || d.coding) && (
        <aside className="card space-y-2 text-sm print:hidden">
          <p className="font-semibold">전형 결과 (담당자 참고)</p>
          {d.document && (
            <p>1차 서류 · {d.document.status === "passed" ? "통과" : d.document.status} (AI 결론 {d.document.criteria_scores?.결론 ?? "없음"} · 참고) · 부족한 가치 {VALUE[d.document.handoff?.deficit_value] ?? d.document.handoff?.deficit_value}: {d.document.handoff?.deficit_reason}</p>
          )}
          {d.coding && (
            <p>코딩 · {d.coding.q3_tier} · 환산 {Number(d.coding.q3_converted)}점 · 약점 {[...d.coding.weakness_summary.algorithms, ...d.coding.weakness_summary.weakness_tags].join(", ")}</p>
          )}
        </aside>
      )}
    </div>
  );
}
