"use client";
// ※ 지원서 작성·제출 (CAN-005·006은 다른 파트 화면이 오면 바꾼다). 이름·연락처·이메일은 계정 정보를 그대로 쓴다
// 이미 낸 지원서는 접수 마감 전·서류 심사 중이면 이 화면에서 고친다 (마지막 저장본이 제출본)
// 항목은 팀 이력서 양식(v0.3 수정본, 4쪽)과 같은 순서: 머리말 → 인적사항 → 학력 → 수상 → 경력 → 자격증 → 교육·활동 → 경력직무 상세 → 보유기술 → 프로젝트 소개서 → 자기소개서
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { activeElsewhere, announce, type MyApp } from "@/lib/apply";

type Posting = { id: number; title: string; job_role: string; apply_end: string; phase: string; description: string | null };
type Essays = { questions: { key: string; question: string }[]; max: number };
type Row = Record<string, string>;
/** 표 항목. key·k = API 칸 이름, need = 이 칸이 비면 그 줄은 보내지 않음, area = 여러 줄 */
type Col = { k: string; label: string; max: number; area?: boolean; ph?: string; req?: boolean };   // req = 첫 줄 필수
type Spec = { key: string; title: string; hint?: string; need: string; max: number; cols: Col[] };
const SPECS: Spec[] = [
  { key: "학력사항", title: "학력사항", hint: "대학·고등학교 (첫 줄 필수)", need: "학교", max: 5, cols: [
    { k: "기간", label: "기간", max: 40, ph: "2022.03 - 2026.02" }, { k: "학교", label: "학교", max: 60, req: true }, { k: "학과", label: "학과", max: 60 },
    { k: "학점", label: "학점", max: 20, ph: "3.72·4.5" }, { k: "상태", label: "졸업 여부", max: 20, ph: "졸업 / 재학" }] },
  { key: "수상경력", title: "수상경력", need: "수상명", max: 10, cols: [
    { k: "수상일", label: "수상일", max: 20, ph: "2025.11" }, { k: "수상명", label: "수상명", max: 80 }, { k: "수여기관", label: "수여기관", max: 60 },
    { k: "내용", label: "수상 내용", max: 300 }] },
  { key: "경력사항", title: "경력사항", hint: "없으면 비워 두세요", need: "회사", max: 10, cols: [
    { k: "기간", label: "기간", max: 40 }, { k: "회사", label: "회사", max: 60 }, { k: "직무", label: "직무", max: 60 },
    { k: "총기간", label: "총 기간", max: 30, ph: "1년 6개월" }, { k: "요약", label: "한 일 요약", max: 200 }] },
  { key: "보유자격증", title: "보유자격증", need: "자격증명", max: 10, cols: [
    { k: "취득일", label: "취득일", max: 20 }, { k: "자격증명", label: "자격증명", max: 60 }, { k: "발급기관", label: "발급기관", max: 60 }] },
  { key: "교육활동", title: "교육사항 & 활동사항", hint: "부트캠프·강의·동아리·오픈소스", need: "과정", max: 10, cols: [
    { k: "기간", label: "기간", max: 40 }, { k: "기관", label: "기관", max: 60 }, { k: "과정", label: "교육과정·활동", max: 80 }, { k: "내용", label: "내용", max: 300 }] },
  { key: "경력직무상세", title: "경력직무 상세", hint: "회사에서 맡은 일을 구체적으로", need: "회사", max: 10, cols: [
    { k: "회사", label: "회사명", max: 60 }, { k: "기간", label: "근무기간", max: 40 }, { k: "수행직무", label: "수행 직무", max: 1000, area: true }] },
  { key: "보유기술", title: "보유기술", hint: "경험이 없는 분야는 기술내역에 '기재사항 없음'", need: "분야", max: 15, cols: [
    { k: "분야", label: "분야", max: 40, ph: "백엔드 개발" }, { k: "기술내역", label: "기술내역", max: 100, ph: "Python, FastAPI" },
    { k: "설명", label: "설명", max: 300 }] },
  { key: "프로젝트소개서", title: "프로젝트 소개서", hint: "대표 프로젝트", need: "이름", max: 3, cols: [
    { k: "주제", label: "프로젝트 주제", max: 80 }, { k: "이름", label: "프로젝트명", max: 80 }, { k: "기간", label: "수행기간", max: 40 },
    { k: "인원", label: "인원", max: 40 }, { k: "주소", label: "프로젝트 주소", max: 200 }, { k: "개발환경", label: "개발환경", max: 300 },
    { k: "동기목표", label: "동기 / 목표", max: 500, area: true }, { k: "담당역할", label: "담당역할", max: 500, area: true },
    { k: "작업과정성과", label: "작업과정 및 성과", max: 1500, area: true }, { k: "느낀점", label: "느낀점 / 성장점", max: 500, area: true }] },
];
const blank = (sp: Spec): Row => Object.fromEntries(sp.cols.map((c) => [c.k, ""]));
type Saved = { 성별: string | null; 생년월일: string | null; 주소: string | null; Github: string; 지원직무: string; 소개: string[]; 자기소개서: Record<string, string> } & Record<string, unknown>;
type Mine = { editable: boolean; resume: Saved };
type Form = { gender: string; birth: string; address: string; github: string; role: string; intro: string; intro2: string };
type Draft = { f: Form; tables: Record<string, Row[]>; essays: Record<string, string> };

