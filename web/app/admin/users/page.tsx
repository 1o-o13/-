"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";

type Pending = { id: number; login_id: string; name: string; role: string; department: string | null; created_at: string };
const ROLE: Record<string, string> = { recruiter: "채용 담당", dept_member: "부서원", sys_admin: "시스템 관리자" };

// 관리자 승인 (최고관리자만). 승인하면 로그인 가능, 채용 담당은 2단계 인증 비밀값을 한 번만 보여 준다
export default function AdminUsers() {
  const router = useRouter();
  const [rows, setRows] = useState<Pending[]>([]);
  const [msg, setMsg] = useState("");
  const [secret, setSecret] = useState<{ login_id: string; value: string } | null>(null);

  const load = useCallback(() => api<Pending[]>("/admin/users/pending").then(setRows, (e) => setMsg(errorText(e, router.push, true))), [router]);
  useEffect(() => {
    load();
  }, [load]);

  async function approve(u: Pending) {
    const r = await api<{ totp_secret: string | null }>(`/admin/users/${u.id}/approve`, { method: "POST" }).catch((e) => (setMsg(e.message), null));
    if (!r) return;
    setMsg(`${u.name}(${u.login_id}) 계정을 승인했습니다.`);
    setSecret(r.totp_secret ? { login_id: u.login_id, value: r.totp_secret } : null);
    load();
  }

  async function reject(u: Pending) {
    if (!confirm(`${u.name}(${u.login_id}) 신청을 거절할까요? 신청 내용이 지워집니다.`)) return;
    await api(`/admin/users/${u.id}/reject`, { method: "POST" }).then(() => setMsg(`${u.name} 신청을 거절했습니다.`), (e) => setMsg(e.message));
    setSecret(null);
    load();
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">관리자 승인</h1>
      {msg && <p className="text-sm">{msg}</p>}
      {secret && (
        <div className="card space-y-1 border-amber-300 bg-amber-50 text-sm">
          <p className="font-semibold">{secret.login_id}의 2단계 인증 비밀값 (지금 한 번만 보여 줍니다)</p>
          <p className="font-mono text-lg">{secret.value}</p>
          <p>본인에게 전달해 Google Authenticator 등 인증 앱에 등록하게 하세요.</p>
        </div>
      )}
      <table className="card w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr><th>아이디</th><th>이름</th><th>역할</th><th>부서</th><th>신청 시각</th><th></th></tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.id} className="border-t border-slate-100">
              <td>{u.login_id}</td>
              <td>{u.name}</td>
              <td>{ROLE[u.role] ?? u.role}</td>
              <td>{u.department ?? "-"}</td>
              <td>{new Date(u.created_at).toLocaleString("ko-KR")}</td>
              <td className="space-x-2 py-1 text-right">
                <button className="btn" onClick={() => approve(u)}>승인</button>
                <button className="btn-line" onClick={() => reject(u)}>거절</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={6} className="py-4 text-center text-slate-500">승인 대기 중인 신청이 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
