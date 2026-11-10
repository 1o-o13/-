"use client";
// 개발용 카메라 점검 화면 (개발 서버에서만 열림). 면접 화면과 같은 감지 코드(lib/face·lib/proctor)를 실제 카메라로 눈으로 확인한다.
// 서버로 아무것도 보내지 않는다. 표정 수치는 확인용으로만 보여 주고 면접 판정·점수에는 쓰지 않는다 (NFR-IV-08).
import { DrawingUtils, FaceLandmarker } from "@mediapipe/tasks-vision";
import { useEffect, useRef, useState } from "react";
import { useDevTools } from "@/lib/quick";
import { GAZE_OUT, isGazeAway, loadFace } from "@/lib/face";
import { FACE_MS, FaceWatch, LeaveTracker, type ProctorEvent } from "@/lib/proctor";

type Shape = { categoryName: string; score: number };
type View = { faces: number; gaze: Shape[]; gazeAway: boolean; yaw: number; pitch: number; expr: Shape[]; fps: number };
type Log = { at: string; text: string };

const TURN = 0.15; // 임시: 고개 좌우 참고 기준 (코 위치 / 눈 사이 거리)
const RULE: Record<ProctorEvent["event_type"], string> = {
  face_missing: `얼굴 없음 ${FACE_MS / 1000}초 → 면접이면 경고 + 의심 건`,
  multi_face: "여러 명 → 면접이면 경고 + 의심 건",
  gaze_away: `시선 이탈 ${FACE_MS / 1000}초 → 면접이면 경고 + 의심 건`,
  tab_leave: "탭 이탈",
  window_blur: "창 이탈",
  upload_fail: "업로드 실패",
};

export default function CameraCheck() {
  const [mounted, setMounted] = useState(false); // 카메라·모델은 브라우저에서만 → 서버에서는 그리지 않는다
  const dev = useDevTools();
  useEffect(() => setMounted(true), []);
  if (!dev) return <p>개발용 화면입니다 (.env DEV_QUICK_LOGIN=1일 때만 열립니다).</p>;
  return mounted ? <Check /> : null;
}

