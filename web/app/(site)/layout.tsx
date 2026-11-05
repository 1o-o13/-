import { SiteFooter, SiteHeader } from "@/lib/brand";

// 지원자 사이트: 홈·로그인·회원가입·지원 현황
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SiteHeader />
      {children}
      <SiteFooter />
    </>
  );
}
