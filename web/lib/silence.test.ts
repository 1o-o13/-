import { describe, expect, it } from "vitest";
import { SilenceTracker } from "./silence";

/** 100ms마다 음량을 넣는다. levels[i] = i번째 0.1초의 음량. 자동 제출된 시각(ms)을 돌려준다 */
function feed(t: SilenceTracker, levels: number[]): number | null {
  for (let i = 0; i < levels.length; i++) if (t.push(levels[i], i * 100)) return i * 100;
  return null;
}
const loud = (sec: number) => Array(sec * 10).fill(0.2);
const quiet = (sec: number) => Array(sec * 10).fill(0.001);

describe("침묵 감지", () => {
  it("5초 침묵이 이어지면 자동 제출", () => {
    expect(feed(new SilenceTracker(5000), [...loud(3), ...quiet(6)])).toBe(8000); // 3초 말한 뒤 5초 침묵
  });

  it("말을 시작하지 않아도 5초 침묵이면 자동 제출", () => {
    expect(feed(new SilenceTracker(5000), quiet(6))).toBe(5000);
  });

  it("중간에 소리가 나면 침묵 시간이 처음부터 다시", () => {
    expect(feed(new SilenceTracker(5000), [...quiet(4), ...loud(1), ...quiet(4), ...loud(1)])).toBeNull();
  });

  it("설정의 침묵 넘김 초를 따른다", () => {
    expect(feed(new SilenceTracker(3000), [...loud(1), ...quiet(4)])).toBe(4000);
  });

  it("침묵 비율은 3초 이상 이어진 침묵만 센다", () => {
    const t = new SilenceTracker(5000);
    feed(t, [...loud(2), ...quiet(4), ...loud(2), ...quiet(2), ...loud(1)]); // 4초 침묵만 셈, 2초 침묵은 빼고
    expect(t.ratio()).toBeCloseTo(4000 / 10900, 2);
  });

  it("지금 이어지는 침묵 길이 (소리가 나면 0으로)", () => {
    const t = new SilenceTracker(5000);
    feed(t, [...loud(1), ...quiet(3)]); // 마지막 넣은 시각 3900ms, 침묵 시작 1000ms
    expect(t.quietFor(3900)).toBe(2900);
    t.push(0.3, 4000);
    expect(t.quietFor(4000)).toBe(0);
  });

  it("소리가 난 시간을 잰다 (말 안 하고 바로 '답변 끝'을 눌러도 알 수 있게)", () => {
    const t = new SilenceTracker(5000);
    feed(t, quiet(2));
    expect(t.voicedSec()).toBe(0);
    const u = new SilenceTracker(5000);
    feed(u, [...quiet(1), ...loud(2), ...quiet(1)]);
    expect(u.voicedSec()).toBeCloseTo(2, 1);
  });

  it("침묵 비율은 0~1", () => {
    const t = new SilenceTracker(5000);
    feed(t, quiet(6));
    expect(t.ratio()).toBe(1);
    expect(new SilenceTracker(5000).ratio()).toBe(0);
  });
});