const Req = () => <span className="ml-0.5 text-red-600" aria-label="필수">*</span>;
const bad = (on: boolean) => (on ? " ring-2 ring-red-400" : "");
const two = (n: number) => String(n).padStart(2, "0");

/** 생년월일: 년·월·일 선택 (연도 4자리, 일은 그 달 마지막 날까지만). 값은 YYYY-MM-DD, 셋 다 골라야 값이 생김 */
function BirthSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [y0, m0, d0] = value ? value.split("-") : ["", "", ""];
  const [y, setY] = useState(y0);
  const [m, setM] = useState(m0);
  const [d, setD] = useState(d0);
  useEffect(() => { setY(y0); setM(m0); setD(d0); }, [y0, m0, d0]);
  const top = new Date().getFullYear() - 15;                                     // 만 15세까지 (서버 BIRTH_MIN과 같은 범위)
  const years = Array.from({ length: top - 1940 + 1 }, (_, i) => String(top - i));
  const lastDay = (yy: string, mm: string) => (yy && mm ? new Date(Number(yy), Number(mm), 0).getDate() : 31);
  const pick = (ny: string, nm: string, nd: string) => {
    if (nd && Number(nd) > lastDay(ny, nm)) nd = "";                            // 2월 30일처럼 없는 날은 비운다
    setY(ny); setM(nm); setD(nd);
    onChange(ny && nm && nd ? `${ny}-${nm}-${nd}` : "");
  };
  return (
    <span className="flex gap-1">
      <select className="input" name="birth-year" aria-label="태어난 해" value={y} onChange={(e) => pick(e.target.value, m, d)}>
        <option value="">년</option>{years.map((x) => <option key={x} value={x}>{x}</option>)}
      </select>
      <select className="input" name="birth-month" aria-label="태어난 달" value={m} onChange={(e) => pick(y, e.target.value, d)}>
        <option value="">월</option>{Array.from({ length: 12 }, (_, i) => two(i + 1)).map((x) => <option key={x} value={x}>{Number(x)}</option>)}
      </select>
      <select className="input" name="birth-day" aria-label="태어난 날" value={d} onChange={(e) => pick(y, m, e.target.value)}>
        <option value="">일</option>{Array.from({ length: lastDay(y, m) }, (_, i) => two(i + 1)).map((x) => <option key={x} value={x}>{Number(x)}</option>)}
      </select>
    </span>
  );
}

function Section({ title, hint, onAdd, children }: { title: string; hint?: string; onAdd?: () => void; children: React.ReactNode }) {
  return (
    <section className="card space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{title}{hint && <span className="ml-2 text-xs font-normal text-slate-500">{hint}</span>}</h2>
        {onAdd && <button type="button" className="text-sm text-brand-700" onClick={onAdd}>+ 추가</button>}
      </div>
      {children}
    </section>
  );
}

const Del = ({ onClick }: { onClick: () => void }) => (
  <button type="button" className="text-xs text-slate-400 hover:text-red-600" onClick={onClick} aria-label="삭제">삭제</button>
);

