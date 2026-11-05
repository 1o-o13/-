import { describe, expect, it } from "vitest";
import { LIVE_LIMIT_MS, LivenessTracker } from "./liveness";

const s = (t: number, yaw: number, blink = 0, faces = 1) => ({ t, faces, yaw, blink });

describe("라이브니스 (11/12)", () => {
  it("돌리기 → 정면 → 깜빡이기 순서면 통과", () => {
    const l = new LivenessTracker();
    expect(l.push(s(0, 0))).toBe("turn");
    expect(l.push(s(500, 0.4))).toBe("center");
    expect(l.push(s(1000, 0.02))).toBe("blink");
    expect(l.push(s(1500, 0.02, 0.8))).toBe("pass");
  });
  it("사진처럼 움직임이 없으면 시간 초과로 실패", () => {
    const l = new LivenessTracker();
    for (let t = 0; t <= LIVE_LIMIT_MS + 500; t += 500) l.push(s(t, 0.01, 0.05));
    expect(l.step).toBe("fail");
  });
  it("돌리지 않고 깜빡이기만 하면 통과 아님", () => {
    const l = new LivenessTracker();
    l.push(s(0, 0, 0.9));
    expect(l.step).toBe("turn");
  });
  it("다른 사람이 계속 같이 보이면 실패, 잠깐 놓친 얼굴은 기다림", () => {
    const l = new LivenessTracker();
    l.push(s(0, 0, 0, 0));
    expect(l.step).toBe("turn");
    [1, 2, 3].forEach((i) => l.push(s(i * 300, 0.4, 0, 2)));
    expect(l.step).toBe("fail");
  });
});
