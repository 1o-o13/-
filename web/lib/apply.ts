// 지원 규칙 (api/site.py와 같게): 진행 중인 지원(최종 결과 전)이 있으면 다른 공고에는 지원할 수 없다
export const ACTIVE = ["submitted", "doc_passed", "stage2", "stage2_done"];
export type MyApp = { posting_id: number; title: string; status: string; final_announce_at: string };

/** 이 공고 말고 진행 중인 지원 (없으면 undefined) */
export function activeElsewhere(apps: MyApp[], pid: number): MyApp | undefined {
  return apps.find((a) => a.posting_id !== pid && ACTIVE.includes(a.status));
}

export const announce = (s: string) => new Date(s).toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
