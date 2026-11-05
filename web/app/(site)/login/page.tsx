"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { QuickLogin } from "@/lib/quick";
import { Divider, SOCIAL_ERROR, SocialButtons } from "@/lib/social";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [joined, setJoined] = useState(false);
  const [err, setErr] = useState("");
  const [reprompt, setReprompt] = useState(""); // 이메일 제공을 빼고 동의한 제공사 → 동의 화면 다시 열기

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    setJoined(q.has("joined")); // 회원가입 직후 안내
    if (q.get("social_error")) setErr(SOCIAL_ERROR[q.get("social_error")!] ?? "간편 로그인에 실패했습니다.");
    if (q.get("social_error") === "no_email") setReprompt(q.get("provider") ?? "");
    if (q.has("expired")) setErr("1시간 동안 사용하지 않아 로그아웃되었습니다. 다시 로그인해 주세요.");
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/auth/login", { method: "POST", json: { email, password } });
      router.push("/"); // 로그인 뒤에는 홈으로. 지원 현황은 위쪽 메뉴에서
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <main className="mx-auto grid max-w-4xl grid-cols-2 gap-8 px-6 py-16">
      <div className="pt-6">
        <h1 className="text-2xl font-bold text-brand-900">새벽소프트 채용</h1>
        <p className="mt-2 text-slate-600">지원 현황을 확인하고 2차 전형(코딩 테스트·AI 화상면접)에 응시할 수 있습니다.</p>
        <ul className="mt-6 space-y-2 text-sm text-slate-600">
          <li>· 1차(서류) 합격자에게 2차 응시 안내가 열립니다.</li>
          <li>· 면접 점수·판정은 공개하지 않고, 결과는 최종 발표일에 안내합니다.</li>
        </ul>
      </div>
      <form onSubmit={submit} className="card space-y-3">
        <h2 className="text-xl font-bold">지원자 로그인</h2>
        {joined && <p className="rounded-md bg-green-50 p-2 text-sm text-green-700">가입이 완료되었습니다. 로그인해 주세요.</p>}
        <input className="input" name="email" type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="input" name="password" type="password" placeholder="비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {err && <p className="err">{err}</p>}
        {reprompt && (
          <a className="btn-line w-full" href={`/api/auth/social/${reprompt}/start?reprompt=1`}>
            {{ naver: "네이버", kakao: "카카오", google: "구글" }[reprompt] ?? reprompt} 동의 화면 다시 열기
          </a>
        )}
        <button className="btn w-full">로그인</button>
        <Divider text="또는 간편 로그인" />
        <SocialButtons />
        <p className="text-sm">
          처음이신가요? <Link className="text-brand-700" href="/signup">회원가입</Link>
        </p>
        <QuickLogin kind="candidate" />
      </form>
    </main>
  );
}
