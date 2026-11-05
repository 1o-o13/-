"use client";
// 간편 가입 마무리: 제공사에서 받은 이름·이메일을 확인하고 휴대폰 번호를 넣는다
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { check, formatPhone } from "@/lib/rules";

type Pending = { provider: "naver" | "google" | "kakao"; email: string | null; name: string | null; phone: string | null };
const NAME: Record<string, string> = { naver: "네이버", google: "Google", kakao: "카카오" };

export default function SocialSignup() {
  const router = useRouter();
  const [p, setP] = useState<Pending | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [touched, setTouched] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Pending>("/auth/social/pending").then(
      (d) => (setP(d), setName(d.name ?? ""), setPhone(formatPhone(d.phone ?? ""))),
      (e) => setErr(e.message),
    );
  }, []);

  const errors = { name: check.name(name), phone: check.phone(phone) };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (errors.name || errors.phone) return;
    try {
      await api("/auth/social/complete", { method: "POST", json: { name, phone } });
      router.push("/");
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <main className="px-6 py-16">
      <form onSubmit={submit} className="card mx-auto max-w-sm space-y-4" noValidate>
        <h1 className="text-xl font-bold">간편 가입 마무리</h1>
        {!p && !err && <p className="text-slate-500">불러오는 중…</p>}
        {!p && err && (
          <p className="err">
            {err} <Link className="text-brand-700" href="/signup">회원가입으로</Link>
          </p>
        )}
        {p && (
          <>
            <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-600">
              {NAME[p.provider]} 계정으로 가입합니다.<br />이메일: <b>{p.email ?? "(제공 안 됨)"}</b>
            </p>
            <label className="block text-sm">
              이름
              <input className="input" name="name" value={name} onChange={(e) => setName(e.target.value)} />
              {touched && errors.name && <span className="err">{errors.name}</span>}
            </label>
            <label className="block text-sm">
              휴대폰 번호
              <input className="input" name="phone" type="tel" maxLength={13} placeholder="010-1234-5678" value={phone} onChange={(e) => setPhone(formatPhone(e.target.value))} />
              {touched && errors.phone && <span className="err">{errors.phone}</span>}
            </label>
            {err && <p className="err">{err}</p>}
            <button className="btn w-full">가입 완료</button>
          </>
        )}
      </form>
    </main>
  );
}
