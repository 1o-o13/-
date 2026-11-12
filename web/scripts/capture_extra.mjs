// E2E에 없는 화면 보충 사진 (11/12): 관리자 로그인 · 관리자 승인 · 이력서 원본 · 글로 답하기 신청(지원자)·승인(관리자).
// 평소 시험 데이터(tasks.ps1 seed) 상태의 운영 화면(localhost:3000)에서 찍는다. 김하늘의 글로 답하기 신청은 찍은 뒤 되돌린다(Python 쪽).
//   node scripts/capture_extra.mjs  → ../records/docs/extra/*.png
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:3000";
const OUT = "../records/docs/extra";
const PW = "Test1234!";
const EMAIL = process.env.CAND_EMAIL ?? "haneul.kim@naver.com";   // 면접 전인 지원자 (11/17: 김하늘이 면접을 마친 상태면 다른 지원자로)
const APP = process.env.CAND_APP ?? "1";
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const shot = async (page, name) => { await page.waitForTimeout(800); await page.screenshot({ path: `${OUT}/${name}.png` }); };

// 지원자: 글로 답하기 신청 → 상태
const cand = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
await cand.goto(`${BASE}/login`);
await cand.fill("input[name=email]", EMAIL);
await cand.fill("input[name=password]", PW);
await cand.getByRole("button", { name: "로그인", exact: true }).click();
await cand.waitForURL((u) => !u.pathname.startsWith("/login"));
await cand.goto(`${BASE}/interview/${APP}/guide`);
await cand.getByRole("button", { name: /신청하기|다시 신청/ }).click();
await cand.getByLabel("신청 사유").fill("발음 장애로 말하기가 어려워 글로 답하고 싶습니다.");
await cand.getByRole("button", { name: "신청", exact: true }).click();
await cand.getByText("담당관 확인 중").waitFor();
await cand.getByRole("heading", { name: /글로 답하기 신청/ }).scrollIntoViewIfNeeded();
await shot(cand, "4-guide-accommodation");

// 관리자
const adm = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
await adm.goto(`${BASE}/admin/login`);
await shot(adm, "1-admin-login");
await adm.getByRole("button", { name: /채용 담당/ }).click();
await adm.waitForURL(/\/admin\/(interviews|postings|documents)/);
await adm.goto(`${BASE}/admin/interviews`);
await adm.getByTestId("accommodations").waitFor();
await shot(adm, "3-accommodation");
await adm.goto(`${BASE}/admin/applicants/1`);
await adm.getByText("인적사항").first().waitFor();
await shot(adm, "2-admin-resume");
await adm.context().clearCookies();
await adm.goto(`${BASE}/admin/login`);
await adm.getByRole("button", { name: /최고관리자/ }).click();
await adm.waitForURL((u) => !u.pathname.endsWith("/login"));
await adm.goto(`${BASE}/admin/users`);
await shot(adm, "5-admin-users");
await browser.close();
console.log("ok");
