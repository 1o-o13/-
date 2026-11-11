"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { check } from "@/lib/rules";

type Dept = { id: number; name: string };

// 관리자 가입 신청 → 최고관리자가 승인하면 로그인 (채용 담당은 승인 때 받은 2단계 인증 비밀값을 인증 앱에 등록)
export default function AdminSignup() {
  const [depts, setDepts] = useState<Dept[]>([]);
  const [f, setF] = useState({ login_id: "", password: "", name: "", role: "recruiter", department_id: "" });
  const [touched, setTouched] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Dept[]>("/auth/departments").then(setDepts, () => {});
  }, []);

  const errors = { login_id: check.loginId(f.login_id), name: check.name(f.name), password: check.password(f.password), department_id: f.department_id ? "" : "부서를 골라 주세요" };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (Object.values(errors).some(Boolean)) return;
    try {
      await api("/auth/admin/signup", { method: "POST", json: { ...f, department_id: Number(f.department_id) } });
      setDone(true);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (done)
    return (
      <div className="card mx-auto mt-16 max-w-sm space-y-3 text-center">
        <h1 className="text-xl font-bold">가입 신청을 보냈습니다</h1>
        <p>최고관리자가 승인하면 로그인할 수 있습니다.</p>
        <Link className="btn inline-block" href="/admin/login">로그인 화면으로</Link>
      </div>
    );

  const field = (k: "login_id" | "name" | "password", label: string, hint: string, type = "text") => (
    <label className="block text-sm">
      {label}
      <input className="input" name={k} type={type} placeholder={hint} maxLength={k === "password" ? 13 : 20} value={f[k]} onChange={set(k)} />
      {touched && errors[k] && <span className="err">{errors[k]}</span>}
    </label>
  );

  return (
    <form onSubmit={submit} className="card mx-auto mt-16 max-w-sm space-y-3" noValidate>
      <h1 className="text-xl font-bold">관리자 가입 신청</h1>
      {field("login_id", "아이디", "영문 소문자로 시작, 4~20자")}
      {field("name", "이름", "한글 2~17자 또는 영문")}
      {field("password", "비밀번호", "영문·숫자·특수문자 포함 8~13자", "password")}
      <label className="block text-sm">
        역할
        <select className="input" name="role" value={f.role} onChange={set("role")}>
          <option value="recruiter">채용 담당</option>
          <option value="dept_member">부서원 (조회만)</option>
        </select>
      </label>
      <label className="block text-sm">
        부서
        <select className="input" name="department_id" value={f.department_id} onChange={set("department_id")}>
          <option value="">고르기</option>
          {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        {touched && errors.department_id && <span className="err">{errors.department_id}</span>}
      </label>
      {err && <p className="err">{err}</p>}
      <button className="btn w-full">신청하기</button>
    </form>
  );
}
