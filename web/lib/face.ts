// 얼굴 감지 (MediaPipe FaceLandmarker, 브라우저 안에서만). 결과 수만 쓰고 영상은 보내지 않는다.
import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

export const FACE_MODEL = "/models/face_landmarker.task";
export const GAZE_OUT = 0.6; // 임시: 눈동자 방향 blendshape가 이 값을 넘으면 시선이 화면 밖 (실측 후 조정)
export const TURN_OUT = 0.3; // 임시: 고개 좌우 (코 위치 / 눈 사이 거리)가 이만큼 넘으면 화면 밖
export const PITCH_UP = 0.25; // 임시: 고개 위아래 (코 높이 / 눈~턱 거리)가 이 아래면 위를, PITCH_DOWN 위면 아래를 봄
export const PITCH_DOWN = 0.7;
const MIN_CONF = 0.3; // 임시: 얼굴 찾기·유지 기준 (기본 0.5면 뒤쪽 작은 얼굴을 놓침)

/** 모델 파일(public/models/face_landmarker.task)이 없으면 null → 얼굴 감지 없이 진행 */
export async function loadFace(): Promise<FaceLandmarker | null> {
  const ok = await fetch(FACE_MODEL, { method: "HEAD" }).then((r) => r.ok, () => false);
  if (!ok) {
    console.warn(`${FACE_MODEL} 없음: 얼굴 감지 꺼짐`);
    return null;
  }
  quietMediaPipeInfo();
  const files = await FilesetResolver.forVisionTasks("/mediapipe");
  return FaceLandmarker.createFromOptions(files, {
    baseOptions: { modelAssetPath: FACE_MODEL },
    runningMode: "VIDEO",
    numFaces: 3, // 2명 이상이면 '여러 명'. 한 명 더 찾아도 판정은 같고, 뒤쪽 사람이 앞사람에 가려져도 놓치지 않게
    minFaceDetectionConfidence: MIN_CONF,
    minFacePresenceConfidence: MIN_CONF,
    outputFaceBlendshapes: true,
  });
}

/** MediaPipe(wasm)는 "INFO: Created TensorFlow Lite XNNPACK delegate…" 같은 안내를 console.error로 찍어서
 *  개발 화면 왼쪽 아래에 이슈로 잡힌다. 'INFO:'로 시작하는 줄만 걸러 내고 진짜 오류는 그대로 둔다 */
let quieted = false;
function quietMediaPipeInfo() {
  if (quieted) return;
  quieted = true;
  const original = console.error;
  console.error = (...args: unknown[]) => {
    if (typeof args[0] === "string" && args[0].startsWith("INFO:")) return;
    original(...args);
  };
}

/** 자동 시험(E2E) 전용: Playwright가 시험용 Chrome에 window.__E2E_FAKE_FACE__를 심었을 때만 '얼굴 1명 있음'으로 본다.
 *  가짜 카메라 영상에는 얼굴이 없기 때문. 개발 서버에서만 통하고, 직접 쓰는 Chrome에는 이 표시가 없다 */
export function e2eFakeFace(): boolean {
  return process.env.NODE_ENV === "development" && (window as { __E2E_FAKE_FACE__?: boolean }).__E2E_FAKE_FACE__ === true;
}

type Point = { x: number; y: number };
type Shape = { categoryName: string; score: number };

/** 고개 방향 (얼굴 점 33·263 눈 바깥, 1 코끝, 152 턱). yaw: 0 정면, ± 좌우 / pitch: 0.4~0.5 정면 */
export function headPose(lm: Point[]): { yaw: number; pitch: number } {
  const [re, le, nose, chin] = [lm[33], lm[263], lm[1], lm[152]];
  const eyeY = (re.y + le.y) / 2;
  return { yaw: (nose.x - (re.x + le.x) / 2) / Math.abs(le.x - re.x), pitch: (nose.y - eyeY) / (chin.y - eyeY) };
}

