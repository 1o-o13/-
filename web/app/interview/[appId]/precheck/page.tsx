"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { ContactButton } from "@/lib/brand";
import { e2eFakeFace, liveSignal, loadFace, look } from "@/lib/face";
import { LIVE_TEXT, type LiveStep, LivenessTracker } from "@/lib/liveness";
import { useGuide } from "@/lib/guide";
import { levelMeter, openMedia, snapshot } from "@/lib/media";
import { SILENCE_LEVEL } from "@/lib/silence";

type Check = { camera: boolean; mic: boolean; chrome: boolean; online: boolean; single_face: boolean };
const CONSENTS = [
  ["consent_voice", "음성 녹음 (필수)", "텍스트 변환 후 삭제"],
  ["consent_ai", "AI 평가 활용 (필수)", "AI는 질문 생성·답변 정리를 돕고 합격 결정은 담당관이 함 · 면접 기록은 최종 발표 후 180일 뒤 파기"],
  ["consent_overseas", "국외 AI 서비스 전송 (필수)", "거부하면 응시할 수 없음 · 사내 보안 문서가 든 처리는 국외로 보내지 않음"],
  ["consent_face", "얼굴 생체정보 대조 (선택)", "사진 저장 안 함 · 거부하면 담당자가 직접 본인 확인"],
] as const;

