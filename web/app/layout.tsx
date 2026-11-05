import "./globals.css";

export const metadata = { title: "새벽소프트 채용", description: "(가상 회사) 새벽소프트 채용 사이트 · AI 화상면접" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
