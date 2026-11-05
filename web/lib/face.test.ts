import { describe, expect, it } from "vitest";
import { headPose, isGazeAway } from "./face";

/** 얼굴 점 4개만 채운 가짜 랜드마크: 눈 바깥(33·263), 코끝(1), 턱(152) */
function face(noseX: number, noseY: number) {
  const lm = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }));
  lm[33] = { x: 0.4, y: 0.4 };
  lm[263] = { x: 0.6, y: 0.4 };
  lm[1] = { x: noseX, y: noseY };
  lm[152] = { x: 0.5, y: 0.7 };
  return lm;
}

describe("시선·고개 방향", () => {
  it("정면이면 화면 안", () => {
    const lm = face(0.5, 0.53);
    expect(headPose(lm).yaw).toBeCloseTo(0);
    expect(isGazeAway([], lm)).toBe(false);
  });

  it("눈동자만 옆으로 가도 화면 밖", () => {
    expect(isGazeAway([{ categoryName: "eyeLookOutLeft", score: 0.8 }], face(0.5, 0.53))).toBe(true);
    expect(isGazeAway([{ categoryName: "eyeLookInLeft", score: 0.9 }], face(0.5, 0.53))).toBe(false); // 안쪽(코 쪽)은 화면 안
  });

  it("고개를 크게 돌리면 눈동자가 정면이어도 화면 밖", () => {
    expect(isGazeAway([], face(0.58, 0.53))).toBe(true); // yaw 0.4
    expect(isGazeAway([], face(0.54, 0.53))).toBe(false); // yaw 0.2는 허용
  });

  it("고개를 숙이거나(휴대폰) 젖히면 화면 밖", () => {
    expect(isGazeAway([], face(0.5, 0.65))).toBe(true); // pitch 0.83
    expect(isGazeAway([], face(0.5, 0.44))).toBe(true); // pitch 0.13
  });
});
