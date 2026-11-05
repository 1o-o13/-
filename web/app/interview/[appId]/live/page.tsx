"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { type Expression, loadFace, look, segments } from "@/lib/face";
import { useGuide } from "@/lib/guide";
import { levelMeter, openMedia, snapshot, startRecording } from "@/lib/media";
import { FaceWatch, LeaveTracker, type ProctorEvent } from "@/lib/proctor";
import { SILENCE_LEVEL, SilenceTracker } from "@/lib/silence";
import { left, mmss, recordDeadline } from "@/lib/timer";
import { EDIT_MAX, editRatio } from "@/lib/edit";

type Q = { id: number; ask_order: number; kind: "non_tech" | "tech"; question_type: "main" | "followup" | "reask"; depth: number; question_text: string };
type Review = { answer_id: number; question_id: number; ask_order: number; ready: boolean; text: string | null; remaining_sec: number };
type State = { status: string; total_questions: number; silence_skip_sec: number; question: Q | null; phase: "think" | "record" | "review" | "preparing" | "ended"; remaining_sec: number; review: Review | null; answer_mode?: "voice" | "text" };
type Phase = "loading" | "think" | "record" | "upload" | "transcribing" | "review" | "preparing";

const INTRO = { main: "AI 면접관", followup: "조금 더 여쭤보겠습니다", reask: "같은 질문을 한 번 더 드립니다" } as const;
const FACE_MSG = { face_missing: "얼굴이 화면에 보이도록 해 주세요.", multi_face: "화면에는 응시자 한 명만 있어야 합니다.", gaze_away: "화면을 바라봐 주세요." };
const UPLOAD_TRIES = 3; // 업로드 실패는 3번까지 다시 보낸다 (IV-20)
const RECHECK_MS = 60_000; // 임시: 면접 중 본인 확인 간격 (identity_check phase 'recheck' = 60초마다)
const FONT = ["text-lg", "text-xl", "text-2xl"] as const; // 질문 글자 크기 (11/12 접근성)
const SPEAK_WAIT_MS = 30_000; // 임시: 질문 읽기가 끝났다는 신호를 이만큼 못 받으면 녹음을 시작한다

