// 면접 시간 계산 (순수 함수). 서버 /state의 남은 초를 받은 시각 기준으로 줄여 간다.

/** 남은 초 → "02:12" */
export function mmss(sec: number): string {
  const s = Math.max(0, Math.ceil(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** 지금 남은 초. deadlineMs = 받은 시각 + 남은 초 */
export function left(deadlineMs: number, nowMs: number): number {
  return Math.max(0, (deadlineMs - nowMs) / 1000);
}

/** 녹음 끝 시각. 생각 단계에서 받았으면 생각 남은 시간 + 답변 최대, 녹음 단계에서 받았으면 남은 시간 그대로 */
export function recordDeadline(phase: "think" | "record", remainingSec: number, answerMaxSec: number, receivedMs: number): number {
  return receivedMs + (phase === "think" ? remainingSec + answerMaxSec : remainingSec) * 1000;
}
