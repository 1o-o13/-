"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";

type Result = { title: string; passed: boolean; published_at: string; stage2_start: string; stage2_end: string; final_announce_at: string };
const when = (s: string) => new Date(s).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit" });

// 1차(서류) 결과 발표: 알림 버튼 → 이 화면. 합격이면 2차(코딩 테스트 + AI 면접) 응시 기간과 준비할 것을 안내한다. 점수는 보여 주지 않는다
export default function DocumentResult() {
  const pid = useParams<{ pid: string }>().pid;
  const router = useRouter();
  const [r, setR] = useState<Result | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Result>(`/me/results/${pid}/document`).then(setR, (e) => setErr(errorText(e, router.push)));
  }, [pid, router]);

  if (err) return <main className="mx-auto max-w-2xl px-6 py-16"><p className="card">{err} <Link className="text-brand-700" href="/me/applications">지원 현황 보기</Link></p></main>;
  if (!r) return <main className="mx-auto max-w-2xl px-6 py-16 text-slate-500">불러오는 중…</main>;
  return (
    <main className="mx-auto max-w-2xl space-y-5 px-6 py-12">
      <div>
        <p className="text-sm text-brand-600">1차 서류 전형 결과 발표 · {when(r.published_at)}</p>
        <h1 className="mt-1 text-2xl font-bold">{r.title}</h1>
      </div>
      {r.passed ? (
        <section className="card space-y-3 border-emerald-200 bg-emerald-50/50">
          <p className="text-xl font-bold text-emerald-800" data-testid="doc-result">서류 전형에 합격하셨습니다.</p>
          <p>
            새벽소프트에 관심을 갖고 정성껏 지원서를 작성해 주셔서 감사합니다. 지원서에 담아 주신 경험과 이야기를 바탕으로 다음 전형에서 더 깊이
            이야기를 나누고 싶습니다.
          </p>
          <p>2차 전형(코딩 테스트 + AI 화상 면접)을 아래 기간 안에 원하는 시간에 응시해 주세요.</p>
          <dl className="grid grid-cols-[7rem_1fr] gap-y-1.5 text-sm">
            <dt className="text-slate-500">응시 기간</dt><dd className="font-semibold">{when(r.stage2_start)} ~ {when(r.stage2_end)}</dd>
            <dt className="text-slate-500">준비 기간</dt><dd>지금부터 응시 시작 전까지</dd>
            <dt className="text-slate-500">최종 발표</dt><dd>{when(r.final_announce_at)}</dd>
          </dl>
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
            <li>코딩 테스트를 먼저 보고, 끝나면 AI 화상 면접으로 이어집니다. 언어는 Python 또는 Java입니다.</li>
            <li>카메라·마이크가 있는 PC와 조용한 곳이 필요합니다. 응시 전에 장치 점검과 본인 확인을 합니다.</li>
            <li>응시 기간이 되면 <b>지원 현황</b>에서 응시 버튼이 열립니다.</li>
          </ul>
          <Link className="btn inline-block" href="/me/applications">지원 현황으로</Link>
        </section>
      ) : (
        <section className="card space-y-3">
          <p className="text-xl font-bold" data-testid="doc-result">아쉽게도 이번 서류 전형에는 함께하지 못하게 되었습니다.</p>
          <p className="text-slate-700">
            먼저 새벽소프트에 관심을 갖고 소중한 시간을 내어 지원해 주셔서 진심으로 감사드립니다. 보내 주신 지원서는 담당자가 한 분 한 분 꼼꼼히
            살펴보았습니다. 다만 이번 공고는 모집 인원이 정해져 있어 많은 분과 함께하지 못하게 되었고, 아쉽지만 이번에는 좋은 소식을 전해 드리지
            못하게 되었습니다.
          </p>
          <p className="text-slate-700">
            이번 결과가 지원자님의 역량이 부족하다는 뜻은 아닙니다. 앞으로 더 잘 맞는 자리에서 다시 만날 수 있기를 바랍니다. 지원자님의 앞날을
            진심으로 응원합니다.
          </p>
          <p className="text-sm text-slate-600">진행 중인 다른 공고에는 바로 지원하실 수 있습니다.</p>
          <Link className="btn-line inline-block" href="/#jobs">다른 공고 보기</Link>
        </section>
      )}
    </main>
  );
}
