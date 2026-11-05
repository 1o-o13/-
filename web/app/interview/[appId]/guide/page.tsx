"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { day, RulesList, useGuide } from "@/lib/guide";
import { api } from "@/lib/api";
import { levelMeter, openMedia, startRecording } from "@/lib/media";
import { mmss } from "@/lib/timer";

// CAN-008 2차 응시 안내·튜토리얼
export default function GuidePage() {
  const { appId, guide: g, err } = useGuide();
  if (err) return <p className="err">{err}</p>;
  if (!g) return <p>불러오는 중…</p>;
  const done = g.session_status === "completed";
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">2차 응시 안내 · {g.title}</h1>
      <div className="card space-y-3">
        <p>응시 기간 {day(g.stage2_start)} ~ {day(g.stage2_end)}{g.exam_code && ` · 응시 번호 ${g.exam_code}`}</p>
        <p className="text-sm">진행 순서: {g.steps.map((s, i) => `${"①②③④⑤⑥"[i]} ${s}`).join(" → ")}</p>
        <h2 className="font-semibold">AI 화상면접 규칙</h2>
        <RulesList r={g.rules} />
        <p className="text-sm text-slate-600">권장 환경: PC · Chrome 최신 · 웹캠·마이크 · 조용한 장소</p>
      </div>
      <AiNotice />
      <Practice appId={appId} />
      {!done && <Accommodation appId={appId} />}
      <div className="flex items-center gap-3">
        {done ? (
          <span className="btn bg-slate-400">응시 완료</span>
        ) : g.session_status === "in_progress" ? (
          <Link className="btn" href={`/interview/${appId}/live`}>면접 이어 하기</Link>
        ) : g.can_start ? (
          <Link className="btn" href={`/interview/${appId}/precheck`}>응시 시작</Link>
        ) : (
          <button className="btn" disabled>응시 시작</button>
        )}
        {g.reason && !done && <p className="err">{g.reason}</p>}
      </div>
    </div>
  );
}

/** AI 활용 사전 고지 (AI 기본법: 채용은 고영향 AI → 사용 사실·주요 판단 기준·사람의 결정을 미리 알림, 11/12) */
function AiNotice() {
  return (
    <div className="card space-y-2 text-sm">
      <h2 className="font-semibold">AI 활용 안내</h2>
      <ul className="list-disc space-y-1 pl-5 text-slate-700">
        <li>이 면접은 AI가 질문을 만들고, 답변을 글로 바꿔 평가 기준에 따라 정리합니다. <b>합격·불합격은 채용 담당관이 AI 정리와 기록을 보고 직접 결정</b>합니다.</li>
        <li>주요 평가 기준: 기술 답변은 정확성 30 · 회사 상황 적용 30 · 깊이 25 · 구체성 15, 그 밖에 말의 구성·용어·질문 의도(언어 30점), 시간 안에 마친 정도·침묵 비율(10점). 표정·목소리 톤은 점수에 넣지 않습니다.</li>
        <li>AI에는 이름·학교·연락처·주소 등을 가린 내용만 보냅니다. 답변 음성은 글로 바꾼 직후 지우고, 영상은 저장하지 않습니다.</li>
        <li>면접 기록(답변 글·평가·감독 기록)은 최종 발표 후 180일이 지나면 파기합니다.</li>
        <li>말하기가 어려우면 응시 전에 아래에서 &lsquo;글로 답하기&rsquo;를 신청할 수 있습니다 (담당관 확인 뒤 적용).</li>
      </ul>
    </div>
  );
}

type Acc = { request: { reason: string; status: "requested" | "approved" | "rejected"; decision_note: string | null } | null; can_request: boolean };
const ACC_STATUS = { requested: "담당관 확인 중", approved: "승인됨 — 면접에서 녹음 대신 글로 답합니다", rejected: "승인되지 않음" } as const;

