"use client";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "@/lib/api";
import { useGuide } from "@/lib/guide";
import { Logo } from "@/lib/brand";
import { mmss } from "@/lib/timer";

// CAN-010 코딩 테스트. 1·2번(기본 등급) → 3번(1·2번 결과로 등급을 정해 새로 출제) 순서. 채점은 서버, 화면에는 통과 수만
type Lang = "python" | "java";
type Counts = { passed: number; total: number; groups: Record<string, string>; compile_error?: string | null };
type Problem = {
  slot: number; statement: string; examples: { input: string; output: string }[]; language: Lang;
  closed: boolean; submissions: number; last: Counts | null;
};
type State = {
  status: string; phase: "q12" | "q3_preparing" | "q3" | "done"; remaining_sec: number; problems: Problem[];
  templates: Record<Lang, string>; runtime: Record<Lang, string>;
};
type RunResult = { compile_error: string | null; results: { input: string; expected: string; output: string; stderr: string; verdict: string; time_ms: number }[] };

const VERDICT: Record<string, string> = { AC: "맞음", WA: "틀림", TLE: "시간 초과", RE: "실행 오류", CE: "컴파일 오류" };
const AUTO_SUBMIT_SEC = 5; // 남은 시간이 이만큼이면 고친 코드를 자동 제출 (임시)

// 브라우저 안 편집기. CDN 대신 설치된 monaco-editor를 쓴다 (외부로 코드가 나가지 않게)
const Editor = dynamic(
  async () => {
    const monaco = await import("monaco-editor");
    (self as any).MonacoEnvironment = {
      getWorker: () => new Worker(new URL("monaco-editor/editor/editor.worker.js", import.meta.url), { type: "module" }),
    };
    const m = await import("@monaco-editor/react");
    m.loader.config({ monaco });
    return m.default;
  },
  { ssr: false, loading: () => <p className="p-4 text-sm text-slate-400">편집기 불러오는 중…</p> },
);

/** 지문 마크다운 일부(# 제목, **굵게**, `코드`, 목록)만 그린다 */
function Statement({ text }: { text: string }) {
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
      p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith("`") ? <code key={i} className="rounded bg-slate-100 px-1">{p.slice(1, -1)}</code> : p,
    );
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {text.split("\n").map((ln, i) =>
        ln.startsWith("# ") ? <h2 key={i} className="text-lg font-bold">{ln.slice(2)}</h2>
        : ln.startsWith("- ") ? <p key={i} className="pl-3">• {inline(ln.slice(2))}</p>
        : ln.trim() === "" ? null : <p key={i}>{inline(ln)}</p>,
      )}
    </div>
  );
}

