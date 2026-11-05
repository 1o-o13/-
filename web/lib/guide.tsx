"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";

export type Rules = { total_questions: number; think_sec_non_tech: number; think_sec_tech: number; answer_max_sec: number; silence_skip_sec: number };
export type Guide = {
  posting_id: number;
  title: string; stage2_start: string; stage2_end: string; final_announce_at: string; session_id: number | null; exam_code: string | null;
  session_status: string | null; can_start: boolean; reason: string | null; steps: string[]; rules: Rules;
  coding_required: boolean; coding_status: string | null; face_real: boolean; has_photo: boolean;
};

/** 지원자 면접 화면 공통: 경로의 appId로 안내 정보(GET /guide)를 읽는다 */
export function useGuide() {
  const appId = Number(useParams<{ appId: string }>().appId);
  const router = useRouter();
  const [guide, setGuide] = useState<Guide | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Guide>(`/interview/applications/${appId}/guide`).then(setGuide, (e) => setErr(errorText(e, router.push)));
  }, [appId, router]);
  return { appId, guide, err, router };
}

export const day = (s: string) => new Date(s).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", weekday: "short", hour: "2-digit", minute: "2-digit" });

export function RulesList({ r }: { r: Rules }) {
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      <li>{r.total_questions}문항 · 1·2번은 경험·가치 질문, 3번부터 기술 질문 (답변에 따라 더 깊게 묻거나 한 번 다시 물을 수 있음)</li>
      <li>질문마다 생각 시간({r.think_sec_non_tech}초·{r.think_sec_tech}초) 뒤 녹음 · 답변 최대 {Math.round(r.answer_max_sec / 60)}분 · 답변을 마치면 &apos;답변 끝&apos; 버튼 · 다시 녹음 불가</li>
      <li>시작하면 끝까지 이어서 진행 · 탭·창 이탈 2번 또는 한 번에 10초 이상이면 포기 처리</li>
      <li>영상은 저장하지 않고, 음성은 텍스트로 바꾼 뒤 지움</li>
    </ul>
  );
}
