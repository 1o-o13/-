// 녹음 중 침묵 감지 (순수 로직). 음량을 시간 순서대로 넣으면 자동 제출 여부와 침묵 비율을 알려 준다.
export const SILENCE_LEVEL = 0.02;   // 임시: 이 음량(RMS 0~1) 아래면 침묵 (실측 후 조정)
export const PAUSE_MS = 3000;        // 3초 이상 이어진 침묵만 침묵 비율에 넣는다 (interview_answer.silence_ratio)

export class SilenceTracker {
  private start = -1;
  private last = -1;
  private quietFrom = -1;        // 지금 이어지는 침묵의 시작 (-1 = 소리 남)
  private longQuiet = 0;         // 끝난 3초 이상 침묵의 합
  private voicedMs = 0;          // 소리가 난 시간의 합 (말을 했는지)
  private prev = -1;

  constructor(private skipMs: number, private level = SILENCE_LEVEL) {}

  /** 음량 하나를 넣는다. 침묵이 skipMs 이상 이어지면 true (자동 제출) */
  push(rms: number, t: number): boolean {
    if (this.start < 0) this.start = t;
    if (this.prev >= 0 && rms >= this.level) this.voicedMs += t - this.prev;
    this.prev = t;
    this.last = t;
    if (rms < this.level) {
      if (this.quietFrom < 0) this.quietFrom = t;
      return t - this.quietFrom >= this.skipMs;
    }
    if (this.quietFrom >= 0 && t - this.quietFrom >= PAUSE_MS) this.longQuiet += t - this.quietFrom;
    this.quietFrom = -1;
    return false;
  }

  /** 녹음 중 소리가 난 시간(초). 거의 0이면 말을 안 한 것 → 서버가 무응답으로 본다 */
  voicedSec(): number {
    return this.voicedMs / 1000;
  }

  /** 지금 이어지는 침묵 길이(ms). 소리가 나는 중이면 0 (화면의 '침묵 N초' 표시) */
  quietFor(t: number): number {
    return this.quietFrom < 0 ? 0 : t - this.quietFrom;
  }

  /** 3초 이상 침묵이 전체 녹음에서 차지한 비율 (0~1) */
  ratio(): number {
    const total = this.last - this.start;
    if (total <= 0) return 0;
    const open = this.quietFrom >= 0 && this.last - this.quietFrom >= PAUSE_MS ? this.last - this.quietFrom : 0;
    return Math.min(1, (this.longQuiet + open) / total);
  }
}
