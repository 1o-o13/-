// 채용 공고 관리 화면들이 같이 쓰는 이름표 (임시: 공고 파트 정식 기능이 오면 교체)
export const STATUS: Record<string, [string, string]> = {
  draft: ["작성 중", "bg-slate-100 text-slate-700"], dept_review: ["부서 확인 중", "bg-amber-100 text-amber-800"],
  published: ["게시 중", "bg-emerald-100 text-emerald-800"], closed: ["마감", "bg-slate-200 text-slate-600"], finished: ["채용 끝", "bg-slate-200 text-slate-600"],
};
export const CAREER: Record<string, string> = { new: "신입 (0~2년)", junior: "주니어 (3~5년)", senior: "시니어 (6년+)" };
export const ROLES = ["백엔드", "프론트엔드", "AI", "데이터", "임베디드"];   // 회사 문서·질문 은행이 있는 직무 (api/interview/engine.DEPT)
