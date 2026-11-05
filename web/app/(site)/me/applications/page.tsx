"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";

type App = { id: number; posting_id: number; title: string; status: string; stage2_start: string; stage2_end: string; final_announce_at: string; apply_end: string; editable: boolean; has_photo: boolean };

const STATUS: Record<string, string> = {
  submitted: "서류 심사 중", doc_passed: "서류 합격", doc_failed: "서류 불합격", stage2: "2차 응시 대상", stage2_done: "2차 응시 완료",
  final_passed: "최종 합격", final_failed: "최종 불합격", withdrawn: "지원 취소", abandoned: "응시 포기",
};
const STEPS = ["서류 전형", "2차 (코딩·AI 면접)", "최종 발표"];
const stepOf = (s: string) => (["submitted", "doc_passed", "doc_failed"].includes(s) ? 0 : ["stage2", "stage2_done", "abandoned"].includes(s) ? 1 : 2);
const day = (s: string) => new Date(s).toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });

// CAN-007 간단 목록: 지원한 공고와 진행 상태만 (점수 없음)
export default function MyApplications() {
  const router = useRouter();
  const [apps, setApps] = useState<App[] | null>(null);
  const [err, setErr] = useState("");

  const load = () => api<App[]>("/interview/applications").then(setApps, (e) => setErr(errorText(e, router.push)));
  useEffect(() => {
    load();
  }, [router]); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(a: App, file: File | undefined) {
    if (!file) return;
    const body = new FormData();
    body.append("photo", file);
    try {
      await api(`/interview/applications/${a.id}/photo`, { method: "POST", body });
      setErr("");
      load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <main className="mx-auto max-w-4xl space-y-4 px-6 py-10">
      <h1 className="text-2xl font-bold">지원 현황</h1>
      {err && <p className="err">{err}</p>}
      {apps?.length === 0 && (
        <div className="card text-slate-600">
          지원한 공고가 없습니다. <Link className="text-brand-700" href="/#jobs">채용 공고 보기</Link>
        </div>
      )}
      {apps?.map((a) => (
        <div key={a.id} className="card space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-lg font-semibold">{a.title}</p>
              <p className="text-sm text-slate-600">
                <span className="badge">{STATUS[a.status] ?? a.status}</span>
                {a.status !== "doc_failed" && <> · 2차 응시 기간 {day(a.stage2_start)} ~ {day(a.stage2_end)} · 최종 발표 {day(a.final_announce_at)}</>}
              </p>
            </div>
            {a.status === "stage2" && <Link className="btn" href={`/interview/${a.id}/guide`}>2차 응시 안내</Link>}
            {a.editable && (
              <div className="text-right">
                <Link className="btn-line" href={`/jobs/${a.posting_id}/apply`}>지원서 수정</Link>
                <p className="mt-1 text-xs text-slate-500">{day(a.apply_end)} 접수 마감 전까지 고칠 수 있습니다</p>
              </div>
            )}
          </div>
          {["submitted", "stage2"].includes(a.status) && (
            <label className="flex items-center gap-2 text-sm text-slate-600">
              증명사진 (2차 본인 확인 얼굴 대조 기준) <span className="badge">{a.has_photo ? "올림" : "없음"}</span>
              <input type="file" accept="image/jpeg,image/png" name={`photo-${a.id}`} className="text-xs" onChange={(e) => upload(a, e.target.files?.[0])} />
            </label>
          )}
          {a.status === "doc_failed" && (
            <section className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700" data-testid="doc-failed-note">
              <p className="text-base font-bold text-slate-800">이번 서류 전형에는 아쉽게도 함께하지 못하게 되었습니다.</p>
              <p>
                새벽소프트에 관심을 갖고 소중한 시간을 내어 지원해 주셔서 진심으로 감사드립니다. 보내 주신 지원서는 담당자가 한 분 한 분 꼼꼼히
                살펴보았습니다. 다만 이번 공고는 모집 인원이 정해져 있어 많은 분과 함께하지 못하게 되었습니다.
              </p>
              <p>
                이번 결과가 지원자님의 역량이 부족하다는 뜻은 아닙니다. 진행 중인 다른 공고에는 바로 지원하실 수 있고, 앞으로 더 잘 맞는 자리에서
                다시 만날 수 있기를 바랍니다. 지원자님의 앞날을 진심으로 응원합니다.
              </p>
              <div className="flex gap-2 pt-1">
                <Link className="btn-line" href={`/me/results/${a.posting_id}`}>결과 안내 자세히 보기</Link>
                <Link className="btn-line" href="/#jobs">다른 공고 보기</Link>
              </div>
            </section>
          )}
          {a.status === "final_passed" && (
            <section className="space-y-2 rounded-md border border-emerald-200 bg-emerald-50/50 p-4 text-sm text-slate-700" data-testid="final-result">
              <p className="text-base font-bold text-emerald-800">최종 합격을 진심으로 축하드립니다.</p>
              <p>
                서류 전형부터 코딩 테스트, AI 화상 면접까지 긴 과정에 성실히 임해 주셔서 감사합니다. 전형 내내 보여 주신 경험과 생각을 바탕으로,
                새벽소프트는 지원자님과 함께 앞으로의 길을 걸어가고자 합니다.
              </p>
              <p>입사 일정과 준비할 서류는 담당자가 메일과 문자로 따로 안내해 드리겠습니다. 함께하게 되어 기쁩니다.</p>
            </section>
          )}
          {a.status === "final_failed" && (
            <section className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700" data-testid="final-result">
              <p className="text-base font-bold text-slate-800">아쉽게도 이번에는 함께하지 못하게 되었습니다.</p>
              <p>
                새벽소프트에 지원해 주시고 서류 전형부터 코딩 테스트, AI 화상 면접까지 긴 과정에 성실히 참여해 주셔서 진심으로 감사드립니다.
                전형 과정에서 보여 주신 노력과 열정은 담당자 모두가 소중하게 살펴보았습니다.
              </p>
              <p>
                모집 인원이 정해져 있어 아쉽지만 이번에는 좋은 소식을 전해 드리지 못하게 되었습니다. 이번 결과가 지원자님의 가능성을 정하는 것은
                아닙니다. 앞으로 더 좋은 기회로 다시 만나기를 바라며, 지원자님의 앞날을 진심으로 응원합니다.
              </p>
            </section>
          )}
          <ol className="flex gap-2 text-xs">
            {STEPS.map((s, i) => (
              <li key={s} className={`flex-1 rounded-md px-3 py-2 ${i < stepOf(a.status) ? "bg-brand-50 text-brand-700" : i === stepOf(a.status) ? "bg-brand-700 text-white" : "bg-slate-100 text-slate-500"}`}>{s}</li>
            ))}
          </ol>
        </div>
      ))}
    </main>
  );
}
