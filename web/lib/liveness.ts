/** 라이브니스 확인 (11/12): 시작 전 본인 확인 때 1회. 사진·화면 속 영상으로 대리 응시하는 것을 막는다.
 *  순서: ① 고개를 옆으로 돌렸다가 ② 다시 정면 ③ 눈 깜빡이기. 그동안 얼굴은 1명이어야 하고, 제한 시간 안에 끝내야 통과.
 *  브라우저 안에서만 판단하고 결과(통과·실패)만 서버로 보낸다 (영상은 보내지 않음) */
export const LIVE_TURN = 0.25;   // 임시: 고개 좌우(yaw)가 이보다 크면 돌린 것
export const LIVE_CENTER = 0.1;  // 임시: 이보다 작으면 정면
export const LIVE_BLINK = 0.5;   // 임시: 눈 감음 계수(eyeBlink)가 이보다 크면 깜빡임
export const LIVE_LIMIT_MS = 20_000;

export type LiveSample = { t: number; faces: number; yaw: number; blink: number };
export type LiveStep = "turn" | "center" | "blink" | "pass" | "fail";

export const LIVE_TEXT: Record<LiveStep, string> = {
  turn: "고개를 천천히 왼쪽이나 오른쪽으로 돌려 주세요",
  center: "다시 화면 정면을 봐 주세요",
  blink: "눈을 한 번 감았다 떠 주세요",
  pass: "확인했습니다",
  fail: "확인하지 못했습니다",
};

export class LivenessTracker {
  step: LiveStep = "turn";
  private start: number | null = null;
  private many = 0;

  push(s: LiveSample): LiveStep {
    if (this.step === "pass" || this.step === "fail") return this.step;
    this.start ??= s.t;
    if (s.t - this.start > LIVE_LIMIT_MS) return (this.step = "fail");
    if (s.faces > 1 && ++this.many >= 3) return (this.step = "fail");      // 다른 사람이 계속 같이 보이면 실패
    if (s.faces !== 1) return this.step;                                   // 잠깐 얼굴을 놓친 건 기다림
    if (this.step === "turn" && Math.abs(s.yaw) > LIVE_TURN) this.step = "center";
    else if (this.step === "center" && Math.abs(s.yaw) < LIVE_CENTER) this.step = "blink";
    else if (this.step === "blink" && s.blink > LIVE_BLINK) this.step = "pass";
    return this.step;
  }
}
