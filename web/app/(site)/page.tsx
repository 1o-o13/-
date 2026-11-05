"use client";
// 가상 회사 '새벽소프트' 채용 홈. 회사 소개(미션·목표·가치·연혁)·복지·채용 공고·채용 절차·자주 묻는 질문
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ACTIVE, activeElsewhere, announce, type MyApp } from "@/lib/apply";
import { COMPANY } from "@/lib/brand";

type Posting = {
  id: number; title: string; job_role: string; career_level: string; headcount: number; description: string | null;
  apply_start: string; apply_end: string; doc_announce_at: string; stage2_start: string; stage2_end: string; final_announce_at: string;
  phase: "accepting" | "upcoming" | "screening" | "past";
};

const LEVEL: Record<string, string> = { new: "신입", junior: "경력 2년+", senior: "경력 5년+" };
const FIRST = 4; // 처음에 보여 줄 공고 수 (11/17: 공고를 줄여 접수·진행 중 4개를 한 번에)
const MORE = 4; // '더보기' 한 번에 더 보여 줄 수
const day = (s: string) => new Date(s).toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
const dday = (s: string) => Math.ceil((new Date(s).getTime() - Date.now()) / 86_400_000);

const STATS = [
  ["2018", "설립"],
  ["184명", "구성원 · 개발 112명"],
  ["3,200만 건", "하루 처리 요청"],
  ["99.98%", "결제 서비스 가용성"],
];
const GOALS = [
  ["2027", "하루 1억 건 처리", "결제·정산 플랫폼을 다시 설계해 지금의 3배를 받습니다."],
  ["2028", "가용성 99.99%", "모든 서비스를 다중 리전으로 옮기고 장애 복구 시간을 5분 안으로 줄입니다."],
  ["2030", "아시아 3개국", "일본·베트남 가맹점에 같은 결제 경험을 제공합니다."],
];
const VALUES = [
  ["주인의식", "맡은 서비스는 끝까지 책임지고, 장애도 숨기지 않고 공유합니다."],
  ["함께 일하기", "설계 문서와 회고를 모두가 읽고 고칩니다. 혼자 잘하는 것보다 같이 잘하는 것."],
  ["정직", "모르는 것은 모른다고 말하고, 숫자로 확인한 뒤 결정합니다."],
  ["고객 먼저", "가맹점과 이용자가 겪는 1초의 지연도 우리 문제로 봅니다."],
  ["성장", "새로운 기술을 써 볼 시간과 실패해도 되는 환경을 만듭니다."],
];
const HISTORY = [
  ["2018", "설립 · 결제 게이트웨이 페이브릿지 출시"],
  ["2020", "정산온·톡허브 출시, 가맹점 1만 곳"],
  ["2022", "시리즈 B 투자 유치, 사내 플랫폼 쉽잇 도입"],
  ["2024", "운영 서비스 20개, 하루 요청 3천만 건 돌파"],
  ["2026", "AI 추천(픽미)·이상거래 탐지(가디언) 정식 출시"],
];
const PERKS: [string, string, string[]][] = [
  ["🕘", "일하는 방식", ["8~11시 자율 출근, 코어 타임 11~16시", "주 2회 재택 근무", "3년마다 2주 리프레시 휴가 + 휴가비 100만 원"]],
  ["💰", "보상", ["연 1회 연봉 협상, 반기 성과급", "입사 시 스톡옵션 부여", "추천 입사 시 보상금 300만 원"]],
  ["📚", "성장", ["교육·도서·컨퍼런스 연 200만 원", "사내 기술 세미나·스터디 지원", "해외 컨퍼런스 연 1회 참가 지원"]],
  ["🩺", "건강", ["본인·가족 종합 검진", "단체 상해·실손 보험", "전문 심리 상담 연 6회"]],
  ["🍱", "생활", ["점심 식대 지원, 간식·커피 무제한", "원하는 노트북과 모니터 2대", "통신비 월 5만 원"]],
  ["👨‍👩‍👧", "가족", ["경조사 휴가·경조금", "출산 축하금, 육아기 단축 근무", "자녀 학자금 지원"]],
];
const STEPS = [
  ["서류 전형", "이력서로 직무 적합도를 봅니다. 결과는 서류 발표일에 안내합니다."],
  ["코딩 테스트", "알고리즘 3문제. 결과의 약점 요약이 면접 질문에 쓰입니다."],
  ["AI 화상면접", "10문항, 약 30분. 답변에 따라 더 깊이 묻거나 한 번 다시 묻습니다."],
  ["최종 발표", "2차 결과와 부서 의견을 함께 보고 채용 사이트에서 안내합니다."],
];
const FAQ = [
  ["AI 화상면접 영상이 저장되나요?", "저장하지 않습니다. 영상은 브라우저 안에서 감독(화면 이탈·얼굴 확인)에만 쓰고, 본인 확인 사진 1장도 대조 뒤 바로 버립니다. 답변 음성은 텍스트로 바꾼 뒤 지웁니다."],
  ["면접 점수를 볼 수 있나요?", "면접 중이나 끝난 뒤에 점수·판정은 보여 드리지 않습니다. 결과는 최종 발표일에 채용 사이트에서 확인합니다."],
  ["응시 중 문제가 생기면요?", "면접 화면의 '문의하기'를 눌러 주세요. 시스템 문제로 확인되면 머문 시간만큼 시간을 더 드리고, 면접이 멈추면 담당자가 재응시를 안내합니다."],
  ["준비물이 있나요?", "PC와 최신 Chrome, 웹캠·마이크, 조용한 장소가 필요합니다. 응시 전 튜토리얼로 미리 연습할 수 있습니다."],
  ["여러 공고에 동시에 지원할 수 있나요?", "한 번에 한 공고만 진행할 수 있습니다. 지원한 공고의 결과가 나온 뒤(불합격 포함) 다른 공고에 지원할 수 있고, 같은 공고에 다시 지원할 수는 없습니다."],
];