/** 표 항목 하나 (줄 추가·삭제) */
function Rows({ sp, rows, setRows, miss }: { sp: Spec; rows: Row[]; setRows: (r: Row[]) => void; miss: string }) {
  const put = (i: number, k: string, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <Section title={sp.title} hint={sp.hint} onAdd={rows.length < sp.max ? () => setRows([...rows, blank(sp)]) : undefined}>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 p-3 md:grid-cols-4">
          {sp.cols.map((c) => (
            <label key={c.k} className={`text-xs text-slate-600 ${c.area || c.max >= 200 ? "col-span-2 md:col-span-4" : ""}`}>{c.label}{c.req && i === 0 && <Req />}
              {c.area
                ? <textarea className={"input h-24" + bad(miss === `${sp.key}-${i}-${c.k}`)} name={`${sp.key}-${i}-${c.k}`} maxLength={c.max} placeholder={c.ph} value={r[c.k] ?? ""} onChange={(e) => put(i, c.k, e.target.value)} />
                : <input className={"input" + bad(miss === `${sp.key}-${i}-${c.k}`)} name={`${sp.key}-${i}-${c.k}`} maxLength={c.max} placeholder={c.ph} value={r[c.k] ?? ""} onChange={(e) => put(i, c.k, e.target.value)} />}
            </label>
          ))}
          <div className="col-span-2 text-right md:col-span-4"><Del onClick={() => setRows(rows.length > 1 ? rows.filter((_, j) => j !== i) : [blank(sp)])} /></div>
        </div>
      ))}
    </Section>
  );
}

