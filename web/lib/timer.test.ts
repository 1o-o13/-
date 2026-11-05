import { describe, expect, it } from "vitest";
import { left, mmss, recordDeadline } from "./timer";

describe("타이머", () => {
  it("남은 초를 mm:ss로, 소수는 올림", () => {
    expect(mmss(132)).toBe("02:12");
    expect(mmss(14.2)).toBe("00:15");
    expect(mmss(180)).toBe("03:00");
    expect(mmss(-3)).toBe("00:00");
  });

  it("남은 시간은 마감에서 지금을 뺀 값, 0 아래로 안 감", () => {
    expect(left(10_000, 4_000)).toBe(6);
    expect(left(10_000, 12_000)).toBe(0);
  });

  it("생각 단계에서 받으면 녹음 끝 = 생각 남은 시간 + 답변 최대", () => {
    expect(recordDeadline("think", 20, 180, 1_000)).toBe(1_000 + 200_000);
  });

  it("녹음 단계에서 받으면(재접속) 남은 시간 그대로", () => {
    expect(recordDeadline("record", 95.5, 180, 1_000)).toBe(1_000 + 95_500);
  });
});
