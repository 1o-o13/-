import path from "node:path";
import { defineConfig } from "@playwright/test";

// E2E (stub 모드): compose의 web(3000)·api·worker를 그대로 쓴다. 브라우저는 PC에 설치된 Chrome, 카메라·마이크는 가짜 장치
export default defineConfig({
  testDir: "e2e",
  timeout: 10 * 60_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: "chrome",
    permissions: ["camera", "microphone"],
    // 가짜 마이크 = 녹음해 둔 한국어 답변(e2e/fixtures/answer_ko.wav, Supertonic으로 만든 약 10초, 반복 재생) → 실제 STT·인식 글 확인까지 지난다 (11/11)
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                            `--use-file-for-fake-audio-capture=${path.resolve(__dirname, "e2e/fixtures/answer_ko.wav")}`] },
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
  },
});
