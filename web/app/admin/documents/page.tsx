"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useState } from "react";
import { VALUE } from "@/lib/labels";
import { api, errorText } from "@/lib/api";

type Posting = { id: number; title: string };
type Sent = { channel: string; status: string; sent_at: string | null };
type Decision = "pass" | "reject" | "hold";
type Ai = {
  screened: boolean; conclusion?: "추천" | "비추천" | null; verify?: string;
  basis?: { req: string; label: string | null; quote: string | null }[]; awards_opinion?: string; work_fit?: string; overall?: string; model?: string;
  detail?: { labels: { req_id: string; req: string; label: string; quote: string }[]; retrieval: Record<string, { chunk_id: string; rrf: number; bm25: number | null; vector: number | null }[]> };
};
type Row = {
  id: number; seq: number; status: string; name: string; email: string; deficit_value: string | null; ai: Ai; decision: "pass" | "reject" | null;
  stage_label: string; decision_reason: string | null;
  deficit_evidence: { z: Record<string, number>; 후보: string[]; "원문 근거": Record<string, string | null>; "비교 지원자 수": number } | null;
  latest: Decision | null; decided_by: string | null; history: { decision: Decision; reason: string | null; by: string; at: string }[]; notified: Sent[];
};
type Board = {
  posting: { id: number; title: string; headcount: number; apply_end: string; doc_announce_at: string; stage2_start: string; stage2_end: string };
  announcement: { published_at: string; published_by: string | null } | null;
  rows: Row[];
  criteria: { id: string; text: string }[];
};

const AI: Record<string, string> = { 추천: "bg-emerald-100 text-emerald-800", 비추천: "bg-slate-100 text-slate-600" };
const WORD: Record<Decision, string> = { pass: "합격", reject: "불합격", hold: "선택 해제" };
const md = (s: string) => new Date(s).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });   // 일정 카드용 짧은 날짜

