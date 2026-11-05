"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { check, formatPhone } from "@/lib/rules";
import { Divider, SocialButtons } from "@/lib/social";

// 임시 회원가입 (공통 기반 파트가 휴대폰 본인인증·약관 동의를 붙인 정식 화면으로 바꿈)
const FIELDS = [
  ["name", "이름", "한글 2~17자 또는 영문", "text"],
  ["email", "이메일", "네이버·구글 등 실제 쓰는 메일", "email"],
  ["phone", "휴대폰 번호", "010-1234-5678", "tel"],
  ["password", "비밀번호", "영문·숫자·특수문자 포함 8~13자", "password"],
] as const;

export default function Signup() {
  const router = useRouter();
  const [f, setF] = useState({ email: "", password: "", name: "", phone: "" });
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState("");
  const errors = { name: check.name(f.name), email: check.email(f.email), phone: check.phone(f.phone), password: check.password(f.password) };
  const ok = Object.values(errors).every((e) => !e);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ name: true, email: true, phone: true, password: true });
    if (!ok) return;
    try {
      await api("/auth/signup", { method: "POST", json: f });
      router.push("/login?joined=1"); // 가입 완료 → 로그인 화면 (A-01)
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <main className="px-6 py-16">
    <form onSubmit={submit} className="card mx-auto max-w-sm space-y-3" noValidate>
      <h1 className="text-xl font-bold">회원가입</h1>
      <SocialButtons />
      <Divider text="또는 이메일로 가입" />
      {FIELDS.map(([k, label, hint, type]) => (
        <label key={k} className="block text-sm">
          {label}
          <input
            className="input"
            name={k}
            type={type}
            placeholder={hint}
            maxLength={k === "password" ? 13 : k === "phone" ? 13 : undefined}
            value={f[k]}
            onChange={(e) => setF({ ...f, [k]: k === "phone" ? formatPhone(e.target.value) : e.target.value })}
            onBlur={() => setTouched({ ...touched, [k]: true })}
            required
          />
          {touched[k] && errors[k] && <span className="err">{errors[k]}</span>}
        </label>
      ))}
      {err && <p className="err">{err}</p>}
      <button className="btn w-full">가입하기</button>
      <p className="text-sm">
        이미 가입했나요? <Link className="text-brand-700" href="/login">로그인</Link>
      </p>
    </form>
    </main>
  );
}