// CAN-012 AI 화상면접. 점수·판정은 보여 주지 않고 번호·질문 종류·남은 시간만
export default function Live() {
  const { appId, guide, err: gErr, router } = useGuide();
  const video = useRef<HTMLVideoElement>(null);
  const [q, setQ] = useState<Q | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [now, setNow] = useState(0);
  const [warning, setWarning] = useState("");
  const [notice, setNotice] = useState("");
  const [finished, setFinished] = useState(false); // 마지막 답변 제출 → '제출되었습니다' 안내 뒤 완료 화면으로
  const [err, setErr] = useState("");
  const [paused, setPaused] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [rv, setRv] = useState<Review | null>(null);          // 답변 인식 글 확인 (11/11)
  const [draft, setDraft] = useState<string | null>(null);   // 수정 중인 글 (null = 수정 안 함)
  const [rvErr, setRvErr] = useState("");
  const [mic, setMic] = useState<number | null>(null); // 지금 마이크 음량 (null = 마이크를 못 엶)
  const [textMode, setTextMode] = useState(false); // 글로 답하기 승인 (11/12): 녹음 대신 글 입력
  const [typed, setTyped] = useState("");
  const [fs, setFs] = useState(() => { try { return Math.min(2, Number(localStorage.getItem("qfs") ?? 0)); } catch { return 0; } });
  const font = (d: number) => setFs((v) => { const n = Math.max(0, Math.min(2, v + d)); try { localStorage.setItem("qfs", String(n)); } catch { /* 저장 못 해도 화면만 */ } return n; });
  const [faceNow, setFaceNow] = useState<{ faces: number; away: boolean } | "off" | null>(null); // 얼굴·시선 (off = 감지 못 씀)
  const m = useRef({
    q: null as Q | null, phase: "loading" as Phase, thinkEnd: 0, recordEnd: 0, recStart: 0,
    faceSamples: [] as { t: number; label: Expression; value: Record<string, number> }[], // 녹음 중 표정 표본 (점수에 안 씀, 리포트 표기용)
    lastRecheck: 0, // 면접 중 본인 확인 프레임을 마지막으로 보낸 때
    stream: null as MediaStream | null, meter: null as ReturnType<typeof levelMeter> | null,
    rec: null as ReturnType<typeof startRecording> | null, silence: null as SilenceTracker | null,
    answered: new Set<number>(), // 답변을 낸 문항 (늦게 온 응답이 새 문항을 덮지 않게)
    speaking: false, // 질문을 읽는 중 (끝나기 전에는 녹음을 시작하지 않는다 → 면접관 목소리가 답변에 섞이지 않게)
    finishing: false, reviewEnd: 0, reviewId: 0, confirming: false, lastPoll: 0, draft: null as string | null, rv: null as Review | null, // 답변 인식 글 확인 (11/11)
    textMode: false, typed: "", // 글로 답하기 (11/12)
    reading: false, shownAt: 0, // 새 질문을 처음 읽는 중: 생각 시간은 읽기가 끝난 뒤부터 센다 (질문 제시 → 준비 시간, 활동다이어그램 1109)
  });
  const talk = (v: boolean) => {
    m.current.speaking = v;
    setSpeaking(v);
  };
  const sid = guide?.session_id;
  const rules = guide?.rules;

  const go = (p: Phase) => {
    m.current.phase = p;
    setPhase(p);
  };
  const toDone = () => router.push(`/interview/${appId}/done`);

  /** 질문 읽기. 서버 음성(Supertonic, 단계 6)이 없으면 임시로 브라우저 음성으로 읽고, 그것도 안 되면 글로만 진행 (IV-17) */
  function speak(question: Q) {
    const audio = new Audio(`/api/interview/sessions/${sid}/questions/${question.id}/audio`);
    talk(true);
    audio.onended = audio.onerror = () => talk(false);
    audio.play().catch(() => {
      if (!("speechSynthesis" in window)) return talk(false);
      const u = new SpeechSynthesisUtterance(question.question_text);
      u.lang = "ko-KR";
      u.onend = u.onerror = () => talk(false);
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    });
  }

  /** 서버 상태를 화면에 반영. 같은 문항이면 남은 시간만 맞추고(재접속·추가 시간), 새 문항이면 생각 시간부터 */
  function apply(st: State) {
    m.current.textMode = st.answer_mode === "text";
    setTextMode(m.current.textMode);
    if (st.status !== "in_progress") {
      const last = m.current.q;                     // 마지막 문항이 무응답이라 확인할 글 없이 끝나도 '제출되었습니다' 안내 뒤 완료 화면
      if (st.status === "completed" && last && m.current.answered.has(last.id) && last.ask_order >= st.total_questions) return finish();
      return toDone();
    }
    if (st.phase === "review" && st.review) {       // 답변을 글로 바꾸는 중 / 인식 글 확인 (재접속해도 이어서)
      const r = st.review;
      if (!r.ready) return go("transcribing");
      if (m.current.reviewId !== r.answer_id) {
        m.current.reviewId = r.answer_id;
        m.current.reviewEnd = Date.now() + r.remaining_sec * 1000;
        m.current.draft = null;
        m.current.rv = r;
        setRv(r);
        setDraft(null);
        setRvErr("");
      }
      return go("review");
    }
    if (m.current.phase === "review" || m.current.confirming) return;   // 확인 중에는 늦게 온 '준비 중'을 무시
    if (!st.question) {
      if (!m.current.q || m.current.answered.has(m.current.q.id)) go("preparing"); // 새 문항을 이미 받았으면 늦게 온 '준비 중'은 무시
      return;
    }
    const t = Date.now();
    const same = m.current.q?.id === st.question.id;
    if (same && m.current.phase === "upload") return;
    if (st.phase === "think") {
      m.current.thinkEnd = t + st.remaining_sec * 1000;
      m.current.recordEnd = recordDeadline("think", st.remaining_sec, rules!.answer_max_sec, t);
    } else {
      m.current.thinkEnd = t;
      m.current.recordEnd = recordDeadline("record", st.remaining_sec, rules!.answer_max_sec, t);
    }
    if (same) return;
    m.current.q = st.question;
    setQ(st.question);
    m.current.reading = st.phase === "think";      // 새 문항: 읽기가 끝나면 생각 시간을 처음부터
    m.current.shownAt = t;
    go("think");
    speak(st.question);
  }

  const refresh = () => api<State>(`/interview/sessions/${sid}/state`).then(apply, (e) => setErr(e.message));

  async function proctor(ev: ProctorEvent) {
    const r = await api<{ action: string }>(`/interview/sessions/${sid}/proctor`, { method: "POST", json: ev }).catch(() => null);
    if (r?.action === "abandoned") return toDone();
    if (r?.action !== "warned") return;
    if (ev.event_type === "tab_leave" || ev.event_type === "window_blur") setWarning("on");
    else if (ev.event_type !== "upload_fail") setNotice(FACE_MSG[ev.event_type]); // 얼굴 경고도 팝업으로 (시안과 같게)
  }

  async function submit(inTime: boolean) {
    const s = m.current;
    if (s.textMode && s.phase === "record") return submitText(inTime);
    if (s.phase !== "record" || !s.rec) return;
    go("upload");
    speechSynthesis?.cancel();
    talk(false);
    const blob = await s.rec.stop();
    const form = { answer_sec: ((Date.now() - s.recStart) / 1000).toFixed(1), silence_ratio: s.silence!.ratio().toFixed(3), finished_in_time: String(inTime), voiced_sec: s.silence!.voicedSec().toFixed(1) };
    const q = s.q!;
    for (let i = 0; i < UPLOAD_TRIES; i++) {
      const body = new FormData();
      body.append("audio", blob, "answer.webm");
      body.append("face_signals", JSON.stringify(segments(s.faceSamples)));
      Object.entries({ ...form, upload_retry_count: String(i) }).forEach(([k, v]) => body.append(k, v));
      try {
        await api(`/interview/sessions/${sid}/questions/${q.id}/answer`, { method: "POST", body });
        s.answered.add(q.id);
        go("transcribing");                         // 인식된 글을 보여 주고 확인받은 뒤 다음 질문 (11/11)
        return refresh();
      } catch {
        if (i === UPLOAD_TRIES - 1) {
          await proctor({ event_type: "upload_fail", duration_ms: 0 });
          setErr("답변을 보내지 못했습니다. 계속되면 면접이 끝난 뒤 '문의하기'의 담당자 연락처로 알려 주세요.");
        }
      }
    }
  }

  /** 글로 답하기: 쓴 글을 그대로 제출 (음성·인식 글 확인 없음) → 다음 질문 */
  async function submitText(inTime: boolean) {
    const s = m.current;
    const q = s.q!;
    go("upload");
    try {
      await api(`/interview/sessions/${sid}/questions/${q.id}/answer-text`, {
        method: "POST", json: { text: s.typed, answer_sec: Number(((Date.now() - s.recStart) / 1000).toFixed(1)), finished_in_time: inTime },
      });
      s.answered.add(q.id);
      s.typed = "";
      setTyped("");
      go("preparing");
      return refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "답변을 보내지 못했습니다");
    }
  }

  /** 마지막 답변 제출 안내(2.5초) 뒤 완료 화면. SSE·상태 조회가 겹쳐 불려도 한 번만 */
  function finish() {
    if (m.current.finishing) return;
    m.current.finishing = true;
    setFinished(true);
    setTimeout(toDone, 2500);
  }

  /** 인식 글 확인 '완료': 고친 글(또는 그대로)로 판정 → 다음 질문. 마지막 문항이면 제출 안내 뒤 완료 화면 */
  async function confirm(auto = false) {
    const s = m.current;
    const r = s.rv;
    if (s.phase !== "review" || s.confirming || !r) return;
    const text = s.draft !== null && (!auto || editRatio(r.text ?? "", s.draft) <= EDIT_MAX) ? s.draft : null;
    s.confirming = true;
    try {
      await api(`/interview/sessions/${sid}/answers/${r.answer_id}/confirm`, { method: "POST", json: { text } });
    } catch (e) {
      s.confirming = false;
      if (!auto) return setRvErr((e as Error).message);   // 30% 넘게 고침 등: 고친 뒤 다시 '완료'. 시간이 끝났으면 서버가 원본으로 진행
    }
    s.confirming = false;
    s.rv = null;
    setRv(null);
    if (r.ask_order >= rules!.total_questions) return finish();   // 마지막 문항: 제출 안내를 보여 준 뒤 완료 화면으로 (판정이 끝나기 전에도)
    go("preparing");
    refresh();
  }
  const confirmRef = useRef(confirm);
  confirmRef.current = confirm;

  // 카메라·마이크, 질문 진행 타이머, SSE, 감독
  useEffect(() => {
    if (!sid || !rules) return;
    let alive = true;
    const leave = new LeaveTracker();
    const face = new FaceWatch();
    const es = new EventSource(`/api/interview/sessions/${sid}/events`);
    es.addEventListener("question", (e) => apply(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("review", (e) => apply(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("ended", (e) => apply(JSON.parse((e as MessageEvent).data)));   // 마지막 답변이면 제출 안내 먼저
    es.addEventListener("error", (e) => (e as MessageEvent).data && toDone()); // 서버가 보낸 error(시스템 오류)만. 연결 끊김은 자동 재연결
    const onHide = () => (document.hidden ? leave.leave("tab_leave", Date.now()) : back());
    const onBlur = () => leave.leave("window_blur", Date.now());
    const back = () => {
      const ev = leave.back(Date.now());
      if (ev) proctor(ev);
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", back);
    let detector: Awaited<ReturnType<typeof loadFace>> = null;
    let lastLook = 0;

    openMedia().then(async (stream) => {
      if (!alive) return stream.getTracks().forEach((t) => t.stop());
      m.current.stream = stream;
      m.current.meter = levelMeter(stream);
      if (video.current) video.current.srcObject = stream;
      await refresh();
      detector = await loadFace().catch(() => null);
      if (!detector) setFaceNow("off");
    }, () => setErr("카메라·마이크를 열 수 없습니다. 브라우저 권한을 확인해 주세요."));

    const timer = window.setInterval(() => {
      const s = m.current;
      const t = Date.now();
      setNow(t);
      setPaused(!!s.meter?.suspended());
      if (s.meter?.suspended()) return; // 소리를 못 재는 동안은 녹음·침묵 판정을 하지 않는다
      const rms = s.meter ? s.meter.read() : 0;
      setMic(s.meter ? rms : null);
      // 질문 읽기가 끝나면 그때부터 생각 시간 (끝 신호가 안 오면 질문을 띄운 뒤 30초에 시작, 임시)
      if (s.phase === "think" && s.reading && (!s.speaking || t >= s.shownAt + SPEAK_WAIT_MS)) {
        const think = (s.q?.kind === "non_tech" ? rules.think_sec_non_tech : rules.think_sec_tech) * 1000;
        s.reading = false;
        s.thinkEnd = t + think;
        s.recordEnd = s.thinkEnd + rules.answer_max_sec * 1000;
      }
      // 생각 시간이 끝나면 녹음 ('다시 듣기' 중이면 읽기가 끝날 때까지, 최대 30초)
      if (s.phase === "think" && !s.reading && t >= s.thinkEnd && s.stream && (!s.speaking || t >= s.thinkEnd + SPEAK_WAIT_MS)) {
        s.rec = s.textMode ? null : startRecording(s.stream);   // 글로 답하기는 녹음하지 않는다
        s.faceSamples = [];
        s.silence = new SilenceTracker(rules.silence_skip_sec * 1000);
        s.recStart = t;
        go("record");
      } else if (s.phase === "record") {
        if (!s.textMode) s.silence!.push(rms, t); // 침묵 비율만 잰다 (11/11: 침묵 자동 제출 없앰 → '답변 끝' 버튼이나 최대 시간으로만 제출)
        if (t >= s.recordEnd) submit(false); // 답변 최대 시간
      } else if (s.phase === "review" && t >= s.reviewEnd - 1000) {
        confirmRef.current(true);                 // 확인 시간 끝: 고친 글이 범위 안이면 그 글, 아니면 인식 글 그대로
      } else if (s.phase === "transcribing" && t - s.lastPoll >= 2000) {
        s.lastPoll = t;                           // SSE가 늦어도 인식 글을 받게 2초마다 확인
        refresh();
      }
      if (detector && video.current && video.current.readyState >= 2 && t - lastLook >= 500) {
        lastLook = t;
        const r = look(detector, video.current, performance.now());
        if (s.phase === "record") s.faceSamples.push({ t: t - s.recStart, label: r.faces ? r.expr.label : "얼굴 없음", value: r.expr.value });
        setFaceNow({ faces: r.faces, away: r.gazeAway });
        face.update(r.faces, r.gazeAway, t).forEach(proctor);
      }
      // 면접 중 본인 확인: 60초마다 프레임 1장 (임시 간격). 서버가 거리만 기록하고 사진은 저장하지 않는다
      if (video.current && video.current.readyState >= 2 && (s.phase === "think" || s.phase === "record") && t - s.lastRecheck >= RECHECK_MS) {
        s.lastRecheck = t;
        snapshot(video.current).then((frame) => {
          const body = new FormData();
          body.append("frame", frame, "frame.jpg");
          return api(`/interview/sessions/${sid}/identity-recheck`, { method: "POST", body });
        }).catch(() => {});
      }
    }, 100);

    return () => {
      alive = false;
      clearInterval(timer);
      es.close();
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", back);
      m.current.meter?.close();
      m.current.stream?.getTracks().forEach((t) => t.stop());
    };
  }, [sid, rules]);

  if (gErr) return <p className="err p-6">{gErr}</p>;
  if (!guide || !rules) return <p className="p-6">불러오는 중…</p>;
  const s = m.current;
  const thinkSec = q?.kind === "non_tech" ? rules.think_sec_non_tech : rules.think_sec_tech;
  const thinkLeft = s.reading ? thinkSec : left(s.thinkEnd, now);
  const recLeft = left(s.recordEnd, now);
  const timeLabel =
    phase === "think" && s.reading ? "질문을 읽는 중" : phase === "think" ? `생각 시간 ${mmss(thinkLeft)}` : phase === "record" ? `답변 남은 시간 ${mmss(recLeft)}` : phase === "transcribing" ? "답변을 글로 바꾸는 중" : phase === "review" ? `답변 확인 ${mmss(left(s.reviewEnd, now))}` : phase === "upload" || phase === "preparing" ? "다음 질문 준비 중" : "질문";
  const kind = !q ? "" : q.kind === "non_tech" ? "경험·가치" : q.question_type === "followup" ? `꼬리질문 ${q.depth}` : q.question_type === "reask" ? "다시 질문" : "기술";
  const waiting = phase === "upload" || phase === "preparing" || !q;

  return (
    <main className="flex min-h-screen flex-col bg-room text-room-fg">
      <div className="flex flex-wrap items-center gap-2.5 border-b border-room-3 px-4 py-2.5">
        <h1 className="font-bold">새벽소프트 · AI 화상면접</h1>
        {q && <span className="pill font-mono" data-testid="qnum">{q.ask_order} / {rules.total_questions}</span>}
        {q && <span className="pill">{kind}</span>}
        <span className="flex-1" />
        <span className="flex items-center gap-1 text-xs text-room-muted" aria-label="질문 글자 크기">
          글자
          <button className="rounded bg-room-3 px-2 py-0.5 hover:bg-room-3/70" onClick={() => font(-1)} disabled={fs === 0}>가-</button>
          <button className="rounded bg-room-3 px-2 py-0.5 hover:bg-room-3/70" onClick={() => font(1)} disabled={fs === 2}>가+</button>
        </span>
        <span className={`pill font-mono ${phase === "record" ? "bg-dawn-500/25 text-dawn-400" : ""}`}>{timeLabel}</span>
      </div>

      <div className="grid flex-1 grid-cols-[1.5fr_1fr] gap-3.5 p-4 max-md:grid-cols-1">
        <div className="flex min-w-0 flex-col gap-3.5">
          <div className="tile flex min-h-[300px] items-center justify-center">
            <div className={`orb ${speaking ? "talk" : ""}`} />
            {q && !waiting && phase === "think" && ( /* 녹음 중에 다시 들으면 스피커 소리가 답변에 녹음됨 */
              <button className="absolute bottom-3 right-3 rounded-md bg-room-3 px-3 py-1 text-sm hover:bg-room-3/70" onClick={() => speak(q)}>🔊 다시 듣기</button>
            )}
          </div>
          <div className="tile space-y-2 p-5">
            <p className="text-sm text-avatar">{q ? INTRO[q.question_type] : "AI 면접관"}</p>
            <p className={`${FONT[fs]} leading-relaxed`} data-testid="question">
              {waiting ? <span className="text-room-muted">답변을 정리하고 다음 질문을 준비하고 있습니다… (최대 60초)</span> : q.question_text}
            </p>
          </div>
          {(phase === "transcribing" || phase === "review") && (
            <ReviewBox phase={phase} rv={rv} draft={draft} err={rvErr} left={left(s.reviewEnd, now)}
              onEdit={(v) => { m.current.draft = v; setDraft(v); setRvErr(""); }} onDone={() => confirm(false)} />
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-3.5">
          <div className="tile">
            <video ref={video} autoPlay muted playsInline className="aspect-video w-full -scale-x-100 bg-black object-cover" />
            <span className="absolute bottom-2 left-2 rounded bg-black/50 px-2 py-0.5 text-xs text-room-muted">영상은 저장되지 않습니다</span>
            <MicMeter rms={mic} />
            <FaceBadge now={faceNow} />
          </div>
          <div className="tile space-y-2 p-4">
            {phase === "think" && (
              <>
                <p className="text-sm text-room-muted">{s.reading ? "질문을 끝까지 들은 뒤 생각 시간이 시작됩니다" : "생각 시간이 끝나면 녹음이 시작됩니다"}</p>
                <p className="font-mono text-5xl font-semibold">{Math.ceil(thinkLeft)}</p>
                <Bar pct={100 - (thinkLeft / thinkSec) * 100} />
              </>
            )}
            {phase === "record" && textMode && (
              <>
                <p className="text-sm text-room-muted">글로 답하기 (담당관 승인) · 남은 시간 {mmss(recLeft)}</p>
                <textarea className="h-40 w-full rounded-md border border-room-3 bg-room-3 p-2 text-room-fg" value={typed} maxLength={5000}
                  aria-label="답변 글" onChange={(e) => { m.current.typed = e.target.value; setTyped(e.target.value); }} />
                <Bar pct={100 - (recLeft / rules.answer_max_sec) * 100} />
                <button className="btn w-full" onClick={() => submit(true)}>답변 제출</button>
              </>
            )}
            {phase === "record" && !textMode && (
              <>
                <div className="flex items-center">
                  <span className="text-dawn-400">● 녹음 중</span>
                  <span className="flex-1" />
                </div>
                <Bar pct={100 - (recLeft / rules.answer_max_sec) * 100} />
                <p className="text-xs text-room-muted">다시 녹음할 수 없습니다. 답변을 마치면 아래 버튼을 눌러 주세요.</p>
                <button className="btn w-full" onClick={() => submit(true)}>답변 끝</button>
              </>
            )}
            {waiting && (
              <>
                <p className="text-sm text-room-muted">{phase === "upload" ? "답변을 보내고 있습니다…" : "제출했습니다. 다음 질문을 준비하고 있습니다."}</p>
                <Bar pct={60} />
              </>
            )}
            {phase === "transcribing" && <p className="text-sm text-room-muted">답변을 글로 바꾸고 있습니다…</p>}
            {phase === "review" && (
              <>
                <p className="text-sm text-room-muted">인식된 답변을 확인해 주세요. 시간이 지나면 그대로 제출됩니다.</p>
                <p className="font-mono text-5xl font-semibold">{Math.ceil(left(s.reviewEnd, now))}</p>
                <Bar pct={100 - (left(s.reviewEnd, now) / 60) * 100} />
              </>
            )}
            {notice && <p className="rounded bg-dawn-500/20 p-2 text-sm text-dawn-400">{notice}</p>}
            {err && <p className="text-sm text-red-400">{err}</p>}
          </div>
          <div className="tile p-3">
            <p className="mb-1.5 text-xs text-room-muted">진행</p>
            <div className="flex flex-wrap gap-1.5">
              {Array.from({ length: rules.total_questions }, (_, i) => {
                const cur = q ? q.ask_order - 1 : -1;
                const done = i < cur || (i === cur && waiting);
                return (
                  <span key={i} className={`flex h-7 w-7 items-center justify-center rounded-full font-mono text-xs ${done ? "bg-avatar/30 text-room-fg" : i === cur ? "bg-avatar text-room" : "bg-room-3 text-room-muted"}`}>
                    {i + 1}
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {warning && (
        <Modal>
          <p className="font-semibold text-dawn-500">⚠ 화면을 벗어났습니다 (1번째)</p>
          <p>한 번 더 벗어나거나 10초 이상 벗어나면 면접이 포기 처리됩니다.</p>
          <button className="btn" onClick={() => setWarning("")}>계속하기</button>
        </Modal>
      )}
      {finished && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="alertdialog" data-testid="finished">
          <div className="tile space-y-2 p-6 text-center">
            <p className="text-lg font-semibold">✓ 마지막 답변이 제출되었습니다</p>
            <p className="text-sm text-room-muted">면접이 종료되었습니다. 잠시 뒤 완료 화면으로 넘어갑니다.</p>
          </div>
        </div>
      )}
      {notice && (
        <Modal>
          <p className="font-semibold text-dawn-500">⚠ 감독 경고</p>
          <p>{notice}</p>
          <button className="btn" onClick={() => setNotice("")}>계속하기</button>
        </Modal>
      )}
      {paused && (
        <Modal>
          <p>면접을 이어 가려면 아래 버튼을 눌러 주세요.</p>
          <button className="btn" onClick={() => m.current.meter?.resume()}>면접 이어 하기</button>
        </Modal>
      )}
    </main>
  );
}

/** 답변 인식 글 확인·수정 (11/11). 인식이 틀린 곳만 고칠 수 있다 (원본 대비 30%까지, 서버가 최종 확인) */
function ReviewBox({ phase, rv, draft, err, left: sec, onEdit, onDone }: {
  phase: "transcribing" | "review"; rv: Review | null; draft: string | null; err: string; left: number;
  onEdit: (v: string | null) => void; onDone: () => void;
}) {
  if (phase === "transcribing" || !rv)
    return <div className="tile p-5 text-sm text-room-muted" data-testid="review">답변을 글로 바꾸고 있습니다… 잠시 뒤 인식된 답변을 확인할 수 있습니다.</div>;
  const ratio = draft === null ? 0 : editRatio(rv.text ?? "", draft);
  const over = ratio > EDIT_MAX;
  return (
    <div className="tile space-y-3 p-5" data-testid="review">
      <div className="flex items-center">
        <p className="font-semibold">내 답변 확인</p>
        <span className="flex-1" />
        <span className="font-mono text-xs text-room-muted">남은 시간 {mmss(sec)}</span>
      </div>
      <p className="text-sm text-room-muted">말씀하신 내용이 맞게 적혔는지 확인해 주세요. 잘못 알아들은 부분만 고칠 수 있습니다 (새 내용 추가 불가).</p>
      {draft === null ? (
        <p className="whitespace-pre-wrap rounded-md bg-room-3 p-3 leading-relaxed" data-testid="review-text">{rv.text}</p>
      ) : (
        <>
          <textarea className="h-40 w-full rounded-md bg-room-3 p-3 leading-relaxed text-room-fg outline-none ring-avatar focus:ring-2" name="review_text"
            value={draft} onChange={(e) => onEdit(e.target.value)} />
          <p className={`text-xs ${over ? "text-red-400" : "text-room-muted"}`}>
            바뀐 정도 약 {Math.round(ratio * 100)}% / 최대 {Math.round(EDIT_MAX * 100)}%{over && " — 인식이 틀린 부분만 고쳐 주세요"}
          </p>
        </>
      )}
      {err && <p className="text-sm text-red-400">{err}</p>}
      <div className="flex gap-2">
        {draft === null
          ? <button className="flex-1 rounded-md border border-room-3 bg-room-3 px-4 py-2 text-room-fg hover:bg-room-3/70" onClick={() => onEdit(rv.text ?? "")}>수정하기</button>
          : <button className="flex-1 rounded-md border border-room-3 bg-room-3 px-4 py-2 text-room-fg hover:bg-room-3/70" onClick={() => onEdit(null)}>수정 취소</button>}
        <button className="btn flex-1" disabled={over} onClick={onDone}>완료</button>
      </div>
    </div>
  );
}

/** 얼굴·시선 표시 (감독용 감지를 지원자도 바로 볼 수 있게). 5초 넘게 이어지면 경고 + 의심 건 */
function FaceBadge({ now }: { now: { faces: number; away: boolean } | "off" | null }) {
  const [text, tone] =
    now === null ? ["얼굴 확인 중…", "text-room-muted"]
    : now === "off" ? ["얼굴 감지를 쓸 수 없습니다", "text-red-400"]
    : now.faces === 0 ? ["얼굴이 보이지 않습니다", "text-dawn-400"]
    : now.faces > 1 ? [`얼굴 ${now.faces}명 감지`, "text-red-400"]
    : now.away ? ["얼굴 1명 · 시선 화면 밖", "text-dawn-400"]
    : ["얼굴 1명 · 시선 화면 안", "text-green-400"];
  return (
    <span className={`absolute left-2 top-2 flex items-center gap-1.5 rounded bg-black/60 px-2 py-1 text-xs ${tone}`} data-testid="face-badge">
      <span>👁</span>
      {text}
    </span>
  );
}

/** 마이크 인식 표시: 막대 5칸 + 상태. 소리가 침묵 기준을 넘으면 '소리 들림' */
function MicMeter({ rms }: { rms: number | null }) {
  const heard = rms !== null && rms > SILENCE_LEVEL;
  const bars = rms === null ? 0 : Math.min(5, Math.ceil(rms / 0.03)); // 임시: 음량 0.03마다 한 칸
  return (
    <span className="absolute bottom-2 right-2 flex items-center gap-2 rounded bg-black/60 px-2 py-1 text-xs" data-testid="mic-meter">
      <span>🎤</span>
      <span className="flex items-end gap-0.5">
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={`w-1 rounded-sm ${i <= bars ? "bg-green-400" : "bg-room-3"}`} style={{ height: `${4 + i * 2}px` }} />
        ))}
      </span>
      <span className={rms === null ? "text-red-400" : heard ? "text-green-400" : "text-room-muted"}>
        {rms === null ? "마이크 없음" : heard ? "소리 들림" : "조용함"}
      </span>
    </span>
  );
}

function Bar({ pct }: { pct: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-room-3">
      <div className="h-full rounded-full bg-avatar transition-[width] duration-100" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

function Modal({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 flex items-center justify-center bg-black/60">
      <div className="card max-w-md space-y-3 text-slate-900">{children}</div>
    </div>
  );
}
