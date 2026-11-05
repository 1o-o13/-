"use client";
import Link from "next/link";
import { ContactButton } from "@/lib/brand";
import { useGuide } from "@/lib/guide";

// CAN-013 응시 완료. 점수·판정은 보여 주지 않고 발표 예정일만. 포기·시스템 오류면 종료 안내
export default function Done() {
  const { guide: g, err } = useGuide();
  if (err) return <p className="err">{err}</p>;
  if (!g) return <p>불러오는 중…</p>;
  const day = new Date(g.final_announce_at).toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit", weekday: "short" });
  const [title, body] =
    g.session_status === "abandoned"
      ? ["면접이 종료되었습니다", "감독 규칙(화면 이탈)에 따라 면접이 포기 처리되었습니다."]
      : g.session_status === "system_error"
        ? ["면접이 멈췄습니다", "시스템 문제로 면접을 이어 갈 수 없습니다. 담당자가 확인한 뒤 안내해 드립니다."]
        : ["✓ 면접이 종료되었습니다", `모든 답변이 제출되었습니다. 최종 합격 여부는 ${day}에 발표하며, 채용 사이트의 지원 현황과 알림(메일·문자)으로 알려 드립니다.`];
  return (
    <div className="card mx-auto mt-16 max-w-xl space-y-4 text-center">
      <h1 className="text-xl font-bold">{title}</h1>
      <p>{body}</p>
      <div className="flex justify-center gap-2">
        <ContactButton postingId={g.posting_id} />
        <Link className="btn inline-block" href="/me/applications">
          지원 현황으로
        </Link>
      </div>
    </div>
  );
}
