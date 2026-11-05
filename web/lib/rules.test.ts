import { describe, expect, it } from "vitest";
import { check, formatPhone } from "./rules";

describe("가입 입력 틀", () => {
  it("이름: 한글 2~17자 또는 영문", () => {
    for (const ok of ["김하", "김하늘", "가".repeat(17), "Haneul Kim", "Jo"]) expect(check.name(ok)).toBe("");
    for (const bad of ["김", "가".repeat(18), "김 하늘", "김Haneul", "kim1", " Kim", "Kim  Lee", "ㄱㄴ"]) expect(check.name(bad)).not.toBe("");
  });

  it("이메일: 실제 쓰는 메일 서비스만", () => {
    for (const ok of ["haneul.kim@naver.com", "a_b+1@gmail.com", "X@Daum.net"]) expect(check.email(ok)).toBe("");
    for (const bad of ["a@test.local", "a@example.com", "a@naver.co", "a@gmail.com.evil.com", "@naver.com", "a b@naver.com"]) expect(check.email(bad)).not.toBe("");
  });

  it("휴대폰: 국내 앞 3자리-4자리-4자리", () => {
    for (const ok of ["010-1234-5678", "011-1234-5678", "019-0000-0000"]) expect(check.phone(ok)).toBe("");
    for (const bad of ["012345678989", "012-3456-7898", "010-123-4567", "01012345678", "020-1234-5678", "010-1234-56789"]) expect(check.phone(bad)).not.toBe("");
  });

  it("비밀번호: 영문·숫자·특수문자 포함 8~13자", () => {
    for (const ok of ["Test1234!", "a1!aaaaa", "Abcdefgh12#$%"]) expect(check.password(ok)).toBe("");
    for (const bad of ["Test1234", "test!!!!", "12345678!", "a1!aaaa", "Abcdefgh123#$%", "Test 1234!"]) expect(check.password(bad)).not.toBe("");
  });

  it("휴대폰 번호는 숫자만 받아 하이픈을 넣는다", () => {
    expect(formatPhone("01012345678")).toBe("010-1234-5678");
    expect(formatPhone("012345678989")).toBe("012-3456-7898"); // 11자리에서 자르고, 앞 3자리 틀에서 걸러짐
    expect(formatPhone("010-12")).toBe("010-12");
  });
});
