"use client";
// 내 정보: 이름·휴대폰 수정, 비밀번호 변경, 간편 로그인 연결, 회원 탈퇴
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorText } from "@/lib/api";
import { check, formatPhone } from "@/lib/rules";

type Profile = { email: string; name: string; phone: string; has_password: boolean; created_at: string; social: string[]; rejoin_block_if_withdraw: string | null };
const SOCIAL: Record<string, string> = { naver: "네이버", google: "Google", kakao: "카카오" };

export default function MyInfo() {
  const router = useRouter();
  const [p, setP] = useState<Profile | null>(null);
  const [info, setInfo] = useState({ name: "", phone: "" });
  const [pw, setPw] = useState({ current: "", new: "", again: "" });
  const [bye, setBye] = useState({ open: false, password: "", confirm: "" });
  const [msg, setMsg] = useState<Record<string, string>>({});
  const note = (k: string, v: string) => setMsg((m) => ({ ...m, [k]: v }));

  useEffect(() => {
    api<Profile>("/auth/me/profile").then(
      (d) => (setP(d), setInfo({ name: d.name, phone: d.phone })),
      (e) => note("load", errorText(e, router.push)),
    );
  }, [router]);

  async function saveInfo(e: React.FormEvent) {
    e.preventDefault();
    const bad = check.name(info.name) || check.phone(info.phone);
    if (bad) return note("info", bad);
    await api("/auth/me/profile", { method: "PUT", json: info }).then(() => note("info", "저장했습니다."), (e) => note("info", e.message));
  }

  async function savePw(e: React.FormEvent) {
    e.preventDefault();
    if (pw.new !== pw.again) return note("pw", "새 비밀번호가 서로 다릅니다.");
    const bad = check.password(pw.new);
    if (bad) return note("pw", bad);
    await api("/auth/me/password", { method: "PUT", json: { current: pw.current, new: pw.new } }).then(
      () => (setPw({ current: "", new: "", again: "" }), note("pw", "비밀번호를 바꿨습니다.")),
      (e) => note("pw", e.message),
    );
  }

  async function withdraw(e: React.FormEvent) {
    e.preventDefault();
    if (!confirm(`정말 탈퇴할까요? ${rejoinText}`)) return;
    await api("/auth/me/withdraw", { method: "POST", json: p!.has_password ? { password: bye.password } : { confirm: bye.confirm } }).then(
      () => router.push("/?bye=1"),
      (e) => note("bye", e.message),
    );
  }

  if (!p) return <main className="mx-auto max-w-2xl px-6 py-16 text-slate-500">{msg.load || "불러오는 중…"}</main>;
  // 재가입 제한: 진행 중인 지원이 있으면 그 공고의 최종 발표일까지 (같은 공고 중복 지원 방지), 없으면 바로 다시 가입 가능
  const rejoinText = p.rejoin_block_if_withdraw
    ? `진행 중인 지원서는 지원 취소되고, 그 공고가 끝나는 ${new Date(p.rejoin_block_if_withdraw).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })}까지 다시 가입할 수 없습니다.`
    : "진행 중인 지원이 없어 탈퇴한 뒤 바로 다시 가입할 수 있습니다.";
  return (
    <main className="mx-auto max-w-2xl space-y-5 px-6 py-10">
      <div className="flex items-end justify-between">
        <h1 className="text-2xl font-bold">내 정보</h1>
        <Link className="text-sm text-brand-700" href="/me/applications">지원 현황 보기 →</Link>
      </div>

      <form onSubmit={saveInfo} className="card space-y-3">
        <h2 className="font-semibold">기본 정보</h2>
        <p className="text-sm text-slate-600">이메일 <b className="ml-2 text-slate-900">{p.email}</b> <span className="ml-2 text-xs text-slate-400">이메일은 바꿀 수 없습니다</span></p>
        <label className="block text-sm">이름<input className="input" name="name" value={info.name} onChange={(e) => setInfo({ ...info, name: e.target.value })} /></label>
        <label className="block text-sm">휴대폰 번호<input className="input" name="phone" type="tel" maxLength={13} value={info.phone} onChange={(e) => setInfo({ ...info, phone: formatPhone(e.target.value) })} /></label>
        <p className="text-xs text-slate-500">이미 낸 지원서에는 제출할 때의 정보가 남습니다. 접수 중인 공고라면 지원서 수정에서 다시 저장해 주세요.</p>
        {msg.info && <p className="text-sm text-brand-700">{msg.info}</p>}
        <div className="text-right"><button className="btn">저장</button></div>
      </form>

      <section className="card space-y-2">
        <h2 className="font-semibold">간편 로그인 연결</h2>
        <p className="text-sm text-slate-600">{p.social.length ? p.social.map((s) => SOCIAL[s]).join(", ") + " 계정과 연결되어 있습니다." : "연결된 간편 로그인이 없습니다."}</p>
      </section>

      {p.has_password && (
        <form onSubmit={savePw} className="card space-y-3">
          <h2 className="font-semibold">비밀번호 바꾸기</h2>
          <input className="input" name="current" type="password" placeholder="지금 비밀번호" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          <input className="input" name="new" type="password" maxLength={13} placeholder="새 비밀번호 (영문·숫자·특수문자 포함 8~13자)" value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} />
          <input className="input" name="again" type="password" maxLength={13} placeholder="새 비밀번호 다시" value={pw.again} onChange={(e) => setPw({ ...pw, again: e.target.value })} />
          {msg.pw && <p className="text-sm text-brand-700">{msg.pw}</p>}
          <div className="text-right"><button className="btn" disabled={!pw.current || !pw.new}>비밀번호 바꾸기</button></div>
        </form>
      )}

      <section className="card space-y-3 border-red-100">
        <h2 className="font-semibold text-red-700">회원 탈퇴</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>탈퇴하면 로그인할 수 없고, 진행 중인 지원서는 모두 <b>지원 취소</b>됩니다.</li>
          <li data-testid="rejoin-note">{rejoinText}</li>
          <li>지원 기록과 개인정보는 1년 동안 보관한 뒤 지웁니다. 같은 이메일로 다시 가입하면 예전 기록이 이어져, 이미 지원했던 공고에는 다시 지원할 수 없습니다.</li>
          <li>AI 화상면접 응시 중에는 탈퇴할 수 없습니다.</li>
        </ul>
        {!bye.open ? (
          <button className="btn-line text-red-600" onClick={() => setBye({ ...bye, open: true })}>탈퇴하기</button>
        ) : (
          <form onSubmit={withdraw} className="space-y-2">
            {p.has_password ? (
              <input className="input" name="withdraw_password" type="password" placeholder="본인 확인을 위해 비밀번호를 입력하세요" value={bye.password} onChange={(e) => setBye({ ...bye, password: e.target.value })} />
            ) : (
              <input className="input" name="withdraw_confirm" placeholder="간편 가입 계정입니다. '탈퇴'를 입력하세요" value={bye.confirm} onChange={(e) => setBye({ ...bye, confirm: e.target.value })} />
            )}
            {msg.bye && <p className="err">{msg.bye}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-line" onClick={() => setBye({ open: false, password: "", confirm: "" })}>취소</button>
              <button className="btn bg-red-600 hover:bg-red-500">회원 탈퇴</button>
            </div>
          </form>
        )}
      </section>
    </main>
  );
}