/** 글로 답하기 신청 (응시 편의, 11/12): 응시 전에 사유를 적어 신청 → 담당관 승인 뒤 적용 */
function Accommodation({ appId }: { appId: number }) {
  const [a, setA] = useState<Acc | null>(null);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => api<Acc>(`/interview/applications/${appId}/accommodation`).then(setA, () => setA(null));
  useEffect(() => { load(); }, [appId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!a) return null;
  const r = a.request;
  async function send() {
    try {
      await api(`/interview/applications/${appId}/accommodation`, { method: "POST", json: { reason } });
      setOpen(false);
      setMsg("신청했습니다. 담당관이 확인하면 이 화면에 결과가 보입니다.");
      load();
    } catch (e) { setMsg(e instanceof Error ? e.message : "신청하지 못했습니다"); }
  }
  return (
    <div className="card space-y-2 text-sm">
      <h2 className="font-semibold">글로 답하기 신청 <span className="text-xs font-normal text-slate-500">말하기가 어려운 경우 (응시 편의)</span></h2>
      {r && <p>상태: <b>{ACC_STATUS[r.status]}</b>{r.decision_note && ` · ${r.decision_note}`}</p>}
      {a.can_request && !open && (
        <button className="btn-line" onClick={() => { setOpen(true); setReason(r?.reason ?? ""); }}>{r ? "사유 고쳐 다시 신청" : "신청하기"}</button>
      )}
      {open && (
        <div className="space-y-2">
          <textarea className="h-24 w-full rounded border border-slate-300 p-2" value={reason} maxLength={500} aria-label="신청 사유"
            placeholder="말하기가 어려운 사유를 적어 주세요 (5자 이상). 증빙이 필요하면 담당관이 따로 연락합니다." onChange={(e) => setReason(e.target.value)} />
          <div className="flex gap-2">
            <button className="btn" disabled={reason.trim().length < 5} onClick={send}>신청</button>
            <button className="btn-line" onClick={() => setOpen(false)}>취소</button>
          </div>
        </div>
      )}
      {!a.can_request && !r && <p className="text-slate-500">면접을 시작한 뒤에는 신청할 수 없습니다.</p>}
      {msg && <p className="text-slate-600">{msg}</p>}
    </div>
  );
}

type Practice = { questions: string[]; think_sec: number; answer_max_sec: number };

/** 연습 면접 (11/12): 실제 화면과 같은 흐름 — 질문 음성 → 생각 시간 → 녹음 → 인식 글 확인. 질문 2개.
 *  평가·저장 없음: 음성은 서버에서 글로 바꾼 뒤 바로 지우고, 글도 남기지 않는다 */
function Practice({ appId }: { appId: number }) {
  const video = useRef<HTMLVideoElement>(null);
  const [p, setP] = useState<Practice | null>(null);
  const [n, setN] = useState(0);                                         // 0 = 시작 전, 1·2 = 연습 질문 번호
  const [state, setState] = useState<"think" | "record" | "stt" | "show" | "end">("think");
  const [left, setLeft] = useState(0);
  const [level, setLevel] = useState(0);
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const r = useRef<{ stream?: MediaStream; meter?: ReturnType<typeof levelMeter>; rec?: ReturnType<typeof startRecording>; audio?: HTMLAudioElement; t0: number; timer: number; phase: string }>({ t0: 0, timer: 0, phase: "" });

  useEffect(() => { api<Practice>(`/interview/applications/${appId}/practice`).then(setP, () => setP(null)); }, [appId]);
  useEffect(() => () => stopAll(), []); // eslint-disable-line react-hooks/exhaustive-deps

  function stopAll() {
    clearInterval(r.current.timer);
    r.current.meter?.close();
    r.current.stream?.getTracks().forEach((t) => t.stop());
    r.current.audio?.pause();
    r.current = { t0: 0, timer: 0, phase: "" };
  }
  function play(k: number) {
    r.current.audio?.pause();
    const a = new Audio(`/api/interview/applications/${appId}/practice/${k}/audio`);
    r.current.audio = a;
    a.play().catch(() => { /* 음성이 없으면 글로 */ });
  }
  async function begin(k: number) {
    if (!p) return;
    setErr(""); setText(null); setN(k); setState("think");
    if (!r.current.stream) {
      const s = await openMedia();
      r.current.stream = s;
      r.current.meter = levelMeter(s);
      if (video.current) video.current.srcObject = s;
    }
    play(k);
    r.current.t0 = performance.now();
    r.current.phase = "think";
    clearInterval(r.current.timer);
    r.current.timer = window.setInterval(() => {
      const sec = (performance.now() - r.current.t0) / 1000;
      setLevel(r.current.meter?.read() ?? 0);
      if (r.current.phase === "think") {
        setLeft(p.think_sec - sec);
        if (sec >= p.think_sec) {
          r.current.audio?.pause();                                       // 녹음에 스피커 소리가 섞이지 않게
          r.current.rec = startRecording(r.current.stream!);
          r.current.phase = "record";
          r.current.t0 = performance.now();
          setState("record");
        }
      } else if (r.current.phase === "record") {
        setLeft(p.answer_max_sec - sec);
        if (sec >= p.answer_max_sec) done();
      }
    }, 100);
  }
  async function done() {
    if (r.current.phase !== "record" || !r.current.rec) return;
    r.current.phase = "stt";
    setState("stt");
    const blob = await r.current.rec.stop();
    const body = new FormData();
    body.append("audio", blob, "practice.webm");
    try {
      const out = await api<{ text: string | null }>(`/interview/applications/${appId}/practice/stt`, { method: "POST", body });
      setText(out.text);
    } catch (e) { setErr(e instanceof Error ? e.message : "글로 바꾸지 못했습니다"); }
    setState("show");
  }

  if (!p) return null;
  return (
    <div className="card space-y-2">
      <h2 className="font-semibold">연습 면접 <span className="text-xs font-normal text-slate-500">평가에 반영하지 않고 저장하지 않습니다 · 질문 {p.questions.length}개</span></h2>
      {n === 0 ? (
        <button className="btn-line" onClick={() => begin(1)}>연습 시작</button>
      ) : (
        <div className="flex gap-4">
          <video ref={video} autoPlay muted playsInline className="h-36 w-48 -scale-x-100 rounded bg-black" />
          <div className="flex-1 space-y-2">
            <p>{p.questions[n - 1]}</p>
            {state === "think" && (
              <p className="text-sm">생각 시간 {mmss(left)} <button className="ml-2 text-brand-700 underline" onClick={() => play(n)}>🔊 다시 듣기</button></p>
            )}
            {state === "record" && (
              <>
                <p className="text-sm">● 녹음 중 {mmss(left)}</p>
                <div className="h-2 w-48 rounded bg-slate-200"><div className="h-2 rounded bg-green-500" style={{ width: `${Math.min(100, level * 400)}%` }} /></div>
                <button className="btn-line" onClick={done}>답변 끝</button>
              </>
            )}
            {state === "stt" && <p className="text-sm text-slate-600">답변을 글로 바꾸는 중…</p>}
            {state === "show" && (
              <div className="space-y-2 rounded border border-slate-200 bg-slate-50 p-3 text-sm">
                <p className="text-xs text-slate-500">내 답변 (인식된 글)</p>
                <p>{text ?? (err || "말한 내용이 인식되지 않았습니다. 마이크를 확인해 주세요.")}</p>
                <p className="text-xs text-slate-500">실제 면접에서는 여기서 잘못 인식된 부분을 고칠 수 있습니다 (원래 글의 30%까지, 60초).</p>
                {n < p.questions.length
                  ? <button className="btn-line" onClick={() => begin(n + 1)}>다음 연습 질문</button>
                  : <button className="btn-line" onClick={() => { stopAll(); setN(0); }}>연습 마치기</button>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
