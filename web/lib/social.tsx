"use client";
// 네이버·카카오·구글 간편 가입·로그인 버튼. 앱 키가 없는 제공사는 눌리지 않게 (api/social.py)
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const BUTTONS = [
  ["naver", "네이버로 시작하기", "bg-[#03C75A] text-white hover:brightness-95", "N"],
  ["kakao", "카카오로 시작하기", "bg-[#FEE500] text-[#191919] hover:brightness-95", "K"],
  ["google", "Google로 시작하기", "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50", "G"],
] as const;

export const SOCIAL_ERROR: Record<string, string> = {
  not_ready: "이 간편 로그인은 아직 설정되지 않았습니다.",
  state: "간편 로그인이 취소되었거나 만료되었습니다. 다시 시도해 주세요.",
  provider: "간편 로그인 제공사와 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
  email_exists: "같은 이메일로 이미 가입한 계정이 있습니다. 이메일과 비밀번호로 로그인해 주세요.",
  rejoin_blocked: "탈퇴 때 진행 중이던 공고가 아직 끝나지 않아 다시 가입할 수 없습니다.",
  no_email: "가입하려면 이메일 제공에 동의해야 합니다. 아래 버튼으로 동의 화면을 다시 열어 이메일 항목에 체크해 주세요.",
};

export function SocialButtons() {
  const [ready, setReady] = useState<Record<string, boolean> | null>(null);
  useEffect(() => {
    api<Record<string, boolean>>("/auth/social/providers").then(setReady, () => setReady({}));
  }, []);
  return (
    <div className="space-y-2">
      {BUTTONS.map(([p, label, tone, mark]) => {
        const on = !!ready?.[p];
        return on ? (
          <a key={p} href={`/api/auth/social/${p}/start`} className={`flex h-11 w-full items-center justify-center gap-2 rounded-full font-semibold ${tone}`}>
            <span className="font-black">{mark}</span>
            {label}
          </a>
        ) : (
          <span key={p} title="앱 키가 설정되지 않았습니다 (.env)" className={`flex h-11 w-full cursor-not-allowed items-center justify-center gap-2 rounded-full font-semibold opacity-40 ${tone}`}>
            <span className="font-black">{mark}</span>
            {label} <span className="text-xs font-normal">(키 설정 전)</span>
          </span>
        );
      })}
    </div>
  );
}

export function Divider({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 text-xs text-slate-400">
      <span className="h-px flex-1 bg-slate-200" />
      {text}
      <span className="h-px flex-1 bg-slate-200" />
    </div>
  );
}
