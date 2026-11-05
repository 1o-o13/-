"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { QuickLogin } from "@/lib/quick";

export default function AdminLogin() {
  const router = useRouter();
  const [f, setF] = useState({ login_id: "", password: "", otp: "" });
  const [err, setErr] = useState("");
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/auth/admin/login", { method: "POST", json: { ...f, otp: f.otp || null } });
      router.push("/admin/interviews");
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <form onSubmit={submit} className="card mx-auto mt-16 max-w-sm space-y-3">
      <h1 className="text-xl font-bold">관리자 로그인</h1>
      <input className="input" name="login_id" placeholder="아이디" value={f.login_id} onChange={set("login_id")} required />
      <input className="input" name="password" type="password" placeholder="비밀번호" value={f.password} onChange={set("password")} required />
      <input className="input" name="otp" inputMode="numeric" placeholder="인증 코드 6자리 (2단계 인증)" value={f.otp} onChange={set("otp")} />
      {err && <p className="err">{err}</p>}
      <button className="btn w-full">로그인</button>
      <p className="text-sm">
        계정이 없나요? <Link className="text-brand-700" href="/admin/signup">관리자 가입 신청</Link>
      </p>
      <QuickLogin kind="admin" />
    </form>
  );
}