/** 시선이 화면 밖인지: 눈동자 방향(eyeLookOut·Up·Down)이 기준을 넘거나, 고개를 크게 돌리거나 숙이면 */
export function isGazeAway(shapes: Shape[], lm?: Point[]): boolean {
  if (shapes.some((c) => /^eyeLook(Out|Up|Down)/.test(c.categoryName) && c.score > GAZE_OUT)) return true;
  if (!lm) return false;
  const { yaw, pitch } = headPose(lm);
  return Math.abs(yaw) > TURN_OUT || pitch < PITCH_UP || pitch > PITCH_DOWN;
}

/** 표정 표기 (11/10, 점수에 쓰지 않고 관리자 리포트에 표기만). 임시 기준: 표정 계수(blendshape) 평균 */
export type Expression = "미소" | "긴장" | "놀람" | "무표정" | "시선 아래" | "얼굴 없음";
export function expression(shapes: Shape[]): { label: Expression; value: Record<string, number> } {
  const g = (...names: string[]) => names.reduce((a, n) => a + (shapes.find((c) => c.categoryName === n)?.score ?? 0), 0) / names.length;
  const v = { smile: g("mouthSmileLeft", "mouthSmileRight"), brow: g("browDownLeft", "browDownRight"), press: g("mouthPressLeft", "mouthPressRight"),
    up: g("browInnerUp"), jaw: g("jawOpen"), down: g("eyeLookDownLeft", "eyeLookDownRight") };
  const value = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, Math.round(x * 100) / 100]));
  if (!shapes.length) return { label: "얼굴 없음", value };
  if (v.smile > 0.4) return { label: "미소", value };
  if (v.up > 0.5 && v.jaw > 0.3) return { label: "놀람", value };
  if (v.brow > 0.4 || v.press > 0.4) return { label: "긴장", value };
  if (v.down > 0.5) return { label: "시선 아래", value };
  return { label: "무표정", value };
}

export function look(fl: FaceLandmarker, video: HTMLVideoElement, t: number): { faces: number; gazeAway: boolean; expr: ReturnType<typeof expression> } {
  const r = fl.detectForVideo(video, t);
  const shapes = r.faceBlendshapes[0]?.categories ?? [];
  return { faces: r.faceLandmarks.length, gazeAway: isGazeAway(shapes, r.faceLandmarks[0]), expr: expression(shapes) };
}

/** 라이브니스용 한 장면: 얼굴 수·고개 좌우(yaw)·눈 감음 계수(양쪽 중 큰 값) (11/12, lib/liveness.ts) */
export function liveSignal(fl: FaceLandmarker, video: HTMLVideoElement, t: number): { faces: number; yaw: number; blink: number } {
  const r = fl.detectForVideo(video, t);
  const shapes = r.faceBlendshapes[0]?.categories ?? [];
  const blink = Math.max(0, ...shapes.filter((c) => c.categoryName === "eyeBlinkLeft" || c.categoryName === "eyeBlinkRight").map((c) => c.score));
  return { faces: r.faceLandmarks.length, yaw: r.faceLandmarks[0] ? headPose(r.faceLandmarks[0]).yaw : 0, blink };
}

/** 녹음 중 표정 표본(0.5초마다) → 같은 표기가 이어진 구간으로 묶는다 (ms, 녹음 시작 기준). 1초 미만 구간은 앞 구간에 붙인다 */
export type FaceSeg = { t0: number; t1: number; label: Expression; value: Record<string, number> };
export function segments(samples: { t: number; label: Expression; value: Record<string, number> }[]): FaceSeg[] {
  const out: FaceSeg[] = [];
  for (const s of samples) {
    const last = out.at(-1);
    if (last && (last.label === s.label || s.t - last.t0 < 1000)) last.t1 = s.t;
    else out.push({ t0: s.t, t1: s.t, label: s.label, value: s.value });
  }
  return out.slice(0, 200);
}