function Section({ id, eyebrow, title, desc, children, gray }: { id?: string; eyebrow: string; title: string; desc?: string; children: React.ReactNode; gray?: boolean }) {
  return (
    <section id={id} className={gray ? "bg-slate-100/60" : ""}>
      <div className="mx-auto max-w-6xl px-6 py-20">
        <p className="text-sm font-semibold tracking-wide text-brand-600">{eyebrow}</p>
        <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">{title}</h2>
        {desc && <p className="mt-3 max-w-2xl text-slate-600">{desc}</p>}
        <div className="mt-10">{children}</div>
      </div>
    </section>
  );
}

function PostingCard({ p, applied, blocked }: { p: Posting; applied: boolean; blocked?: MyApp }) {
  const left = dday(p.apply_end);
  const badge =
    p.phase === "accepting" ? <span className="rounded-full bg-dawn-500 px-3 py-1 text-xs font-semibold text-white">{left <= 0 ? "오늘 마감" : `D-${left}`}</span>
    : p.phase === "upcoming" ? <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">접수 예정 · {day(p.apply_start)} 시작</span>
    : p.phase === "screening" ? <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">전형 진행 중</span>
    : <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">채용 마감</span>;
  return (
    <article className={`rounded-3xl border border-slate-100 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${p.phase === "past" ? "opacity-70" : ""}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-wrap gap-1.5">
          <span className="badge">{p.job_role}</span>
          <span className="badge">{LEVEL[p.career_level]}</span>
          <span className="badge">{p.headcount}명</span>
        </div>
        {badge}
      </div>
      <h3 className="mt-3 text-lg font-semibold text-slate-900">{p.title}</h3>
      {p.description && <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-slate-600">{p.description}</p>}
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-slate-100 pt-4 text-xs text-slate-500">
        <dt>접수</dt><dd className="text-slate-700">{day(p.apply_start)} ~ {day(p.apply_end)}</dd>
        <dt>2차 (코딩·AI 면접)</dt><dd className="text-slate-700">{day(p.stage2_start)} ~ {day(p.stage2_end)}</dd>
        <dt>최종 발표</dt><dd className="text-slate-700">{day(p.final_announce_at)}</dd>
      </dl>
      {p.phase === "accepting" && (
        <div className="mt-4 flex justify-end">
          {blocked && !applied ? (
            <span className="rounded-full bg-slate-100 px-4 py-2 text-sm text-slate-500" title={`진행 중인 지원: ${blocked.title}`}>
              지원 불가 · {announce(blocked.final_announce_at)} 결과 발표 뒤 지원 가능
            </span>
          ) : applied ? (
            <span className="flex gap-2">
              <Link href={`/jobs/${p.id}/apply`} className="btn-line px-4 py-2 text-sm font-semibold text-slate-700">지원서 수정</Link>
              <Link href="/me/applications" className="rounded-full bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-600">지원 완료 · 지원 현황</Link>
            </span>
          ) : (
            <Link href={`/jobs/${p.id}/apply`} className="btn px-5 py-2 text-sm font-semibold">지원하기</Link>
          )}
        </div>
      )}
    </article>
  );
}

export default function Home() {
  const [postings, setPostings] = useState<Posting[] | null>(null);
  const [shown, setShown] = useState(FIRST);
  const [showPast, setShowPast] = useState(false);
  const [mine, setMine] = useState<MyApp[]>([]); // 로그인한 지원자의 지원서 (이미 지원한 공고·진행 중인 지원)
  const applied = mine.map((a) => a.posting_id);
  const [bye, setBye] = useState(false); // 회원 탈퇴 직후 안내
  useEffect(() => {
    api<Posting[]>("/site/postings").then(setPostings, () => setPostings([]));
    setBye(new URLSearchParams(window.location.search).has("bye"));
    api<MyApp[]>("/interview/applications").then(setMine, () => {});
  }, []);
  const current = postings?.filter((p) => p.phase !== "past") ?? [];
  const past = postings?.filter((p) => p.phase === "past") ?? [];

  return (
    <main>
      {bye && <p className="bg-slate-800 py-3 text-center text-sm text-white">회원 탈퇴가 끝났습니다. 그동안 이용해 주셔서 감사합니다.</p>}
      {/* 첫 화면 */}
      <section className="relative overflow-hidden bg-linear-to-br from-[#fff1e6] via-[#f3eeff] to-[#e6f0ff] text-slate-900">
        <div className="absolute -right-24 -top-32 h-[28rem] w-[28rem] rounded-full bg-dawn-400/25 blur-3xl" />
        <div className="absolute -bottom-40 left-1/4 h-96 w-96 rounded-full bg-brand-600/15 blur-3xl" />
        <div className="absolute -left-24 top-10 h-72 w-72 rounded-full bg-pink-300/20 blur-3xl" />
        <div className="relative mx-auto grid max-w-6xl grid-cols-[1.3fr_1fr] items-center gap-10 px-6 py-24 max-md:grid-cols-1">
          <div>
            <p className="inline-block rounded-full border border-white bg-white/70 px-3.5 py-1.5 text-xs font-medium text-brand-700 shadow-sm">{COMPANY} 채용 · 2026 하반기</p>
            <h1 className="mt-5 text-4xl font-bold leading-tight tracking-tight lg:text-5xl">
              매일의 거래가 멈추지 않도록,<br /><span className="bg-linear-to-r from-brand-700 to-dawn-500 bg-clip-text text-transparent">새벽에도 깨어 있는</span><br />소프트웨어를 만듭니다
            </h1>
            <p className="mt-5 max-w-lg text-slate-600">결제·정산·검색·인증까지 하루 3,200만 건의 요청을 받는 서비스를 함께 키울 동료를 찾습니다.</p>
            <div className="mt-8 flex gap-3">
              <Link href="/#jobs" className="btn px-6 py-3 font-semibold">채용 공고 보기</Link>
              <Link href="/#about" className="btn-line border-white bg-white/70 px-6 py-3 font-semibold text-slate-700">회사 알아보기</Link>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {STATS.map(([n, l]) => (
              <div key={l} className="rounded-3xl border border-white bg-white/70 p-5 shadow-sm backdrop-blur">
                <p className="text-2xl font-bold text-brand-700">{n}</p>
                <p className="mt-1 text-sm text-slate-600">{l}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 회사 소개 */}
      <Section id="about" eyebrow="ABOUT" title="모든 거래가 멈추지 않는 세상" desc={`${COMPANY}는 커머스·핀테크 회사가 쓰는 결제·정산·검색·인증 서비스 20개를 직접 만들고 운영합니다. 가맹점 3만 곳, 이용자 1,200만 명이 매일 우리 서비스를 거쳐 갑니다.`}>
        <div className="grid grid-cols-3 gap-5 max-md:grid-cols-1">
          {GOALS.map(([y, t, d]) => (
            <div key={y} className="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
              <p className="text-sm font-semibold text-dawn-500">{y} 목표</p>
              <p className="mt-2 text-xl font-bold text-slate-900">{t}</p>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{d}</p>
            </div>
          ))}
        </div>
        <div className="mt-14 grid grid-cols-[1fr_1fr] gap-10 max-md:grid-cols-1">
          <div>
            <h3 className="text-lg font-bold text-slate-900">우리가 일하는 방식</h3>
            <ul className="mt-5 space-y-4">
              {VALUES.map(([t, d]) => (
                <li key={t} className="flex gap-4">
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand-600" />
                  <div><p className="font-semibold text-slate-900">{t}</p><p className="text-sm text-slate-600">{d}</p></div>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900">걸어온 길</h3>
            <ol className="mt-5 border-l-2 border-slate-200">
              {HISTORY.map(([y, t]) => (
                <li key={y} className="relative pb-5 pl-6 last:pb-0">
                  <span className="absolute -left-[7px] top-1.5 h-3 w-3 rounded-full border-2 border-white bg-brand-600" />
                  <p className="text-sm font-semibold text-brand-700">{y}</p>
                  <p className="text-sm text-slate-700">{t}</p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </Section>

      {/* 복지 */}
      <Section id="perks" eyebrow="BENEFITS" title="일에 집중할 수 있도록" desc="좋은 소프트웨어는 충분히 쉬고 배우는 사람이 만든다고 믿습니다." gray>
        <div className="grid grid-cols-3 gap-5 max-md:grid-cols-1">
          {PERKS.map(([icon, t, items]) => (
            <div key={t} className="rounded-3xl bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
              <p className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-2xl">{icon}</p>
              <p className="mt-3 font-bold text-slate-900">{t}</p>
              <ul className="mt-3 space-y-1.5 text-sm text-slate-600">
                {items.map((x) => <li key={x}>· {x}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </Section>

      {/* 채용 공고 */}
      <Section id="jobs" eyebrow="CAREERS" title="채용 공고" desc="지금 진행 중인 공고입니다. 한 번에 한 공고만 지원할 수 있고, 결과가 나오면 다른 공고에 지원할 수 있습니다.">
        {postings === null && <p className="text-slate-500">불러오는 중…</p>}
        {postings && current.length === 0 && <p className="text-slate-500">지금 진행 중인 공고가 없습니다.</p>}
        {(() => {
          const busy = mine.find((a) => ACTIVE.includes(a.status));
          return busy ? (
            <p className="mb-5 rounded-xl bg-brand-50 p-4 text-sm text-brand-900" data-testid="active-notice">
              진행 중인 지원(<b>{busy.title}</b>)이 있어, {announce(busy.final_announce_at)} 결과 발표 전까지 다른 공고에는 지원할 수 없습니다.
            </p>
          ) : null;
        })()}
        <div className="grid grid-cols-2 gap-5 max-md:grid-cols-1" data-testid="current-postings">
          {current.slice(0, shown).map((p) => <PostingCard key={p.id} p={p} applied={applied.includes(p.id)} blocked={activeElsewhere(mine, p.id)} />)}
        </div>
        {current.length > shown && (
          <div className="mt-6 text-center">
            <button className="btn-line px-6 py-2.5 text-sm font-semibold" onClick={() => setShown(shown + MORE)}>
              더보기 ({current.length - shown}개 남음)
            </button>
          </div>
        )}
        {past.length > 0 && (
          <div className="mt-12 border-t border-slate-200 pt-6">
            <button className="text-sm font-semibold text-slate-500 hover:text-slate-800" onClick={() => setShowPast(!showPast)}>
              지난 공고 {past.length}개 {showPast ? "접기 ▲" : "보기 ▼"}
            </button>
            {showPast && (
              <div className="mt-5 grid grid-cols-2 gap-5 max-md:grid-cols-1" data-testid="past-postings">
                {past.map((p) => <PostingCard key={p.id} p={p} applied={applied.includes(p.id)} />)}
              </div>
            )}
          </div>
        )}
      </Section>

      {/* 채용 절차 */}
      <Section id="process" eyebrow="PROCESS" title="채용 절차" gray>
        <ol className="grid grid-cols-4 gap-5 max-md:grid-cols-1">
          {STEPS.map(([t, d], i) => (
            <li key={t} className="rounded-3xl bg-white p-6 shadow-sm">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-50 text-sm font-bold text-brand-700">{i + 1}</span>
              <p className="mt-4 font-bold text-slate-900">{t}</p>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{d}</p>
            </li>
          ))}
        </ol>
        <p className="mt-6 rounded-2xl bg-white p-4 text-sm text-slate-600 shadow-sm">
          🔒 AI 화상면접은 영상을 저장하지 않습니다. 답변 음성은 텍스트로 바꾼 뒤 바로 지우고, 평가에는 이름·학교·연락처 같은 개인정보를 가린 내용만 씁니다.
        </p>
      </Section>

      {/* 자주 묻는 질문 */}
      <Section id="faq" eyebrow="FAQ" title="자주 묻는 질문">
        <div className="divide-y divide-slate-100 rounded-3xl border border-slate-100 bg-white shadow-sm">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group px-6 py-5">
              <summary className="flex cursor-pointer list-none items-center justify-between font-semibold text-slate-900">
                {q}
                <span className="text-slate-400 transition group-open:rotate-45">＋</span>
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-slate-600">{a}</p>
            </details>
          ))}
        </div>
      </Section>

      <section className="px-6 pb-20">
        <div className="relative mx-auto flex max-w-6xl items-center justify-between gap-6 overflow-hidden rounded-[2rem] bg-linear-to-r from-brand-700 via-[#8478f0] to-[#f2a37c] px-10 py-12 shadow-lg max-md:flex-col">
          <div>
            <p className="text-2xl font-bold text-white">새벽을 함께 열 동료를 기다립니다</p>
            <p className="mt-2 text-white/85">지금 지원하고, 지원 현황에서 진행 상황을 확인하세요.</p>
          </div>
          <div className="flex gap-3">
            <Link href="/signup" className="rounded-full bg-white px-6 py-3 font-semibold text-brand-700 shadow-sm transition hover:bg-brand-50">회원가입</Link>
            <Link href="/me/applications" className="rounded-full border border-white/50 px-6 py-3 font-semibold text-white transition hover:bg-white/15">내 지원 현황</Link>
          </div>
        </div>
      </section>
    </main>
  );
}
