"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useState } from "react";
import { useDevTools } from "@/lib/quick";
import { api, errorText } from "@/lib/api";
import { EVAL, SESSION, topicName } from "@/lib/labels";

type Signal = { source: "face" | "voice"; t0: number; t1: number; label: string; value: Record<string, string | number | null> };
type Source = { chunk_id: string; doc_title: string; sec_title: string; tier: number };
type Question = {
  id: number; ask_order: number; kind: string; question_type: string; depth: number; tech_stack: string | null; question_text: string;
  basis: string; sources: Source[]; key_points: string[]; stt_text: string | null; answer_sec: string; no_response: boolean;
  stt_original: string | null; stt_edit_ratio: string | null; answer_mode?: "voice" | "text"; // 글로 답하기 (11/12) // 지원자 확인·수정 (11/11): 인식 원본과 바뀐 비율
  judge_status: string | null; score: string | null; rubric: Record<string, number> | null; opinion: Record<string, unknown> | null;
  quotes: string[] | null; rationale: string | null; model_tier: string | null; judge_model: string | null; signals: Signal[] | null;
  defense: {
    nli?: { verdict: string; by: string; entailment: number | null; contradiction: number | null; reason?: string }; fixed?: boolean; low_confidence?: boolean;
    comment?: string; 경로?: string[]; 검색?: { query: string; rrf: number | number[]; bm25?: number | null; vector?: number | null; "주제 재사용"?: boolean };
    "재질문 유형"?: string;
  } | null;
};
type Mark = { topic: string; orders: number[]; depth: number; mark: string | null };
type Check = { check_no: number; passed: boolean; detail: string; checker: string };
type Evaluation = {
  id: number; version_no: number; status: string; total_score: string; content_score: string; language_score: string; nonverbal_score: string;
  topic_scores: Record<string, number>; confirmed_at: string | null; checks: Check[];
  project_topic: string | null; fit_opinion: string | null; growth_opinion: string | null;
};
type Detail = {
  session: Record<string, any>; questions: Question[]; evaluations: Evaluation[]; topic_marks: Mark[];
  llm_calls: { purpose: string; prompt_version: string; provider: string; model: string; min_tier: number | null; input_tokens: number; output_tokens: number;
    latency_ms: number; ok: boolean; route_note: string | null; created_at: string }[];
  identity_checks: { id: number; phase: string; distance: string | null; band: string }[];
  proctor_events: { id: number; event_type: string; duration_ms: number; action: string; occurrence_no: number }[];
  suspicions: { id: number; reason: string; status: string; decision: string | null; decision_reason: string | null }[];
  notes: { id: number; body: string; created_at: string }[];
};

const TYPE: Record<string, string> = { main: "본 질문", followup: "꼬리", reask: "재질문" };
const CHECKS = ["형식", "인용", "체크리스트", "금지 요소", "근거–점수"];
const BAND: Record<string, string> = { match: "일치", unclear: "애매", mismatch: "불일치", no_face: "얼굴 없음" };
const EVENT: Record<string, string> = { tab_leave: "탭 이탈", window_blur: "창 이탈", face_missing: "얼굴 없음", multi_face: "여러 명", gaze_away: "시선 이탈", network_drop: "연결 끊김", reconnect: "재연결", upload_fail: "업로드 실패", identity_unclear: "본인 확인 애매", identity_mismatch: "본인 확인 불일치" };
const ACTION: Record<string, string> = { logged: "기록", warned: "경고", abandoned: "포기", suspected: "의심 건" };
const DECISION: Record<string, string> = { normal: "정상", warning: "경고", disqualified: "실격" };

/** 다음 결정: 다음 문항의 종류로 보여 준다 (진행 규칙은 서버 next_action) */
function nextOf(qs: Question[], i: number): string {
  const n = qs[i + 1];
  if (!n) return "종료";
  if (qs[i].kind === "non_tech") return "다음";
  return n.question_type === "followup" ? "꼬리" : n.question_type === "reask" ? "재질문" : "다음 주제";
}

