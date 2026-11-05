"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { RulesList, useGuide } from "@/lib/guide";

// CAN-011 안내사항 (쉬는 시간). 열리면 서버가 1~3번 질문을 미리 만든다
export default function Ready() {
  const { appId, guide, err: gErr, router } = useGuide();
  const [prepared, setPrepared] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!guide) return;
    if (guide.coding_required && guide.coding_status !== "completed") return router.replace(`/interview/${appId}/coding`); // 코딩 먼저
    api(`/interview/applications/${appId}/prepare`, { method: "POST" }).then(
      () => setPrepared(true),
      (e) => setErr(e.message),
    );
  }, [appId, guide, router]);

  async function start() {
    try {
      await api(`/interview/applications/${appId}/start`, { method: "POST" });
      router.push(`/interview/${appId}/live`);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (gErr) return <p className="err">{gErr}</p>;
  if (!guide) return <p>불러오는 중…</p>;
  return (
    <div className="card mx-auto mt-10 max-w-2xl space-y-4 text-center">
      <h1 className="text-xl font-bold">준비가 되면 AI 화상면접을 시작하세요</h1>
      <div className="text-left">
        <RulesList r={guide.rules} />
      </div>
      {err && <p className="err">{err}</p>}
      <button className="btn" disabled={!prepared} onClick={start}>
        {prepared ? "AI 화상면접 시작" : "질문 준비 중…"}
      </button>
    </div>
  );
}