export default function Coding() {
  const { appId, guide, err: gErr, router } = useGuide();
  const [csid, setCsid] = useState<number | null>(null);
  const [st, setSt] = useState<State | null>(null);
  const [slot, setSlot] = useState(1);
  const [code, setCode] = useState<Record<string, string>>({}); // `${slot}:${lang}` → 코드
  const [lang, setLang] = useState<Record<number, Lang>>({});
  const [left, setLeft] = useState(0);
  const [busy, setBusy] = useState("");
  const [run, setRun] = useState<RunResult | null>(null);
  const [result, setResult] = useState<Counts | null>(null);
  const [err, setErr] = useState("");
  const [paste, setPaste] = useState(0);
  const dirty = useRef<Set<number>>(new Set()); // 마지막 제출 뒤 고친 문항
  const autoDone = useRef(false);

  const key = (s: number, l: Lang) => `${s}:${l}`;
  const store = (id: number) => `coding:${id}`;

  const load = useCallback(async (id: number) => {
    const s = await api<State>(`/coding/sessions/${id}/state`);
    setSt(s);
    setLeft(s.remaining_sec);
    setLang((old) => Object.fromEntries(s.problems.map((p) => [p.slot, old[p.slot] ?? p.language])));
    return s;
  }, []);

  // 시작(이미 시작했으면 같은 응시) → 상태. 고치던 코드는 이 브라우저에 남겨 새로고침해도 이어서 (CT-30)
  useEffect(() => {
    api<{ session_id: number }>(`/coding/applications/${appId}/start`, { method: "POST" })
      .then(async ({ session_id }) => {
        setCsid(session_id);
        setCode(JSON.parse(localStorage.getItem(store(session_id)) ?? "{}"));
        const s = await load(session_id);
        setSlot(s.phase === "q3" ? 3 : 1);
      })
      .catch((e) => setErr(errorText(e, router.push)));
  }, [appId, load, router]);

  useEffect(() => {
    if (csid) localStorage.setItem(store(csid), JSON.stringify(code));
  }, [csid, code]);

  // 남은 시간: 화면에서 1초씩 줄이고, 3번 준비 중에는 3초마다 서버 상태를 다시 본다 (준비 중에는 시간이 멈춤)
  useEffect(() => {
    if (!csid || !st || st.phase === "done") return;
    if (st.phase === "q3_preparing") {
      const t = window.setInterval(() => load(csid).then((s) => s.phase === "q3" && setSlot(3)), 3000);
      return () => clearInterval(t);
    }
    const t = window.setInterval(() => setLeft((x) => Math.max(0, x - 1)), 1000);
    return () => clearInterval(t);
  }, [csid, st, load]);

  const cur = st?.problems.find((p) => p.slot === slot);
  const l: Lang = lang[slot] ?? "python";
  const text = code[key(slot, l)] ?? st?.templates[l] ?? "";

  async function submit(s = slot, quiet = false) {
    if (!csid || !st) return;
    const lg = lang[s] ?? "python";
    if (!quiet) setBusy("submit");
    try {
      const r = await api<Counts>(`/coding/sessions/${csid}/submit`, {
        method: "POST", json: { slot: s, language: lg, code: code[key(s, lg)] ?? st.templates[lg], paste_attempts: paste },
      });
      dirty.current.delete(s);
      if (!quiet) setResult(r), setRun(null);
      await load(csid);
    } catch (e) {
      if (!quiet) setErr(errorText(e, router.push));
    } finally {
      if (!quiet) setBusy("");
    }
  }

  // 시간이 거의 끝나면 고친 문항을 자동 제출하고, 0이 되면 서버가 마감한다 (CT-31)
  useEffect(() => {
    if (!csid || !st || st.phase === "done" || st.phase === "q3_preparing") return;
    if (left <= AUTO_SUBMIT_SEC && !autoDone.current) {
      autoDone.current = true;
      Promise.all([...dirty.current].map((s) => submit(s, true))).then(() => undefined);
    }
    if (left === 0) {
      const t = window.setTimeout(() => load(csid), 1500);
      return () => clearTimeout(t);
    }
  }, [left]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runExamples() {
    if (!csid) return;
    setBusy("run");
    setErr("");
    try {
      setRun(await api<RunResult>(`/coding/sessions/${csid}/run`, { method: "POST", json: { slot, language: l, code: text } }));
      setResult(null);
    } catch (e) {
      setErr(errorText(e, router.push));
    } finally {
      setBusy("");
    }
  }

  async function finish(path: "finish-12" | "finish", msg: string) {
    if (!csid || !confirm(msg)) return;
    setBusy("finish");
    try {
      for (const s of [...dirty.current]) await submit(s, true);
      await api(`/coding/sessions/${csid}/${path}`, { method: "POST" });
      setRun(null);
      setResult(null);
      await load(csid);
    } catch (e) {
      setErr(errorText(e, router.push));
    } finally {
      setBusy("");
    }
  }

  if (gErr) return <p className="err p-6">{gErr}</p>;
  if (err && !st) return <p className="err p-6">{err}</p>;
  if (!guide || !st || !cur && st.phase !== "q3_preparing" && st.phase !== "done") return <p className="p-6">불러오는 중…</p>;

  const header = (
    <header className="flex items-center gap-4 border-b border-slate-200 bg-white px-5 py-2">
      <Logo sub="2차 전형 · 코딩 테스트" />
      <nav className="ml-4 flex gap-1">
        {[1, 2, 3].map((n) => {
          const p = st.problems.find((x) => x.slot === n);
          return (
            <button key={n} disabled={!p} onClick={() => (setSlot(n), setRun(null), setResult(p?.last ?? null))}
              className={`rounded-md px-3 py-1 text-sm ${n === slot ? "bg-brand-600 text-white" : p ? "bg-slate-100" : "bg-slate-50 text-slate-300"}`}>
              {n}번{p?.closed ? " · 제출 끝" : ""}
            </button>
          );
        })}
      </nav>
      <span className={`ml-auto font-mono text-lg ${left < 300 ? "text-red-600" : ""}`} data-testid="coding-timer">
        {st.phase === "q3_preparing" ? "시간 멈춤" : mmss(left)}
      </span>
    </header>
  );

  if (st.phase === "done")
    return (
      <>
        {header}
        <div className="card mx-auto mt-16 max-w-xl space-y-4 text-center">
          <h1 className="text-xl font-bold">코딩 테스트를 마쳤습니다</h1>
          <p className="text-sm text-slate-600">결과는 공개하지 않습니다. 잠시 쉬고 AI 화상면접을 이어서 진행해 주세요.</p>
          <button className="btn" onClick={() => router.push(`/interview/${appId}/ready`)}>AI 화상면접 안내로</button>
        </div>
      </>
    );

  if (st.phase === "q3_preparing")
    return (
      <>
        {header}
        <div className="card mx-auto mt-16 max-w-xl space-y-3 text-center" data-testid="q3-preparing">
          <h1 className="text-xl font-bold">3번 문제를 준비하고 있습니다</h1>
          <p className="text-sm text-slate-600">1·2번 풀이에 맞춘 문제를 만들고 검증하는 중입니다. 몇 분 걸릴 수 있으며, 그동안 남은 시간은 줄지 않습니다.</p>
          <div className="mx-auto h-1.5 w-48 overflow-hidden rounded bg-slate-100"><div className="h-full w-1/3 animate-pulse bg-brand-500" /></div>
        </div>
      </>
    );

  const closed = cur!.closed;
  return (
    <div className="flex h-screen flex-col">
      {header}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(320px,2fr)_3fr]">
        <section className="overflow-y-auto border-r border-slate-200 bg-white p-5">
          <Statement text={cur!.statement} />
          <h3 className="mt-5 text-sm font-bold">예제</h3>
          {cur!.examples.map((e, i) => (
            <div key={i} className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <pre className="overflow-x-auto rounded bg-slate-50 p-2">{e.input}</pre>
              <pre className="overflow-x-auto rounded bg-slate-50 p-2">{e.output}</pre>
            </div>
          ))}
          <p className="mt-4 text-xs text-slate-500">{st.runtime[l]}</p>
        </section>
        <section className="flex min-h-0 flex-col">
          <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm">
            <select value={l} disabled={closed} onChange={(e) => setLang({ ...lang, [slot]: e.target.value as Lang })}
              className="rounded border border-slate-300 px-2 py-1" aria-label="언어">
              <option value="python">Python 3</option>
              <option value="java">Java 21</option>
            </select>
            <span className="text-xs text-slate-500">제출 {cur!.submissions}번 · 제출은 몇 번이든 가능, 가장 좋은 제출로 채점 · 붙여넣기 막힘</span>
            <button className="btn-line ml-auto" disabled={closed || !!busy} onClick={runExamples}>{busy === "run" ? "실행 중…" : "예제 실행"}</button>
            <button className="btn" disabled={closed || !!busy} onClick={() => submit()}>{busy === "submit" ? "채점 중…" : "제출"}</button>
          </div>
          <div className="min-h-0 flex-1">
            <Editor
              height="100%"
              language={l}
              value={text}
              options={{ readOnly: closed, minimap: { enabled: false }, fontSize: 14, scrollBeyondLastLine: false, tabSize: 4 }}
              onChange={(v) => (setCode((c) => ({ ...c, [key(slot, l)]: v ?? "" })), dirty.current.add(slot))}
              onMount={(ed) => {
                // 붙여넣기는 막고 시도 횟수만 기록 (F-SYS-18)
                ed.getDomNode()?.addEventListener("paste", (e) => (e.preventDefault(), e.stopPropagation(), setPaste((n) => n + 1)), true);
              }}
            />
          </div>
          <div className="max-h-[38%] overflow-y-auto border-t border-slate-200 bg-white p-3 text-sm" data-testid="coding-result">
            {err && <p className="err">{err}</p>}
            {run?.compile_error && <pre className="whitespace-pre-wrap text-xs text-red-600">{run.compile_error}</pre>}
            {run?.results.map((r, i) => (
              <div key={i} className="mb-2">
                <b className={r.verdict === "AC" ? "text-emerald-600" : "text-red-600"}>예제 {i + 1}: {VERDICT[r.verdict] ?? r.verdict}</b>
                <span className="ml-2 text-xs text-slate-500">{r.time_ms}ms</span>
                {r.verdict !== "AC" && (
                  <pre className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">내 출력:{"\n"}{r.output || "(없음)"}{r.stderr && `\n오류:\n${r.stderr}`}</pre>
                )}
              </div>
            ))}
            {(result ?? (!run ? cur!.last : null)) && (() => {
              const r = (result ?? cur!.last)!;
              return (
                <div>
                  <b>{result ? "제출 결과" : "마지막 제출"}: 채점 케이스 {r.passed}/{r.total} 통과</b>
                  {r.compile_error && <pre className="mt-1 whitespace-pre-wrap text-xs text-red-600">{r.compile_error}</pre>}
                  <p className="mt-1 text-xs text-slate-500">
                    입력 크기별: {Object.entries(r.groups).map(([g, v]) => `${g}단계 ${v}`).join(" · ")}
                  </p>
                </div>
              );
            })()}
            {!run && !result && !cur!.last && !err && <p className="text-slate-400">예제 실행이나 제출 결과가 여기 나옵니다.</p>}
          </div>
          <div className="flex justify-end border-t border-slate-200 bg-slate-50 px-3 py-2">
            {st.phase === "q12" ? (
              <button className="btn" disabled={!!busy} onClick={() => finish("finish-12", "1·2번을 끝내면 다시 고칠 수 없습니다. 3번으로 넘어갈까요?")}>
                1·2번 끝내고 3번으로
              </button>
            ) : (
              <button className="btn" disabled={!!busy} onClick={() => finish("finish", "3번을 끝내면 코딩 테스트가 종료됩니다. 끝낼까요?")}>
                코딩 테스트 끝내기
              </button>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
