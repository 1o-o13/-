"use client";
import { usePathname } from "next/navigation";
import { Logo } from "@/lib/brand";

// 응시 화면(안내·점검·안내·완료): 집중을 위해 메뉴 없이 로고만. 면접실(live)은 화면 전체를 어두운 방으로 쓴다
export default function InterviewLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  if (path.endsWith("/live") || path.endsWith("/coding")) return children; // 코딩 화면은 자기 머리줄(문항·남은 시간)을 쓴다
  return (
    <>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center px-6 py-3">
          <Logo sub="2차 전형 · AI 화상면접" />
        </div>
      </header>
      <main className="mx-auto max-w-5xl p-6">{children}</main>
    </>
  );
}