// ADM-033 AI 면접 결과 검토
export default function InterviewDetail() {
  const sid = useParams<{ sid: string }>().sid;
  const router = useRouter();
  const dev = useDevTools();   // 개발용 버튼 (.env DEV_QUICK_LOGIN=1)
  const [d, setD] = useState<Detail | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const [role, setRole] = useState("");
  useEffect(() => {
    api<{ role: string }>("/auth/me?as=admin").then((m) => setRole(m.role), () => {});
  }, []);

  const load = useCallback(
    () => api<Detail>(`/admin/interviews/${sid}`).then(setD, (e) => setMsg(errorText(e, router.push, true))),
    [sid, router],
  );
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {                                  // 면접이 진행되는 동안은 5초마다 새로 (답변이 들어올 때마다 판정·표기가 바로 보임)
    if (d?.session.status !== "in_progress") return;
    const t = window.setInterval(load, 5000);
    return () => clearInterval(t);
  }, [d?.session.status, load]);

  /** 처리하고 성공하면 true (실패면 안내 문구만 남기고 false) */
  async function act(path: string, json?: unknown, done = "처리했습니다."): Promise<boolean> {
    try {
      await api(`/admin${path}`, { method: "POST", json });
      setMsg(done);
      load();
      return true;
    } catch (e) {
      setMsg(errorText(e, router.push, true));
      return false;
    }
  }

  if (!d) return <p className={msg ? "err" : ""}>{msg || "불러오는 중…"}</p>;
  const s = d.session;
  const ev = d.evaluations.at(-1);
  const markAt = new Map(d.topic_marks.filter((m) => m.mark).map((m) => [m.orders.at(-1), m.mark])); // 주제 마지막 문항에 표시
  const passed = [...d.evaluations].reverse().find((e) => e.status === "passed");
  const allFailed = d.evaluations.length === 2 && d.evaluations.every((e) => e.status === "failed");
  const openCases = d.suspicions.filter((c) => c.status !== "decided").length;
  const identity = d.identity_checks.at(-1);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">
          {s.candidate_name} <span className="font-normal text-slate-500">· {s.posting_title} · {s.attempt_no}차 응시</span>
          <span className="ml-2 align-middle text-xs font-medium">
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">{SESSION[s.status]}</span>
            {ev && <span className={`ml-1 rounded-full px-2.5 py-1 ${ev.status === "passed" ? "bg-emerald-50 text-emerald-700" : ev.status === "failed" ? "bg-red-50 text-red-600" : "bg-amber-50 text-amber-700"}`}>
              AI {EVAL[ev.status]}{ev.version_no > 1 && ` (재평가)`}</span>}
            {openCases > 0 && <span className="ml-1 rounded-full bg-red-50 px-2.5 py-1 text-red-600">의심 {openCases}건</span>}
          </span>
        </h1>
        <div className="flex gap-2">
          {/* 최고관리자·채용 담당 모두 끝난 응시(완료·포기)와 장애로 멈춘 응시에 재응시를 줄 수 있다 (최대 3차) */}
          <button
            className="btn-line"
            disabled={s.attempt_no >= 3 || !["system_error", "paused", "completed", "abandoned"].includes(s.status)}
            onClick={() => act(`/interviews/${sid}/reattempt`, undefined, `재응시를 부여했습니다. 지원자가 다시 들어오면 ${s.attempt_no + 1}차 응시가 새 질문으로 시작됩니다.`)}
          >
            재응시 부여 {s.attempt_no >= 3 ? "(3차까지 사용)" : `(${s.attempt_no + 1}차)`}
          </button>
          {role === "super_admin" && dev && (
            <button
              className="btn-line text-red-600"
              onClick={() => confirm("시험용: 이 지원자의 면접 기록(질문·답변·평가·확정 점수)을 모두 지우고 1차 응시부터 다시 하게 할까요?") && act(`/interviews/${sid}/reset`, undefined, "응시 기록을 초기화했습니다. 지원자가 1차 응시부터 다시 할 수 있습니다.").then((ok) => ok && router.push("/admin/interviews"))}
            >
              응시 기록 초기화 (시험용)
            </button>
          )}
          <button className="btn" disabled={!passed || !!passed.confirmed_at} onClick={() => act(`/interviews/${sid}/confirm`, undefined, "평가를 확정했습니다. 2차 종합 점수에 반영됩니다.")}>
            {passed?.confirmed_at ? "확정됨" : "평가 확정"}
          </button>
        </div>
      </div>
      {msg && <p className="text-sm">{msg}</p>}
      {allFailed && <p className="err">검증 실패 → 재평가도 실패했습니다. 오류 알림이 등록되어 확정할 수 없습니다.</p>}

      <div className="grid grid-cols-[1fr_2fr] gap-4 max-lg:grid-cols-1">
        <div className="card space-y-3">
          <div>
            <p className="text-sm text-slate-500">면접 점수</p>
            <p className="text-4xl font-bold text-brand-700">{ev?.total_score ?? "-"}</p>
          </div>
          {ev && (
            <div className="grid grid-cols-3 gap-2 text-center text-sm">
              {([["내용", ev.content_score, 60], ["언어", ev.language_score, 30], ["비언어", ev.nonverbal_score, 10]] as const).map(([l, v, max]) => (
                <div key={l} className="rounded-xl bg-slate-50 py-2">
                  <p className="text-xs text-slate-500">{l} <span className="text-slate-400">/ {max}</span></p>
                  <p className="font-semibold">{v}</p>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card text-sm">
          <p className="mb-2 font-semibold">주제 점수 <span className="font-normal text-slate-400">· 물어본 주제별 (꼬리질문까지 가면 높아짐)</span></p>
          {ev ? (
            <ul className="space-y-1.5">
              {d.topic_marks.map((m, i) => {   // 물어본 순서대로. 같은 주제를 또 물으면 점수 키가 'CHT 2'
                const key = `${m.topic} ${d.topic_marks.slice(0, i + 1).filter((t) => t.topic === m.topic).length}`;
                const v = ev.topic_scores[key];
                return (
                  <li key={key} className="grid grid-cols-[4.5rem_13rem_1fr_3rem] items-center gap-3">
                    <span className="text-xs text-slate-500">{m.orders.join("·")}번</span>
                    <span className="truncate" title={key}>
                      {topicName(key)}
                      {m.mark && <b className="ml-1 text-xs font-medium text-amber-700">{m.mark}</b>}
                    </span>
                    <span className="h-2 overflow-hidden rounded-full bg-slate-100" title={`꼬리질문 깊이 ${m.depth}`}>
                      <span className="block h-full rounded-full bg-brand-600" style={{ width: `${Math.min(100, Number(v ?? 0))}%` }} />
                    </span>
                    <span className="text-right font-semibold tabular-nums">{v == null ? "-" : Number(v).toFixed(1)}</span>
                  </li>
                );
              })}
            </ul>
          ) : <p>-</p>}
          <p className="text-xs text-slate-400">모름 = 재질문 뒤 70점 미만 · 깊이 미측정 = 10문항이 끝나 꼬리질문을 못 함</p>
        </div>
        <div className="card space-y-1 text-sm">
          <p className="font-semibold">프로젝트 적합성 · 확장성 <span className="font-normal text-slate-400">(의견, 점수 아님)</span></p>
          <p className="text-slate-500">기준 프로젝트 {ev?.project_topic ? topicName(ev.project_topic) : "-"}</p>
          <p><b className="font-medium">적합성</b> {ev?.fit_opinion ?? "-"}</p>
          <p><b className="font-medium">확장성</b> {ev?.growth_opinion ?? "-"}</p>
        </div>
        <div className="card space-y-1 text-sm">
          <p className="font-semibold">코딩 약점 요약 · 등급</p>
          <p className="flex flex-wrap gap-1">
            {s.coding_weakness ? [...s.coding_weakness.algorithms, ...s.coding_weakness.weakness_tags].map((w: string) => <span key={w} className="badge">{w}</span>) : "-"}
          </p>
          <p>{s.q3_tier ?? "-"} <span className="text-slate-500">(질문 난이도 {s.ct_band ?? "-"})</span></p>
          {s.coding_session_id && <Link href={`/admin/coding/${s.coding_session_id}`} className="text-brand-700 underline">코딩 결과 자세히</Link>}
        </div>
      </div>

      <table className="card w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr><th>번호</th><th>질문 · 지원자 답변(STT)</th><th>종류</th><th>근거 문서</th><th>점수 · 판정 근거</th><th>다음</th></tr>
        </thead>
        <tbody>
          {d.questions.map((q, i) => (
            <Fragment key={q.id}>
              <tr className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(open === q.id ? null : q.id)}>
                <td>{q.ask_order}</td>
                <td className="max-w-xl py-2">
                  <p>{q.question_text}</p>
                  <p className={`mt-1 rounded px-2 py-1 text-xs ${q.stt_text ? "bg-slate-50 text-slate-800" : "bg-amber-50 text-amber-800"}`} data-testid="stt">
                    <b>답변</b>{q.answer_mode === "text" && <span className="ml-1 rounded bg-sky-100 px-1 text-sky-800">글 답변 (응시 편의 승인)</span>} {q.stt_text ?? (q.no_response ? "(무응답 · 말소리가 거의 없어 음성을 버림)" : q.judge_status ? "(STT 결과 없음)" : "(답변 처리 중)")}
                  </p>
                  {q.stt_edit_ratio !== null && Number(q.stt_edit_ratio) > 0 && (
                    <p className="mt-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900" data-testid="stt-edited">
                      <b>지원자 수정 {Math.round(Number(q.stt_edit_ratio) * 100)}%</b> · 인식 원본: {q.stt_original}
                    </p>
                  )}
                </td>
                <td>{q.kind === "non_tech" ? (q.ask_order === 1 ? "경험" : "가치") : `${TYPE[q.question_type]}${q.depth ? ` ${q.depth}` : ""}`}</td>
                <td>{q.kind === "non_tech" ? (q.ask_order === 1 ? "이력서" : "1차 인계") : q.sources.map((x) => `${x.chunk_id} · tier ${x.tier}`).join(", ")}</td>
                <td className="max-w-xs py-2">
                  <b>{q.kind === "non_tech" ? "의견" : q.score ?? "-"}</b>{q.judge_status && q.judge_status !== "ok" && ` (${q.judge_status})`}
                  {q.rationale && <p className="text-xs text-slate-600">{q.rationale}</p>}
                  {q.judge_model && <p className="text-xs text-slate-400">{q.judge_model}{q.model_tier === "fast" ? " · 대체 모델" : ""}</p>}
                </td>
                <td>{nextOf(d.questions, i)}{markAt.get(q.ask_order) && <b className="ml-1 text-amber-700">({markAt.get(q.ask_order)})</b>}</td>
              </tr>
              {open === q.id && (
                <tr>
                  <td colSpan={6} className="space-y-1 bg-slate-50 p-3">
                    <p><b>출제 근거</b> {q.basis}</p>
                    <p><b>STT</b> {q.stt_text ?? "(무응답)"}</p>
                    <SignalReport q={q} />
                    {q.rubric && Object.keys(q.rubric).length > 0 && (
                      <p><b>루브릭</b> 정확성 {q.rubric["정확성"]}/30 · 회사 적용 {q.rubric["회사 적용"]}/30 · 깊이 {q.rubric["깊이"]}/25 · 구체성 {q.rubric["구체성"]}/15</p>
                    )}
                    {q.opinion && <p><b>의견</b> {JSON.stringify(q.opinion)}</p>}
                    <p><b>인용</b> {q.quotes?.join(" / ") || "-"} · <b>체크리스트</b> {q.key_points.join(", ")}</p>
                    {q.rubric?.["관련성(CE)"] != null && <p><b>답변 관련성</b> {q.rubric["관련성(CE)"]} (0.4 미만이면 꼬리 대신 재질문, 점수에 안 더함)</p>}
                    {q.defense?.nli && (
                      <p><b>꼬리질문 모순 검사</b> {q.defense.nli.verdict === "pass" ? "통과" : "미달"} · 함의 {q.defense.nli.entailment} · 모순 {q.defense.nli.contradiction} ({q.defense.nli.by})
                        {q.defense.fixed && " · 1번 고침"}{q.defense.low_confidence && <b className="text-red-600"> · {q.defense.comment}</b>}</p>
                    )}
                    {q.defense?.["경로"] && <p><b>대체 경로</b> <span className="text-amber-700">{q.defense["경로"].join(" → ")}</span></p>}
                    {q.defense?.["검색"] && (
                      <p><b>근거 검색</b> 질의 {q.defense["검색"].query} · RRF {String(q.defense["검색"].rrf)}
                        {q.defense["검색"].bm25 !== undefined && ` · BM25 ${q.defense["검색"].bm25 ?? "-"}위 · 벡터 ${q.defense["검색"].vector ?? "-"}위`}
                        {q.defense["검색"]["주제 재사용"] && " · 주제 재사용"}</p>
                    )}
                    {q.defense?.["재질문 유형"] && <p><b>재질문 유형</b> {q.defense["재질문 유형"] === "off_target" ? "질문과 다른 답 → 범위를 좁혀" : "답 부족 → 형식을 바꿔"}</p>}
                    <p><b>판정 근거</b> {q.rationale} ({q.judge_model}{q.model_tier === "fast" ? ", 대체 모델" : ""})</p>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>

      {d.llm_calls.length > 0 && (
        <details className="card text-sm">
          <summary className="cursor-pointer font-semibold">LLM 호출 기록 {d.llm_calls.length}건 · 사내 {d.llm_calls.filter((c) => c.provider === "ollama").length}건 ·
            실패 {d.llm_calls.filter((c) => !c.ok).length}건 (프롬프트 본문은 남기지 않음)</summary>
          <table className="mt-2 w-full text-xs">
            <thead className="text-left text-slate-500"><tr><th>목적</th><th>프롬프트</th><th>모델</th><th>min_tier</th><th>토큰</th><th>시간</th><th>결과</th></tr></thead>
            <tbody>
              {d.llm_calls.map((c, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td>{c.purpose}</td><td>{c.prompt_version}</td><td>{c.provider} {c.model}</td><td>{c.min_tier ?? "-"}</td>
                  <td>{c.input_tokens}/{c.output_tokens}</td><td>{(c.latency_ms / 1000).toFixed(1)}초</td>
                  <td className={c.ok ? "" : "text-red-600"}>{c.ok ? "성공" : "실패"}{c.route_note && ` · ${c.route_note}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="card space-y-2 text-sm">
          <p className="font-semibold">검증 5검사{ev && ` (v${ev.version_no})`}</p>
          <p>{ev?.checks.map((c) => `${"①②③④⑤"[c.check_no - 1]} ${CHECKS[c.check_no - 1]} ${c.passed ? "✓" : "✗"}`).join("  ") ?? "-"}</p>
          <p className="font-semibold">본인 확인</p>
          <p>{identity ? `${BAND[identity.band]}${identity.distance ? ` (${identity.distance})` : ""} · 촬영 ${d.identity_checks.length}번` : "-"}</p>
          <p className="font-semibold">감독 이벤트</p>
          {d.proctor_events.length === 0 && <p>-</p>}
          {d.proctor_events.map((e) => <p key={e.id}>{EVENT[e.event_type]} {e.occurrence_no}번 · {(e.duration_ms / 1000).toFixed(1)}초 ({ACTION[e.action]})</p>)}
        </div>
        <div className="card space-y-2 text-sm">
          <p className="font-semibold">의심 건</p>
          {d.suspicions.length === 0 && <p>-</p>}
          {d.suspicions.map((c) => <Suspicion key={c.id} c={c} onDecide={(decision, reason) => act(`/suspicions/${c.id}/decision`, { decision, reason })} />)}
          <p className="font-semibold">담당자 메모</p>
          {d.notes.map((n) => <p key={n.id}>{new Date(n.created_at).toLocaleString("ko-KR")} · {n.body}</p>)}
          <div className="flex gap-2">
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="담당자 메모 입력" />
            <button className="btn" disabled={!note.trim()} onClick={() => act(`/interviews/${sid}/notes`, { body: note }).then(() => setNote(""))}>저장</button>
          </div>
          <p className="text-xs text-slate-500">AI 점수는 고칠 수 없고 메모만 남깁니다.</p>
        </div>
      </div>
    </div>
  );
}

function Suspicion({ c, onDecide }: { c: Detail["suspicions"][number]; onDecide: (d: string, r: string) => void }) {
  const [decision, setDecision] = useState("normal");
  const [reason, setReason] = useState("");
  if (c.status === "decided") return <p>{EVENT[c.reason] ?? c.reason} → {DECISION[c.decision!]} ({c.decision_reason})</p>;
  return (
    <div className="flex items-center gap-2">
      <span>{EVENT[c.reason] ?? c.reason}</span>
      <select className="input w-auto" value={decision} onChange={(e) => setDecision(e.target.value)}>
        {Object.entries(DECISION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="처리 사유" />
      <button className="btn" disabled={!reason.trim()} onClick={() => onDecide(decision, reason)}>결정</button>
    </div>
  );
}

const sec = (ms: number) => (ms / 1000).toFixed(1);
const POSITIVE = ["자신감 있는 목소리", "차분한 목소리", "미소"];

/** 구간별 리포트 (11/10): STT 구간마다 목소리 표기 + 같은 시간 표정 + 판정 근거로 인용됐는지. 표정·목소리는 점수에 쓰지 않고 표기만 */
function SignalReport({ q }: { q: Question }) {
  const sig = q.signals ?? [];
  if (!sig.length) return <p className="text-xs text-slate-500"><b>표정·목소리</b> 기록 없음</p>;
  const shift = sig.find((x) => x.label === "다른 목소리 의심");      // 11/12 참고 표기 (앞 답변과 목소리 높이 차이)
  const voice = sig.filter((x) => x.source === "voice" && x !== shift);
  const face = sig.filter((x) => x.source === "face");
  const faceAt = (t0: number, t1: number) => {
    const n: Record<string, number> = {};
    face.filter((f) => f.t1 >= t0 && f.t0 <= t1).forEach((f) => (n[f.label] = (n[f.label] ?? 0) + Math.min(f.t1, t1) - Math.max(f.t0, t0) + 1));
    return Object.entries(n).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "-";
  };
  const quoted = (text: string) => (q.quotes ?? []).some((x) => text.includes(x) || x.includes(text.trim()));
  const good = voice.filter((v) => POSITIVE.includes(v.label)).map((v) => `${sec(v.t0)}~${sec(v.t1)}초`);
  return (
    <div className="space-y-1" data-testid="signal-report">
      <p className="text-xs"><b>구간별 리포트</b> <span className="text-slate-500">(표정·목소리 톤은 평가에 들어가지 않고 표기만 합니다)</span></p>
      {shift && (
        <p className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-900" data-testid="voice-shift">
          <b>다른 목소리 의심</b> — 이 답변의 목소리 높이({String(shift.value.f0)}Hz)가 앞 답변들({String(shift.value["앞 답변 f0"])}Hz)과 크게 다릅니다.
          감기·긴장으로도 생길 수 있어 점수에는 쓰지 않습니다. 필요하면 다른 답변과 함께 확인해 주세요.
        </p>
      )}
      {good.length > 0 && <p className="text-xs text-emerald-700">자신감 있게 말한 구간: {good.join(", ")}</p>}
      {voice.length > 0 ? (
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500"><tr><th>시간</th><th>답변 구간 (STT)</th><th>목소리</th><th>표정</th><th>판정</th></tr></thead>
          <tbody>
            {voice.map((v, i) => (
              <tr key={i} className="border-t border-slate-200 align-top">
                <td className="whitespace-nowrap">{sec(v.t0)}~{sec(v.t1)}초</td>
                <td>{String(v.value.text ?? "")}</td>
                <td className="whitespace-nowrap" title={`음량 ${v.value.db}dB · 높이 ${v.value.f0 ?? "-"}Hz · ${v.value.cps}자/초 · 앞 쉼 ${v.value.pause}초`}>{v.label}</td>
                <td className="whitespace-nowrap">{faceAt(v.t0, v.t1)}</td>
                <td>{quoted(String(v.value.text ?? "")) ? <span className="text-brand-700">판정 근거로 인용</span> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-xs">표정: {face.map((f) => `${sec(f.t0)}~${sec(f.t1)}초 ${f.label}`).join(" · ")} <span className="text-slate-500">(목소리 구간은 실제 STT에서만)</span></p>
      )}
    </div>
  );
}