// CAN-009 사전 점검·본인 확인·동의
export default function Precheck() {
  const { appId, guide, err: gErr, router } = useGuide();
  const video = useRef<HTMLVideoElement>(null);
  const [check, setCheck] = useState<Check>({ camera: false, mic: false, chrome: false, online: false, single_face: false });
  const [level, setLevel] = useState(0);
  const [consent, setConsent] = useState({ consent_voice: false, consent_face: false, consent_ai: false, consent_overseas: false });
  const [saved, setSaved] = useState(false);
  type IdResult = { done: boolean; result: "match" | "retry" | "no_face" | "failed" | "skipped"; left?: number };
  const [id, setId] = useState<IdResult | null>(null); // 본인 확인 결과 (촬영하자마자 서버가 알려 줌)
  const [shooting, setShooting] = useState(false);
  const live = useRef<LivenessTracker | null>(null);      // 라이브니스 확인 중 (11/12, 본인 확인 일치 뒤 1회)
  const [liveStep, setLiveStep] = useState<LiveStep | null>(null);
  const identityOk = (id?.result === "match" && (liveStep === "pass" || liveStep === "fail")) || id?.result === "skipped";   // 일치하면 라이브니스까지 (실패해도 막지 않고 담당관 확인) // 일치해야만 다음 단계 (얼굴 대조 거부는 담당자 확인 경로)
  const [err, setErr] = useState("");
  const [photo, setPhoto] = useState<boolean | null>(null); // 증명사진 (실제 얼굴 대조의 기준). null = 안내 정보 그대로
  const [denied, setDenied] = useState(false); // 카메라·마이크 권한 거부 또는 장치 없음 (C9-02)
  const [faces, setFaces] = useState<number | null>(null); // 지금 화면 속 얼굴 수 (null = 감지 못 함)
  useEffect(() => {                                             // 증명사진과 일치하면 바로 움직임 확인 시작
    if (id?.result === "match" && liveStep === null) {
      live.current = new LivenessTracker();
      setLiveStep("turn");
    }
  }, [id, liveStep]);

  useEffect(() => {
    let stream: MediaStream | undefined;
    let meter: ReturnType<typeof levelMeter> | undefined;
    let timer = 0;
    let alive = true;
    (async () => {
      stream = await openMedia().catch(() => undefined);
      if (!alive) return stream?.getTracks().forEach((t) => t.stop()); // 화면이 먼저 닫혔으면 카메라를 바로 끈다
      const chrome = /Chrome\//.test(navigator.userAgent);
      if (!stream) setDenied(true);
      if (!stream || !alive) return setCheck((c) => ({ ...c, chrome, online: navigator.onLine }));
      if (video.current) video.current.srcObject = stream;
      meter = levelMeter(stream);
      const face = await loadFace().catch(() => null);
      const fake = e2eFakeFace();
      timer = window.setInterval(() => {
        const rms = meter!.read();
        setLevel(rms);
        const v = video.current!;
        const ready = v.readyState >= 2;
        // 실제 얼굴이 1명 보여야 통과. 감지 모델을 못 쓰면 통과시키지 않는다 (자동 시험만 예외)
        const now = performance.now();
        if (live.current && (fake || (face && ready))) {          // 라이브니스: 자동 시험은 가짜 얼굴이라 바로 통과
          const sig = fake ? null : liveSignal(face!, v, now);
          const step = fake ? (live.current.step = "pass") : live.current.push({ t: now, ...sig! });
          setLiveStep(step);
          if (step === "pass" || step === "fail") {
            live.current = null;
            api(`/interview/applications/${appId}/liveness`, { method: "POST", json: { passed: step === "pass" } }).catch(() => undefined);
          }
          return;
        }
        const n = fake ? 1 : face && ready ? look(face, v, now).faces : null;
        setFaces(n);
        setCheck((c) => ({ camera: ready, mic: c.mic || rms > SILENCE_LEVEL, chrome, online: navigator.onLine, single_face: ready && n === 1 }));
      }, 300);
    })();
    return () => {
      alive = false;
      clearInterval(timer);
      meter?.close();
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const devicesOk = Object.values(check).every(Boolean);
  const consentOk = consent.consent_voice && consent.consent_ai && consent.consent_overseas;   // 얼굴 동의는 별도 (거부 → 사람 확인)

  async function save() {
    setErr("");
    try {
      // 임시: 업로드 속도는 브라우저 추정 대역폭(downlink)으로 기록 (실측 방법은 단계 6에서 정함)
      const mbps = (navigator as Navigator & { connection?: { downlink?: number } }).connection?.downlink ?? 0;
      await api(`/interview/applications/${appId}/precheck`, {
        method: "POST",
        json: { chrome: check.chrome, camera: check.camera, mic: check.mic, upload_mbps: mbps, single_face: check.single_face, ...consent },
      });
      setSaved(true);
      if (!consent.consent_face) setId({ done: true, result: "skipped" });   // 얼굴 대조 거부: 촬영 없이 담당자 확인 경로
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const needPhoto = !!guide?.face_real && consent.consent_face && !(photo ?? guide?.has_photo);

  async function uploadPhoto(file: File | undefined) {
    if (!file) return;
    setErr("");
    const body = new FormData();
    body.append("photo", file);
    try {
      await api(`/interview/applications/${appId}/photo`, { method: "POST", body });
      setPhoto(true);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function shoot() {
    setErr("");
    setShooting(true);
    const body = new FormData();
    body.append("frame", await snapshot(video.current!), "frame.jpg");
    try {
      setId(await api<IdResult>(`/interview/applications/${appId}/identity`, { method: "POST", body }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setShooting(false);
    }
  }

  if (gErr) return <p className="err">{gErr}</p>;
  if (!guide) return <p>불러오는 중…</p>;
  const dot = (ok: boolean, device = false) =>
    ok ? <span className="text-green-600">● 정상</span> : device && denied ? <span className="text-red-600">● 실패</span> : <span className="text-slate-400">● 확인 중</span>;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">사전 점검 · {guide.title}</h1>
        <span className="flex-1" />
        <span className="text-xs text-slate-500">장치·본인 확인이 안 되면</span>
        <ContactButton postingId={guide.posting_id} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="card space-y-2">
          <h2 className="font-semibold">1. 장치 점검</h2>
          <p>카메라 {dot(check.camera, true)}</p>
          <p className="flex items-center gap-2">
            마이크 {dot(check.mic, true)}
            <span className="inline-block h-2 w-32 rounded bg-slate-200">
              <span className="block h-2 rounded bg-green-500" style={{ width: `${Math.min(100, level * 400)}%` }} />
            </span>
          </p>
          {denied ? (
            <p className="err">카메라·마이크를 쓸 수 없습니다. 브라우저 주소창의 권한을 허용하고 새로고침해 주세요.</p>
          ) : (
            <p className="text-xs text-slate-500">마이크에 대고 말해 보세요.</p>
          )}
          <p>브라우저(Chrome) {dot(check.chrome)} · 네트워크 {dot(check.online)}</p>
          <p>
            화면 안 한 명 {dot(check.single_face, true)}
            {!check.single_face && faces !== null && <span className="ml-2 text-xs text-slate-500">{faces === 0 ? "얼굴이 보이지 않습니다" : `얼굴 ${faces}명이 보입니다`}</span>}
          </p>
        </div>
        <div className="card space-y-2">
          <h2 className="font-semibold">2. 동의</h2>
          {/* 전체 동의: 필수 3개 + 선택(해외 전송)까지 한 번에. 선택 항목은 아래에서 따로 해제할 수 있다 */}
          <label className="flex items-center gap-2 rounded-md bg-slate-50 p-2 font-medium">
            <input
              type="checkbox"
              name="consent_all"
              checked={Object.values(consent).every(Boolean)}
              disabled={saved}
              onChange={(e) => setConsent({ consent_voice: e.target.checked, consent_face: e.target.checked, consent_ai: e.target.checked, consent_overseas: e.target.checked })}
            />
            전체 동의 <span className="text-xs font-normal text-slate-500">(선택 항목 포함)</span>
          </label>
          {CONSENTS.map(([k, label, note]) => (
            <label key={k} className="flex items-start gap-2">
              <input type="checkbox" name={k} checked={consent[k]} disabled={saved} onChange={(e) => setConsent({ ...consent, [k]: e.target.checked })} />
              <span>
                {label} <span className="text-xs text-slate-500">{note}</span>
              </span>
            </label>
          ))}
          <button className="btn" disabled={!devicesOk || !consentOk || saved} onClick={save}>
            {saved ? "점검·동의 완료" : "점검·동의 저장"}
          </button>
        </div>
      </div>
      <div className="card space-y-2">
        <h2 className="font-semibold">3. 본인 확인</h2>
        <video ref={video} autoPlay muted playsInline className="h-48 w-64 rounded bg-black" />
        <p className="text-sm">얼굴을 화면 가운데에 맞추고 촬영해 주세요. 사진은 저장하지 않습니다.</p>
        {shooting && <p className="text-sm text-slate-600">증명사진과 대조하는 중…</p>}
        {!shooting && id && (
          <p data-testid="identity-result" className={`rounded p-2 text-sm font-medium ${identityOk ? "bg-green-50 text-green-800" : id.result === "failed" ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-900"}`}>
            {id.result === "match" && "✓ 본인 확인 완료 — 증명사진과 같은 사람입니다. 다음으로 넘어가세요."}
            {id.result === "skipped" && "얼굴 대조에 동의하지 않아 촬영하지 않았습니다. 담당자가 면접 기록으로 본인 여부를 확인합니다."}
            {id.result === "retry" && `✗ 증명사진과 일치하지 않습니다. 정면을 보고 밝은 곳에서 다시 촬영해 주세요. (남은 재촬영 ${id.left}번)`}
            {id.result === "no_face" && "얼굴을 찾지 못했습니다. 얼굴이 화면 가운데에 크게 나오게 다시 촬영해 주세요. (횟수에 넣지 않음)"}
            {id.result === "failed" && "✗ 본인 확인에 실패해 응시할 수 없습니다. 위 '문의하기'의 담당자 연락처로 문의해 주세요 (회사 방문 면접 안내)."}
          </p>
        )}
        {id?.result === "match" && liveStep !== "pass" && liveStep !== "fail" && (
          <div className="rounded border border-sky-200 bg-sky-50 p-2 text-sm text-sky-900" data-testid="liveness">
            <b>움직임 확인</b> (사진·영상으로 대신 응시하는 것을 막기 위한 확인, 영상은 저장하지 않습니다)
            <p className="mt-1 text-base font-semibold">{LIVE_TEXT[liveStep ?? "turn"]}</p>
          </div>
        )}
        {(liveStep === "pass" || liveStep === "fail") && id?.result === "match" && <p className="text-sm text-green-700">움직임 확인을 마쳤습니다.</p>}
        {saved && !identityOk && !check.single_face && <p className="text-sm text-dawn-500">얼굴 1명이 화면에 보여야 촬영할 수 있습니다.</p>}
        {saved && !consent.consent_face && <p className="text-sm text-dawn-500">얼굴 대조에 동의하지 않아 촬영하지 않습니다. 담당자가 면접 기록으로 본인 여부를 직접 확인합니다.</p>}
        {needPhoto && (
          <label className="block rounded bg-amber-50 p-2 text-sm text-amber-900">
            본인 확인은 증명사진과 지금 얼굴을 대조합니다. 증명사진을 먼저 올려 주세요 (JPEG·PNG, 5MB까지).
            <input type="file" accept="image/jpeg,image/png" name="photo" className="mt-1 block text-xs" onChange={(e) => uploadPhoto(e.target.files?.[0])} />
          </label>
        )}
        {photo && <p className="text-sm text-green-700">증명사진을 올렸습니다. 이제 촬영해 주세요.</p>}
        <button className="btn-line" disabled={!saved || id?.result === "failed" || id?.result === "skipped" || shooting || !check.single_face || needPhoto} onClick={shoot}>
          {id?.result === "match" ? "다시 확인" : id ? "재촬영" : "촬영"}
        </button>
      </div>
      {err && <p className="err">{err}</p>}
      <div className="flex justify-between">
        <button className="btn-line" onClick={() => router.push(`/interview/${appId}/guide`)}>이전</button>
        <button className="btn" disabled={!identityOk} onClick={() => router.push(`/interview/${appId}/${guide.coding_required && guide.coding_status !== "completed" ? "coding" : "ready"}`)}>
          {guide.coding_required && guide.coding_status !== "completed" ? "다음: 코딩 테스트" : "다음"}
        </button>
      </div>
    </div>
  );
}