export default function Apply() {
  const pid = Number(useParams<{ pid: string }>().pid);
  const router = useRouter();
  const [posting, setPosting] = useState<Posting | null>(null);
  const [me, setMe] = useState(false);
  const [f, setF] = useState<Form>({ gender: "", birth: "", address: "", github: "", role: "", intro: "", intro2: "" });
  const [miss, setMiss] = useState("");          // 제출할 때 처음 비어 있던 필수 칸 (빨간 테두리)
  const [saved, setSaved] = useState("");         // 마지막 임시저장 시각
  const [tables, setTables] = useState<Record<string, Row[]>>(() => Object.fromEntries(SPECS.map((sp) => [sp.key, [blank(sp)]])));
  const [essayQ, setEssayQ] = useState<Essays | null>(null);
  const [essays, setEssays] = useState<Record<string, string>>({});
  const [aiConsent, setAiConsent] = useState<"" | "yes" | "no">(""); // 외부 AI 처리 동의 (필수, 기본값 없음)
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [mine, setMine] = useState<Mine | null | undefined>(undefined); // undefined = 확인 중, null = 아직 지원 안 함
  const [other, setOther] = useState<MyApp | undefined>(undefined); // 다른 공고에 진행 중인 지원

  useEffect(() => {
    api<{ type: string }>("/auth/me?as=candidate").then(
      (m) => (m.type === "candidate" ? setMe(true) : router.push("/login")),
      () => router.push("/login"),
    );
    api<Posting[]>("/site/postings").then((ps) => setPosting(ps.find((p) => p.id === pid) ?? null));
    api<Essays>("/site/essay-questions").then(setEssayQ);
    api<MyApp[]>("/interview/applications").then((a) => setOther(activeElsewhere(a, pid)), () => {});
    api<Mine>(`/site/postings/${pid}/my-application`).then(
      (m) => {
        setMine(m);
        setAiConsent("yes");                          // 제출할 때 이미 동의함
        const r = m.resume;
        setF({ gender: r.성별 ?? "", birth: r.생년월일 ?? "", address: r.주소 ?? "", github: r.Github ?? "", role: r.지원직무 ?? "", intro: r.소개[0] ?? "", intro2: r.소개[1] ?? "" });
        setTables(Object.fromEntries(SPECS.map((sp) => {
          const saved = (r[sp.key] as Row[] | undefined) ?? [];
          return [sp.key, saved.length ? saved.map((x) => ({ ...blank(sp), ...x })) : [blank(sp)]];
        })));
        setEssays(r.자기소개서 ?? {});
      },
      () => {
        setMine(null);
        api<{ form: Draft; saved_at: string }>(`/site/postings/${pid}/draft`).then(({ form, saved_at }) => {   // 쓰다 만 지원서 불러오기
          setF(form.f); setTables(form.tables); setEssays(form.essays);
          setSaved(new Date(saved_at).toLocaleString("ko-KR"));
        }, () => {});
      },
    );
  }, [pid, router]); // eslint-disable-line react-hooks/exhaustive-deps
  const editing = !!mine;

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const filled = (sp: Spec) => tables[sp.key].filter((r) => (r[sp.need] ?? "").trim());

  /** 필수 칸을 화면 순서대로 보고, 처음 빈 칸의 [입력 이름, 안내] */
  function firstMissing(): [string, string] | null {
    if (!f.role.trim()) return ["role", "지원 직무"];
    if (!f.intro.trim()) return ["intro", "소개 첫 줄"];
    if (!(tables["학력사항"][0]?.["학교"] ?? "").trim()) return ["학력사항-0-학교", "학력사항 첫 줄의 학교"];
    const q = essayQ?.questions.find((x) => !(essays[x.key] ?? "").trim());
    if (q) return [`essay-${q.key}`, `자기소개서 '${q.key}'`];
    return aiConsent === "yes" ? null : ["ai_consent", "외부 AI 처리 동의"];
  }

  async function saveDraft() {
    setErr("");
    try {
      const r = await api<{ saved_at: string }>(`/site/postings/${pid}/draft`, { method: "PUT", json: { f, tables, essays } });
      setSaved(new Date(r.saved_at).toLocaleString("ko-KR"));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const m = firstMissing();
    setMiss(m?.[0] ?? "");
    if (m) {                                       // 처음 빈 필수 칸으로 이동
      const el = document.querySelector<HTMLElement>(`[name="${m[0]}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      el?.focus({ preventScroll: true });
      return setErr(m[0] === "ai_consent" && aiConsent === "no"
        ? "외부 AI 처리에 동의하지 않으면 지원서를 제출할 수 없습니다."
        : `필수 항목(*)인 ${m[1]}을(를) ${m[0] === "ai_consent" ? "선택해" : "적어"} 주세요.`);
    }
    if (!confirm(editing ? "고친 내용으로 저장할까요?" : "지원서를 제출할까요? 접수 마감 전까지는 고칠 수 있습니다.")) return;
    setBusy(true);
    setErr("");
    try {
      await api(`/site/postings/${pid}/apply`, {
        method: editing ? "PUT" : "POST",
        json: {
          성별: f.gender || null, 생년월일: f.birth || null, 주소: f.address || null, Github: f.github, 지원직무: f.role, 소개: [f.intro, f.intro2],
          ...Object.fromEntries(SPECS.map((sp) => [sp.key, filled(sp)])),
          자기소개서: essays,
          외부AI동의: aiConsent === "yes",
        },
      });
      router.push("/me/applications");
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 401 ? "로그인이 필요합니다." : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!me || !posting || mine === undefined || !essayQ)
    return <main className="mx-auto max-w-3xl px-6 py-16 text-slate-500">{posting === null && me ? "공고를 찾을 수 없습니다." : "불러오는 중…"}</main>;
  if (!mine && other)
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="card">
          진행 중인 지원(<b>{other.title}</b>)이 있어 다른 공고에 지원할 수 없습니다. {announce(other.final_announce_at)} 결과 발표 뒤에 지원해 주세요.{" "}
          <Link className="text-brand-700" href="/me/applications">지원 현황 보기</Link>
        </p>
      </main>
    );
  if (posting.phase !== "accepting" || (mine && !mine.editable))
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="card">
          {mine ? "접수 마감이 지났거나 심사가 시작되어 지원서를 고칠 수 없습니다." : "지금은 접수 기간이 아닌 공고입니다."}{" "}
          <Link className="text-brand-700" href={mine ? "/me/applications" : "/#jobs"}>{mine ? "지원 현황 보기" : "다른 공고 보기"}</Link>
        </p>
      </main>
    );

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <p className="text-sm text-brand-600">{editing ? "지원서 수정 · 접수 마감 전까지 고칠 수 있습니다" : "지원서 작성"}</p>
      <h1 className="mt-1 text-2xl font-bold">{posting.title}</h1>
      <p className="mt-1 text-sm text-slate-500">접수 마감 {new Date(posting.apply_end).toLocaleString("ko-KR")} · 이름·연락처·이메일은 회원 정보가 들어갑니다</p>
      <p className="mt-1 text-sm text-slate-500"><Req /> 표시는 필수 항목입니다. 다 쓰지 못했으면 아래 <b>임시저장</b>으로 남겨 두고 나중에 이어 쓸 수 있습니다.</p>
      {posting.description && <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-600">{posting.description}</p>}
      <form onSubmit={submit} className="mt-6 space-y-5">
        <Section title="머리말" hint="이력서 맨 위에 보이는 지원 직무와 소개 두 줄">
          <label className="block text-sm">지원 직무<Req /><input className={"input" + bad(miss === "role")} name="role" maxLength={60} placeholder="예: Python 백엔드 개발자 지원" value={f.role} onChange={set("role")} /></label>
          <label className="block text-sm">소개 첫 줄<Req /><input className={"input" + bad(miss === "intro")} name="intro" maxLength={120} placeholder="예: 장애 원인을 측정으로 찾고 고치는 신입입니다." value={f.intro} onChange={set("intro")} /></label>
          <label className="block text-sm">소개 둘째 줄<input className="input" name="intro2" maxLength={120} placeholder="예: 운영 경험을 바탕으로 백엔드 역량을 넓히겠습니다." value={f.intro2} onChange={set("intro2")} /></label>
        </Section>

        <section className="card grid grid-cols-3 gap-3">
          <h2 className="col-span-3 font-semibold">인적사항</h2>
          <label className="text-sm">성별
            <select className="input" name="gender" value={f.gender} onChange={set("gender")}>
              <option value="">선택 안 함</option><option value="여">여</option><option value="남">남</option>
            </select>
          </label>
          <label className="text-sm">생년월일<BirthSelect value={f.birth} onChange={(v) => setF({ ...f, birth: v })} /></label>
          <label className="text-sm">주소 (동까지)<input className="input" name="address" maxLength={100} placeholder="서울특별시 마포구 서교동" value={f.address} onChange={set("address")} /></label>
          <label className="col-span-3 text-sm">Github (없으면 비워 두세요)<input className="input" name="github" maxLength={200} placeholder="https://github.com/아이디" value={f.github} onChange={set("github")} /></label>
          <p className="col-span-3 text-xs text-slate-500">인적사항은 담당자에게만 보이고, AI 평가에는 가린 내용만 들어갑니다.</p>
        </section>

        {SPECS.map((sp) => <Rows key={sp.key} sp={sp} rows={tables[sp.key]} setRows={(r) => setTables({ ...tables, [sp.key]: r })} miss={miss} />)}

        <Section title="자기소개서" hint="네 문항 모두 필수">
          {essayQ.questions.map((q, i) => (
            <label key={q.key} className="block text-sm">
              <span className="font-medium">{i + 1}. {q.key}<Req /></span> <span className="text-slate-500">— {q.question}</span>
              <textarea className={"input mt-1 h-32" + bad(miss === `essay-${q.key}`)} name={`essay-${q.key}`} maxLength={essayQ.max} value={essays[q.key] ?? ""}
                onChange={(e) => setEssays({ ...essays, [q.key]: e.target.value })} />
              <span className="block text-right text-xs text-slate-400">{(essays[q.key] ?? "").length} / {essayQ.max}</span>
            </label>
          ))}
        </Section>

        <Section title="외부 AI 처리 동의" hint="필수 · 거부하면 제출·응시할 수 없습니다">
          <p className="text-sm text-slate-600">
            서류 평가와 2차 AI 면접은 이름·학교·연락처 등을 가린 내용을 국외 AI 서비스(Anthropic 등)로 보내 처리합니다. 사내 보안 문서가 들어간 처리는 국외로 보내지 않습니다.<Req />
          </p>
          <div className={"flex gap-6 text-sm" + bad(miss === "ai_consent")}>
            {(["yes", "no"] as const).map((v) => (
              <label key={v} className="flex items-center gap-1">
                <input type="radio" name="ai_consent" value={v} checked={aiConsent === v} disabled={editing} onChange={() => setAiConsent(v)} />
                {v === "yes" ? "동의합니다" : "동의하지 않습니다"}
              </label>
            ))}
          </div>
          {aiConsent === "no" && <p className="err">동의하지 않으면 지원서를 제출할 수 없습니다.</p>}
        </Section>

        {err && <p className="err">{err}</p>}
        <div className="flex items-center justify-end gap-2">
          {saved && <span className="text-xs text-slate-500">임시저장 {saved}</span>}
          <Link className="btn-line" href="/#jobs">취소</Link>
          {!editing && <button type="button" className="btn-line" onClick={saveDraft}>임시저장</button>}
          <button className="btn" disabled={busy}>{busy ? "저장 중…" : editing ? "수정 저장" : "지원서 제출"}</button>
        </div>
      </form>
    </main>
  );
}
