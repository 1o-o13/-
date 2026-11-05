import { describe, expect, it } from "vitest";
import { EDIT_MAX, editRatio } from "./edit";

describe("답변 인식 글 수정 비율", () => {
  it("같으면 0, 띄어쓰기는 세지 않음", () => {
    expect(editRatio("레디스 캐시를 썼습니다", "레디스 캐시를 썼습니다")).toBe(0);
    expect(editRatio("레디스캐시를 썼습니다", "레디스 캐시를  썼습니다")).toBe(0);
  });
  it("인식 오류 몇 글자 고침은 허용 범위", () => {
    expect(editRatio("레디스 캐쉬로 응답 시간을 줄였습니다", "레디스 캐시로 응답 시간을 줄였습니다")).toBeLessThan(EDIT_MAX);
  });
  it("다른 답을 써 넣으면 범위를 넘음", () => {
    expect(editRatio("잘 모르겠습니다", "인덱스를 걸고 실행 계획을 확인해 쿼리를 열 배 빠르게 만들었습니다")).toBeGreaterThan(EDIT_MAX);
  });
});
