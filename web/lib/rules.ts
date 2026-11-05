// 가입 입력 틀 (api/auth.py와 같은 규칙. 화면은 미리 알려 주기만 하고 서버가 최종 판단)
export const EMAIL_DOMAINS = ["naver.com", "gmail.com", "daum.net", "hanmail.net", "kakao.com", "nate.com", "outlook.com", "hotmail.com", "icloud.com", "yahoo.com"]; // 임시 목록

const NAME_KO = /^[가-힣]{2,17}$/;
const NAME_EN = /^(?=.{2,30}$)[A-Za-z]+(?: [A-Za-z]+)*$/; // 임시: 영문 2~30자
const EMAIL = new RegExp(`^[A-Za-z0-9._%+-]+@(${EMAIL_DOMAINS.map((d) => d.replace(/\./g, "\\.")).join("|")})$`, "i");
const PHONE = /^01[016789]-\d{4}-\d{4}$/;
const PASSWORD = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9\s])\S{8,13}$/;
const LOGIN_ID = /^[a-z][a-z0-9]{3,19}$/;

/** 틀에 맞으면 "", 아니면 안내 문구 */
export const check = {
  name: (v: string) => (NAME_KO.test(v) || NAME_EN.test(v) ? "" : "이름은 한글 2~17자 또는 영문으로 입력해 주세요"),
  email: (v: string) => (EMAIL.test(v) ? "" : "네이버·구글 등 실제 쓰는 메일 주소를 입력해 주세요"),
  phone: (v: string) => (PHONE.test(v) ? "" : "휴대폰 번호는 010-1234-5678 형식으로 입력해 주세요"),
  password: (v: string) => (PASSWORD.test(v) ? "" : "비밀번호는 영문·숫자·특수문자를 모두 넣어 8~13자로 입력해 주세요"),
  loginId: (v: string) => (LOGIN_ID.test(v) ? "" : "아이디는 영문 소문자로 시작하는 영문 소문자·숫자 4~20자로 입력해 주세요"),
};

/** 숫자만 받아 010-1234-5678 모양으로 (최대 11자리) */
export function formatPhone(v: string): string {
  const d = v.replace(/\D/g, "").slice(0, 11);
  return d.length <= 3 ? d : d.length <= 7 ? `${d.slice(0, 3)}-${d.slice(3)}` : `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
}