function Check() {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [on, setOn] = useState(false);
  const [status, setStatus] = useState("");
  const [v, setV] = useState<View | null>(null);
  const [logs, setLogs] = useState<Log[]>([]);
  const add = (text: string) => setLogs((l) => [{ at: new Date().toLocaleTimeString("ko-KR"), text }, ...l].slice(0, 40));

  // 탭·창 이탈 (면접 화면과 같은 규칙: 1번째 경고, 2번째이거나 10초 이상이면 포기)
  useEffect(() => {
    if (!on) return;
    const leave = new LeaveTracker();
    const back = () => {
      const ev = leave.back(Date.now());
      if (!ev) return;
      const out = leave.count >= 2 || ev.duration_ms >= 10_000 ? "포기" : "경고";
      add(`${RULE[ev.event_type]} ${leave.count}번째 · ${(ev.duration_ms / 1000).toFixed(1)}초 → 면접이면 ${out}`);
    };
    const onHide = () => (document.hidden ? leave.leave("tab_leave", Date.now()) : back());
    const onBlur = () => leave.leave("window_blur", Date.now());
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", back);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", back);
    };
  }, [on]);

  // 카메라 → 얼굴 감지 → 그리기·수치·이벤트
  useEffect(() => {
    if (!on) return;
    let stream: MediaStream | undefined;
    let raf = 0;
    let alive = true;
    (async () => {
      setStatus("카메라 여는 중…");
      stream = await navigator.mediaDevices.getUserMedia({ video: true });
      video.current!.srcObject = stream;
      await video.current!.play();
      setStatus("얼굴 감지 모델 여는 중…");
      const fl = await loadFace();
      if (!fl) return setStatus("모델 파일이 없습니다 (public/models/face_landmarker.task)");
      setStatus("");
      const watch = new FaceWatch();
      const draw = new DrawingUtils(canvas.current!.getContext("2d")!);
      let last = 0;
      let frames = 0;
      let fpsAt = performance.now();
      let fps = 0;
      const loop = () => {
        if (!alive) return;
        raf = requestAnimationFrame(loop);
        const t = performance.now();
        if (t - last < 100) return; // 초당 10번
        last = t;
        const vd = video.current!;
        const c = canvas.current!;
        c.width = vd.videoWidth;
        c.height = vd.videoHeight;
        const r = fl.detectForVideo(vd, t);
        for (const lm of r.faceLandmarks) {
          draw.drawConnectors(lm, FaceLandmarker.FACE_LANDMARKS_CONTOURS, { color: "#22c55e", lineWidth: 1.5 });
          draw.drawConnectors(lm, FaceLandmarker.FACE_LANDMARKS_LEFT_IRIS, { color: "#ef4444", lineWidth: 2 });
          draw.drawConnectors(lm, FaceLandmarker.FACE_LANDMARKS_RIGHT_IRIS, { color: "#ef4444", lineWidth: 2 });
        }
        const shapes = r.faceBlendshapes[0]?.categories ?? [];
        const lm = r.faceLandmarks[0];
        let yaw = 0;
        let pitch = 0;
        if (lm) {
          const [re, le, nose, chin] = [lm[33], lm[263], lm[1], lm[152]];
          yaw = (nose.x - (re.x + le.x) / 2) / Math.abs(le.x - re.x);
          const eyeY = (re.y + le.y) / 2;
          pitch = (nose.y - eyeY) / (chin.y - eyeY);
        }
        const gazeAway = isGazeAway(shapes);
        for (const ev of watch.update(r.faceLandmarks.length, gazeAway, Date.now())) add(RULE[ev.event_type]);
        frames += 1;
        if (t - fpsAt >= 1000) {
          fps = frames;
          frames = 0;
          fpsAt = t;
        }
        setV({
          faces: r.faceLandmarks.length,
          gaze: shapes.filter((s) => s.categoryName.startsWith("eyeLook")),
          gazeAway,
          yaw,
          pitch,
          expr: shapes.filter((s) => !s.categoryName.startsWith("eyeLook") && s.categoryName !== "_neutral").sort((a, b) => b.score - a.score).slice(0, 8),
          fps,
        });
      };
      loop();
    })().catch((e) => setStatus(`카메라를 열 수 없습니다: ${e.message}`));
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [on]);

  const faceText = !v ? "-" : v.faces === 0 ? "얼굴 없음" : v.faces === 1 ? "1명 (정상)" : `${v.faces}명 (여러 명)`;
  const yawText = !v || v.faces === 0 ? "-" : v.yaw > TURN ? "왼쪽으로 돌림" : v.yaw < -TURN ? "오른쪽으로 돌림" : "정면";
  const pitchText = !v || v.faces === 0 ? "-" : v.pitch < 0.3 ? "위를 봄" : v.pitch > 0.6 ? "아래를 봄" : "정면";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">카메라 점검 (개발용)</h1>
        <button className="btn" onClick={() => (setOn(!on), setV(null))}>{on ? "끄기" : "카메라 켜기"}</button>
      </div>
      <p className="text-sm text-slate-600">영상은 이 브라우저 안에서만 처리하고 서버로 보내지 않습니다. 감독 이벤트도 기록만 하고 보내지 않습니다.</p>
      {status && <p className="text-sm">{status}</p>}
      <div className="grid grid-cols-5 gap-4">
        <div className="relative col-span-3">
          <video ref={video} muted playsInline className="w-full -scale-x-100 rounded bg-black" />
          <canvas ref={canvas} className="absolute inset-0 h-full w-full -scale-x-100" />
        </div>
        <div className="col-span-2 space-y-3 text-sm">
          <div className="card space-y-1">
            <p className="font-semibold">얼굴 인식</p>
            <p>얼굴 수: <b>{faceText}</b> {v && <span className="text-slate-500">· {v.fps} fps</span>}</p>
            <p>고개 좌우: {yawText} {v?.faces ? `(${v.yaw.toFixed(2)})` : ""} · 위아래: {pitchText} {v?.faces ? `(${v.pitch.toFixed(2)})` : ""}</p>
            <p className="text-xs text-slate-500">고개 방향은 참고용 (면접 감독에는 시선 값만 씀)</p>
          </div>
          <div className="card space-y-1">
            <p className="font-semibold">시선 (기준 {GAZE_OUT} 넘으면 화면 밖) → <span className={v?.gazeAway ? "text-red-600" : "text-green-700"}>{v ? (v.gazeAway ? "화면 밖" : "화면 안") : "-"}</span></p>
            {v?.gaze.map((s) => <Bar key={s.categoryName} s={s} warn={/Out|Up|Down/.test(s.categoryName)} />)}
          </div>
          <div className="card space-y-1">
            <p className="font-semibold">표정 수치 상위 8개</p>
            <p className="text-xs text-amber-700">확인용으로만 보여 줍니다. 면접 판정·점수·감독에는 쓰지 않습니다.</p>
            {v?.expr.map((s) => <Bar key={s.categoryName} s={s} />)}
          </div>
        </div>
      </div>
      <div className="card text-sm">
        <p className="font-semibold">감독 이벤트 (면접이면 서버로 보낼 내용)</p>
        {logs.length === 0 && <p className="text-slate-500">아직 없음 · 얼굴 가리기 5초, 두 명 비추기, 옆 보기 5초, 다른 탭 갔다 오기를 해 보세요.</p>}
        {logs.map((l, i) => <p key={i}>{l.at} · {l.text}</p>)}
      </div>
    </div>
  );
}

function Bar({ s, warn }: { s: Shape; warn?: boolean }) {
  const over = warn && s.score > GAZE_OUT;
  return (
    <div className="flex items-center gap-2">
      <span className="w-36 truncate">{s.categoryName}</span>
      <span className="h-2 flex-1 rounded bg-slate-200">
        <span className={`block h-2 rounded ${over ? "bg-red-500" : "bg-blue-500"}`} style={{ width: `${Math.round(s.score * 100)}%` }} />
      </span>
      <span className="w-10 text-right font-mono">{s.score.toFixed(2)}</span>
    </div>
  );
}
