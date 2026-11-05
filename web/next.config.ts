import type { NextConfig } from "next";

// 화면과 API를 같은 주소로 묶는다 (HttpOnly 쿠키가 그대로 오가도록). API_URL: 로컬 http://localhost:8000, compose는 http://api:8000
const config: NextConfig = {
  // SSE(다음 질문 알림)가 gzip 버퍼에 묶여 늦게 오지 않도록 Next.js 압축을 끈다. 운영 압축은 앞단(nginx)에서
  compress: false,
  // 빌드 결과 폴더: web/scripts/serve.mjs가 .build/a·.build/b를 번갈아 써서 끊김 없이 새 화면으로 바꾼다 (없으면 .next, 개발 서버·시험)
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // 1~3번 질문 준비(사내 모델 LLM 3번)가 중계 기본 제한 30초를 넘을 수 있어 늘린다 (판정 60초 규칙과 같은 여유)
  experimental: { proxyTimeout: 90_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.API_URL ?? "http://localhost:8000"}/api/:path*` }];
  },
};

export default config;