// 1차 서류 결정 (활동다이어그램 1109 2쪽): 점수 없이 AI 결론(추천·비추천·빈칸 = 참고)과 근거(요건 + 이력서 원문)를 보고
// 담당관이 합격할 사람을 체크하고 '결정 확인'을 한 번 누르면 확정·발표(= 응시 안내 발송). 결정은 쌓기만 하고 최근 결정이 유효
export default function Documents() {
  const router = useRouter();
  const [postings, setPostings] = useState<Posting[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [b, setB] = useState<Board | null>(null);
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<number | null>(null);   // '상세'를 연 지원 건
  const [crit, setCrit] = useState<string | null>(null); // 평가 기준 편집 중인 글 (한 줄에 하나)
  const [sel, setSel] = useState<Set<number>>(new Set()); // 체크한 합격자 (화면에만, '결정 확인'을 눌러야 저장·발표)

  useEffect(() => {
    api<Posting[]>("/admin/postings").then(async (ps) => {
      setPostings(ps);
      for (const p of ps) {                       // 처음에는 아직 발표하지 않은 서류 심사 중 공고를 연다
        const x = await api<Board>(`/admin/postings/${p.id}/document`);
        if (!x.announcement && x.rows.some((r) => r.status === "submitted")) return setPid(p.id);
      }
      setPid(ps[0]?.id ?? null);
    }, (e) => setMsg(errorText(e, router.push, true)));
  }, [router]);
  const load = useCallback(() => {
    if (pid) api<Board>(`/admin/postings/${pid}/document`).then((x) => {
      setB(x);
      setSel(new Set(x.rows.filter((r) => r.status === "submitted" && r.decision === "pass").map((r) => r.id)));
    }, (e) => setMsg(e.message));
  }, [pid]);
  useEffect(load, [load]);

  async function screen() {
    try {
      const r = await api<{ queued: number }>(`/admin/postings/${pid}/document/screen`, { method: "POST" });
      setMsg(`AI 1차 검토를 ${r.queued}명에게 실행했습니다. 끝난 지원자부터 결론이 보입니다.`);
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  const can = (r: Row) => r.status === "submitted" && r.ai.screened && r.ai.conclusion !== "비추천";   // 합격은 추천(또는 AI 정리 실패 빈칸) 안에서만 (11/12)   // 체크할 수 있는 지원자
  function toggle(id: number) {
    setSel((x) => { const y = new Set(x); if (y.has(id)) y.delete(id); else y.add(id); return y; });
  }

  async function revoke(r: Row) {                    // 발표 뒤 합격 취소: 부정행위를 발견한 경우만, 사유 필수
    const reason = prompt(`${r.name}의 1차 합격을 취소합니다. 부정행위(지원서와 지원자가 다름 등)를 발견한 경우에만 하세요.\n사유를 5자 이상 적어 주세요 (결정자·시각과 함께 기록됩니다).`);
    if (reason === null) return;
    try {
      await api(`/admin/applications/${r.id}/document/revoke`, { method: "POST", json: { reason } });
      setMsg(`${r.name}의 1차 합격을 취소했습니다.`);
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  async function saveCriteria() {
    try {
      await api(`/admin/postings/${pid}/document/criteria`, { method: "PUT", json: { items: (crit ?? "").split("\n") } });
      setCrit(null);
      setMsg("평가 기준을 저장했습니다.");
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  async function announce() {
    if (!b) return;
    const pass = picked;
    if (!confirm(`체크한 결정으로 1차 결과를 확정하고 합격자에게 응시 안내를 보낼까요?\n고른 ${pass}명 합격 · 나머지 ${pending.length - pass}명 불합격\n확정하면 지원자에게 메일·문자·홈페이지 알림이 가고, 합격 취소는 부정행위를 발견한 경우만 사유를 적어 할 수 있습니다.`)) return;
    try {
      const r = await api<{ announced: number; passed: number; notifications: number }>(`/admin/postings/${pid}/document/announce`, { method: "POST", json: { pass_ids: [...sel] } });
      setMsg(`발표했습니다. ${r.announced}명에게 알림 ${r.notifications}건을 보냈습니다 (메일·문자는 가짜 발송 기록).`);
      load();
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  const rows = b?.rows ?? [];
  const pending = rows.filter((r) => r.status === "submitted");
  const picked = pending.filter((r) => sel.has(r.id)).length;
  const eligible = pending.filter(can);
  const all = eligible.length > 0 && eligible.every((r) => sel.has(r.id));
  const unscreened = pending.filter((r) => !r.ai.screened).length;
  const done = !!b?.announcement;
  const nAi = (v: string) => rows.filter((r) => r.ai.conclusion === v).length;

  const confirmBtn = (
    <button className="btn" disabled={!picked} onClick={announce} title={picked ? undefined : "합격으로 체크한 지원자가 없습니다"}>
      결정 확인 (합격 {picked}명 · 불합격 {pending.length - picked}명)
    </button>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold">1차 서류 결정</h1>
        <select className="input w-auto" value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))}>
          {postings.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
        <span className="ml-auto flex gap-2">
          {!done && unscreened > 0 && <button className="btn-line" onClick={screen}>AI 1차 검토 실행 ({unscreened}명)</button>}
          {done ? (
            <span className="rounded bg-emerald-50 px-3 py-1.5 text-sm text-emerald-800">
              발표 완료 · {new Date(b!.announcement!.published_at).toLocaleString("ko-KR")}{b!.announcement!.published_by && ` · ${b!.announcement!.published_by}`}
            </span>
          ) : confirmBtn}
        </span>
      </div>
      {msg && <p className="text-sm">{msg}</p>}
      {b && (
        <div className="grid grid-cols-4 gap-4">
          {([["지원자", `${rows.length}명 · 모집 ${b.posting.headcount}명`],
             ["AI 추천(참고, 지원자의 30%) 추천·비추천·빈칸", `${nAi("추천")} · ${nAi("비추천")} · ${rows.filter((r) => !r.ai.conclusion).length}`],
             ["합격으로 고름 · 나머지(불합격)", done ? `${rows.filter((r) => r.decision === "pass").length} · ${rows.filter((r) => r.decision === "reject").length}` : `${picked} · ${pending.length - picked}`]] as [string, string][]).map(([l, v]) => (
            <div key={l} className="card"><p className="text-sm text-slate-500">{l}</p><p className="text-lg font-bold">{v}</p></div>
          ))}
          <div className="card text-sm">   {/* 일정은 날짜가 길어 한 줄에 하나씩 (11/17) */}
            <p className="text-slate-500">일정</p>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <dt className="text-slate-500">1차 발표</dt><dd className="font-semibold">{md(b.posting.doc_announce_at)}</dd>
              <dt className="text-slate-500">2차</dt><dd className="whitespace-nowrap font-semibold">{md(b.posting.stage2_start)} ~ {md(b.posting.stage2_end)}</dd>
            </dl>
          </div>
        </div>
      )}
      <p className="text-xs text-slate-500">
        1차 점수는 없습니다. AI 결론(추천·비추천·빈칸)은 참고용이고, 결정은 담당관이 합니다. AI 추천 순으로 보이며, 합격할 사람만 체크한 뒤
        목록 위·아래의 &apos;결정 확인&apos;을 한 번 누르면 체크한 사람은 합격, 나머지는 모두 불합격으로 확정·발표됩니다. 고르기 기록은 쌓이고, 발표 뒤 합격 취소는 부정행위를 발견한 경우만 사유를 적어 할 수 있습니다.
        검색 수치는 &apos;상세&apos;에서만 보입니다. 발표 전까지 지원자에게는 아무것도 보이지 않습니다.
      </p>
      {b && (
        <div className="card space-y-2 text-sm" data-testid="criteria">
          <div className="flex items-center gap-2">
            <p className="font-semibold">1차 평가 기준 (모두 우대 · 없어도 지원 가능)</p>
            <span className="flex-1" />
            {crit === null
              ? <button className="btn-line text-xs" disabled={done || rows.some((r) => r.ai.screened)} onClick={() => setCrit(b.criteria.map((c) => c.text).join("\n"))}
                  title={rows.some((r) => r.ai.screened) ? "AI 1차 검토를 실행한 뒤에는 바꿀 수 없습니다" : undefined}>편집</button>
              : <><button className="btn text-xs" onClick={saveCriteria}>저장</button><button className="btn-line text-xs" onClick={() => setCrit(null)}>취소</button></>}
          </div>
          {crit === null
            ? <p className="text-slate-600">{b.criteria.map((c) => c.text).join(" · ")}</p>
            : <textarea className="input h-32 w-full text-sm" name="criteria" value={crit} onChange={(e) => setCrit(e.target.value)} placeholder="한 줄에 기술·경험 하나" />}
          <p className="text-xs text-slate-500">AI는 이 항목과 이력서의 실제 경험을 보고 항목마다 충족·부분·부족·근거 없음을 붙여 추천합니다.</p>
        </div>
      )}
      <table className="card w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr><th className="w-8 py-2">
            {!done && <input type="checkbox" aria-label="전체 선택" checked={all} disabled={!eligible.length}
              onChange={() => setSel(all ? new Set() : new Set(eligible.map((r) => r.id)))} />}
          </th><th className="py-2">지원 번호</th><th>이름</th><th>AI 결론(참고)</th><th>근거 (항목 · 이력서 원문)</th><th>의견</th><th>결정</th><th>단계·알림</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr className="border-t border-slate-100 align-top" data-testid={`doc-row-${r.id}`}>
                <td className="py-2">
                  {!done && <input type="checkbox" aria-label={`${r.name} 합격`} checked={sel.has(r.id)} disabled={!can(r)} onChange={() => toggle(r.id)}
                    title={can(r) ? undefined : r.ai.screened ? "AI 비추천 지원자는 합격으로 고를 수 없습니다" : "AI 1차 검토 전"} />}
                </td>
                <td className="py-2 font-bold">{r.seq}</td>
                <td><Link className="text-brand-700 underline" href={`/admin/applicants/${r.id}`}>{r.name}</Link></td>
                <td>
                  {!r.ai.screened ? <span className="text-xs text-slate-400">검토 전</span>
                    : r.ai.conclusion ? <span className={`rounded px-2 py-0.5 text-xs ${AI[r.ai.conclusion]}`}>{r.ai.conclusion}</span>
                    : <span className="text-xs text-slate-400">빈칸</span>}
                  {r.ai.screened && r.ai.verify !== "통과" && <span className="mt-1 block max-w-[10rem] text-xs text-amber-700">{r.ai.verify}</span>}
                </td>
                <td className="max-w-sm text-xs text-slate-600">
                  {(r.ai.basis ?? []).map((x, i) => <p key={i}><b>{x.req}</b> · {x.label} · &ldquo;{x.quote}&rdquo;</p>)}
                </td>
                <td className="max-w-xs text-xs text-slate-600">
                  {r.ai.overall && <p>{r.ai.overall}</p>}
                  {r.ai.awards_opinion && <p className="text-slate-500">수상·자격: {r.ai.awards_opinion}</p>}
                  {r.ai.work_fit && <p className="text-slate-500">업무 가능성: {r.ai.work_fit}</p>}
                  {r.ai.screened && <button className="text-brand-700 underline" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "상세 닫기" : "상세"}</button>}
                </td>
                <td>
                  {!done ? (
                    <span className={`text-xs ${sel.has(r.id) ? "font-semibold text-emerald-700" : "text-slate-400"}`}>{sel.has(r.id) ? "합격" : "불합격 예정"}</span>
                  ) : r.decision === "pass" && r.status !== "doc_failed" ? (
                    <span className="flex items-center gap-1">
                      <span className="rounded bg-emerald-600 px-2 py-0.5 text-xs text-white">합격</span>
                      <button className="text-xs text-red-700 underline" onClick={() => revoke(r)}>합격 취소</button>
                    </span>
                  ) : (
                    <span className="rounded bg-slate-500 px-2 py-0.5 text-xs text-white" title={r.decision_reason ?? undefined}>불합격</span>
                  )}
                  {r.history.length > 0 && (
                    <span className="mt-0.5 block text-xs text-slate-500" title={r.history.map((h) => `${new Date(h.at).toLocaleString("ko-KR")} ${h.by} ${WORD[h.decision]}${h.reason ? ` (${h.reason})` : ""}`).join("\n")}>
                      {r.history.at(-1)!.by} {WORD[r.history.at(-1)!.decision]} · 기록 {r.history.length}건
                    </span>
                  )}
                </td>
                <td className="text-xs text-slate-500">
                  <span className="block text-slate-700">{r.stage_label}</span>
                  {r.notified.length ? r.notified.map((n) => `${n.channel === "email" ? "메일" : "문자"} ${n.status === "sent" ? "발송" : "실패"}`).join(" · ") : "-"}
                </td>
              </tr>
              {open === r.id && r.ai.detail && (
                <tr className="bg-slate-50 text-xs">
                  <td colSpan={2} />
                  <td colSpan={6} className="py-2">
                    <p className="font-semibold">요건별 라벨</p>
                    {r.ai.detail.labels.map((x) => <p key={x.req_id}>{x.req_id} {x.req} · <b>{x.label}</b>{x.quote && ` · “${x.quote}”`}</p>)}
                    <p className="mt-1 font-semibold">비교 검색 (RRF · BM25 순위 · 벡터 순위)</p>
                    {Object.entries(r.ai.detail.retrieval).map(([k, v]) => (
                      <p key={k}>{k}: {v.map((d) => `${d.chunk_id} (${d.rrf} · ${d.bm25 ?? "-"} · ${d.vector ?? "-"})`).join(", ") || "-"}</p>
                    ))}
                    <p className="mt-1 text-slate-500">모델 {r.ai.model}</p>
                    <p className="mt-1 font-semibold">결핍 가치 {r.deficit_value ? `${VALUE[r.deficit_value] ?? r.deficit_value} (${r.deficit_value})` : "- (합격으로 고르면 계산)"}</p>
                    {r.deficit_evidence && (
                      <p>지원자 {r.deficit_evidence["비교 지원자 수"]}명 비교 z: {Object.entries(r.deficit_evidence.z).map(([k, v]) => `${VALUE[k]} ${v}`).join(" · ")}
                        {" "}/ 원문 근거: {r.deficit_evidence["후보"].map((k) => `${VALUE[k]} ${r.deficit_evidence!["원문 근거"][k] ? `“${r.deficit_evidence!["원문 근거"][k]}”` : "없음"}`).join(" · ")}</p>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {!done && rows.length > 0 && <div className="flex justify-end">{confirmBtn}</div>}
    </div>
  );
}
