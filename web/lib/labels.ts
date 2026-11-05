// 관리자 화면 상태 표시
export const SESSION: Record<string, string> = {
  ready: "준비", prechecked: "점검 완료", in_progress: "응시 중", paused: "멈춤", completed: "완료", abandoned: "응시 포기",
  system_error: "시스템 오류", retake_granted: "재응시 부여",
};
export const EVAL: Record<string, string> = { checking: "검증 중", passed: "검증 완료", failed: "검증 실패" };
// 회사 문서 주제 코드 → 프로젝트 이름 (seed/corpus_6_1/META_SPEC.md, 11/17)
export const TOPIC: Record<string, string> = {
  PAY: "페이브릿지 (결제)", SRC: "파인드 (검색·추천)", CHT: "톡허브 (상담 채팅)", DWH: "레이크하우스 (데이터)",
  IOT: "팩토리아이 (물류 센서)", WEB: "스토어프론트 (웹·앱)", COMMON: "공통",
};
/** "CHT 2" → "톡허브 (상담 채팅) 2번째" (같은 주제를 두 번 물으면 뒤에 번호가 붙음) */
export const topicName = (k: string) => {
  const [code, n] = k.split(" ");
  return `${TOPIC[code] ?? code}${n && n !== "1" ? ` ${n}번째` : ""}`;
};
// 인재상 가치 코드 (seed/corpus_6_1/09_인재상.md)
export const VALUE: Record<string, string> = { OWN: "주인의식", COL: "협업", INT: "정직", CUS: "고객 중심", GRW: "성장" };
