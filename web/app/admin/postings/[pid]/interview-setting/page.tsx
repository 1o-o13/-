"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useDevTools } from "@/lib/quick";
import { api, errorText } from "@/lib/api";

type Setting = Record<string, string | number | null> & { locked_at: string | null };

const GROUPS: [string, [string, string][]][] = [
  ["질문 구성", [["total_questions", "총 문항"], ["followup_max_depth", "꼬리질문 최대 깊이"], ["follow_score", "꼬리질문 기준 (이 점수 이상)"], ["retry_score", "재질문 기준 (이 점수 미만, 주제당 1번)"]]],
  ["시간 (초)", [["think_sec_non_tech", "생각 시간 (1·2번)"], ["think_sec_tech", "생각 시간 (3번~)"], ["answer_max_sec", "답변 최대"], ["silence_skip_sec", "침묵 넘김"]]],
  ["평가 배점 (합 100)", [["weight_content", "내용"], ["weight_language", "언어"], ["weight_nonverbal", "비언어"]]],
];
const MODELS: [string, string][] = [["llm_eval_model", "판정"], ["llm_fast_model", "대체 (30초 초과)"], ["llm_local_model", "사내 전용"]];
const EDIT = ["company_requirements", "llm_provider", ...GROUPS.flatMap(([, f]) => f.map(([k]) => k)), ...MODELS.map(([k]) => k)];

// ADM-025 AI 화상면접 설정. 첫 응시가 시작되면 잠겨서 고칠 수 없다
export default function InterviewSetting() {
  const pid = useParams<{ pid: string }>().pid;
  const router = useRouter();
  const dev = useDevTools();   // 개발용 버튼 (.env DEV_QUICK_LOGIN=1)
  const [saved, setSaved] = useState<Setting | null>(null);
  const [f, setF] = useState<Setting | null>(null);
  const [msg, setMsg] = useState("");
  const [role, setRole] = useState("");
  useEffect(() => {
    api<{ role: string }>("/auth/me?as=admin").then((m) => setRole(m.role), () => {});
  }, []);

  /** 개발 전용: 최고관리자가 시험 중 설정을 바꿀 수 있게 잠금을 푼다 (면접 중인 응시가 있으면 서버가 거부) */
  async function unlock() {
    if (!confirm("시험용: 설정 잠금을 풀까요? 이미 끝난 응시 기록은 그대로 두고, 이후 시작하는 응시부터 바뀐 설정을 씁니다.")) return;
    try {
      const s = await api<Setting>(`/admin/postings/${pid}/interview-setting/unlock`, { method: "POST" });
      setSaved(s);
      setF(s);
      setMsg("잠금을 풀었습니다. 설정을 고친 뒤 저장하세요. 다음 응시가 시작되면 다시 잠깁니다.");
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  useEffect(() => {
    api<Setting>(`/admin/postings/${pid}/interview-setting`).then(
      (s) => (setSaved(s), setF(s)),
      (e) => setMsg(errorText(e, router.push, true)),
    );
  }, [pid, router]);

  async function save() {
    const body = Object.fromEntries(EDIT.map((k) => [k, typeof saved![k] === "number" ? Number(f![k]) : f![k]]));
    try {
      const s = await api<Setting>(`/admin/postings/${pid}/interview-setting`, { method: "PUT", json: body });
      setSaved(s);
      setF(s);
      setMsg("저장했습니다.");
    } catch (e) {
      setMsg(errorText(e, router.push, true));
    }
  }

  if (!f) return <p className={msg ? "err" : ""}>{msg || "불러오는 중…"}</p>;
  const locked = !!f.locked_at;
  const sum = Number(f.weight_content) + Number(f.weight_language) + Number(f.weight_nonverbal);
  const field = (k: string, label: string, type = "number") => (
    <label key={k} className="block text-sm">
      {label}
      <input className="input" name={k} type={type} disabled={locked} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
    </label>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">AI 화상면접 설정</h1>
        <div className="flex items-center gap-3">
          <span className={locked ? "text-red-600" : "text-green-700"}>{locked ? `응시 시작됨 · 잠김 (${new Date(f.locked_at!).toLocaleString("ko-KR")})` : "응시 시작 전 · 수정 가능"}</span>
          {locked && role === "super_admin" && dev && (
            <button className="btn-line text-red-600" onClick={unlock}>잠금 해제 (시험용)</button>
          )}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-4">
        {GROUPS.map(([title, fields]) => (
          <div key={title} className="card space-y-2">
            <h2 className="font-semibold">{title}</h2>
            {fields.map(([k, l]) => field(k, l))}
            {title.startsWith("평가") && <p className={sum === 100 ? "text-sm text-slate-500" : "err"}>합계 {sum}</p>}
          </div>
        ))}
      </div>
      <div className="card grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <h2 className="font-semibold">AI 모델</h2>
          {field("llm_provider", "제공자", "text")}
          {MODELS.map(([k, l]) => field(k, l, "text"))}
          <p className="text-xs text-slate-500">내부 문서 근거·해외 전송 미동의면 사내 모델. 진행 중 응시는 시작 때 모델을 끝까지 씀.</p>
        </div>
        <label className="block text-sm">
          회사 요구사항
          <textarea className="input h-40" disabled={locked} value={f.company_requirements ?? ""} onChange={(e) => setF({ ...f, company_requirements: e.target.value })} />
        </label>
      </div>
      <p className="text-xs text-slate-500">질문은 응시마다 이력서·인계 데이터·코딩 약점·회사 문서로 만들어서 질문 목록은 따로 관리하지 않습니다. 재질문 기준은 꼬리질문 기준보다 낮아야 저장됩니다.</p>
      {msg && <p className="text-sm">{msg}</p>}
      <div className="flex justify-end gap-2">
        <button className="btn-line" disabled={locked} onClick={() => setF(saved)}>취소</button>
        <button className="btn" disabled={locked} onClick={save}>저장</button>
      </div>
    </div>
  );
}
