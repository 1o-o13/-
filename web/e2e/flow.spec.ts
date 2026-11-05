// 단계 5 E2E (stub 모드): 신규 가입·로그인 → 관리자 설정 수정 → cand01 안내·점검·시작·10문항·완료 → 설정 잠김 → hr01 확인·확정 → 2차 종합 점수.
// 실행 전 tasks.ps1 seed로 DB를 처음 상태로 둔다 (tasks.ps1 e2e가 같이 함). 단계별 스크린샷: e2e/screenshots/
import { expect, type Page, test } from "@playwright/test";
import { totp } from "./totp";

const PW = "Test1234!";
const SECRET = "JBSWY3DPEHPK3PXP"; // 시험 전용 (seed/test_data.sql)
let n = 0;
// full=false: 화면 한 장 크기만 (표가 긴 화면은 전체를 찍으면 공유 페이지에서 글씨가 너무 작아짐)
const shot = async (page: Page, name: string, full = true) => {
  if (!full) await page.evaluate(() => window.scrollTo(0, 0));   // 화면 한 장은 맨 위(제목·확정 버튼)부터
  await page.screenshot({ path: `e2e/screenshots/${String(++n).padStart(2, "0")}-${name}.png`, fullPage: full });
};

async function candidateLogin(page: Page, email: string, pw = PW) {
  await page.goto("/login");
  await page.fill("input[name=email]", email);
  await page.fill("input[name=password]", pw);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByRole("link", { name: "지원 현황", exact: true })).toBeVisible(); // 로그인 뒤 홈 → 위쪽 메뉴의 지원 현황
  await page.getByRole("link", { name: "지원 현황", exact: true }).click();
  await expect(page).toHaveURL(/\/me\/applications/);
}

async function adminLogin(page: Page) {
  await page.goto("/admin/login");
  await page.fill("input[name=login_id]", "hr01");
  await page.fill("input[name=password]", PW);
  await page.fill("input[name=otp]", totp(SECRET));
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/interviews/);
}

test.describe.serial("2차 AI 화상면접 전체 흐름", () => {
  test("채용 홈 (가상 회사 새벽소프트)", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "채용 공고" })).toBeVisible();
    await expect(page.locator("[data-testid=current-postings] article")).toHaveCount(4); // 접수·진행 중 4개를 한 번에 (11/17)
    await expect(page.getByRole("button", { name: /더보기/ })).toHaveCount(0);          // 4개 이하면 더보기 없음
    await expect(page.getByTestId("footer-contact")).toContainText("02-000-0000");      // 맨 밑 담당자 연락처
    await shot(page, "home");
    await expect(page.getByText("2026 하반기 백엔드 신입")).toBeVisible();
    await expect(page.getByTestId("past-postings")).toHaveCount(0); // 지난 공고는 접혀 있음
    await page.getByRole("button", { name: /지난 공고 1개 보기/ }).click();
    await expect(page.locator("[data-testid=past-postings] article")).toHaveCount(1);
    await page.goto("/signup");
    await expect(page.getByText("네이버로 시작하기")).toBeVisible(); // 간편 가입 버튼 (키 설정 전이라 꺼짐)
    await shot(page, "signup-social");
  });

  test("신규 가입 → 로그인 확인 (E-03: 1차·코딩 전이라 응시 버튼 없음) → 내 정보 → 회원 탈퇴", async ({ page }) => {
    const email = `e2e${Date.now()}@gmail.com`;
    await page.goto("/signup");
    await page.fill("input[name=email]", email);
    await page.fill("input[name=password]", "Passw0rd!");
    await page.fill("input[name=name]", "시험가입자");
    await page.fill("input[name=phone]", "01099990000"); // 숫자만 넣어도 010-9999-0000으로
    await shot(page, "signup");
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page.getByText("가입이 완료되었습니다")).toBeVisible(); // A-01 가입 → 로그인 화면
    await page.fill("input[name=email]", email);
    await page.fill("input[name=password]", "Passw0rd!");
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page).toHaveURL(/\/$/); // 로그인 뒤 홈
    await page.getByRole("link", { name: "지원 현황", exact: true }).click();
    await expect(page.getByText("지원한 공고가 없습니다.")).toBeVisible();
    await expect(page.getByRole("link", { name: "2차 응시 안내" })).toHaveCount(0);
    await shot(page, "signup-login");
    await expect(page.getByTestId("login-left")).toContainText(/5\d:\d\d|60:00/); // 로그인 유지 1시간
    // 내 정보 → 휴대폰 번호 바꾸기 → 회원 탈퇴
    await page.getByRole("link", { name: "내 정보" }).click();
    await page.fill("input[name=phone]", "01088887777");
    await page.getByRole("button", { name: "저장", exact: true }).click();
    await expect(page.getByText("저장했습니다.")).toBeVisible();
    await shot(page, "my-info");
    page.on("dialog", (d) => d.accept());
    await expect(page.getByTestId("rejoin-note")).toContainText("바로 다시 가입할 수 있습니다"); // 진행 중인 지원이 없음
    await page.getByRole("button", { name: "탈퇴하기" }).click();
    await page.fill("input[name=withdraw_password]", "Passw0rd!");
    await page.getByRole("button", { name: "회원 탈퇴" }).click();
    await expect(page.getByText("회원 탈퇴가 끝났습니다")).toBeVisible();
    await page.goto("/login");
    await page.fill("input[name=email]", email);
    await page.fill("input[name=password]", "Passw0rd!");
    await page.getByRole("button", { name: "로그인", exact: true }).click();
    await expect(page.getByText("이메일 또는 비밀번호가 맞지 않습니다")).toBeVisible(); // 탈퇴한 계정은 로그인 안 됨
    // 진행 중인 지원이 없었으니 같은 이메일로 바로 다시 가입된다
    await page.goto("/signup");
    await page.fill("input[name=email]", email);
    await page.fill("input[name=password]", "Again123!");
    await page.fill("input[name=name]", "다시가입");
    await page.fill("input[name=phone]", "01055554444");
    await page.getByRole("button", { name: "가입하기" }).click();
    await expect(page.getByText("가입이 완료되었습니다")).toBeVisible();
  });

  test("아직 지원 안 한 지원자: 홈 → 지원하기 → 지원서 제출 → 서류 심사 중 → 마감 전 수정", async ({ page }) => {
    page.on("dialog", (d) => d.accept()); // '제출할까요?' 확인
    await page.goto("/login");
    await page.getByRole("button", { name: /박지민/ }).click();
    await expect(page).toHaveURL(/\/$/); // 로그인 뒤 홈
    await page.getByRole("link", { name: "지원하기" }).first().click();
    await expect(page).toHaveURL(/\/jobs\/\d+\/apply/);
    await page.selectOption("select[name=gender]", "여");
    await page.selectOption("select[name=birth-year]", "2000");          // 생년월일: 년·월·일 선택 (일은 그 달 마지막 날까지만)
    await page.selectOption("select[name=birth-month]", "02");
    await expect(page.locator("select[name=birth-day] option")).toHaveCount(30);   // '일' + 1~29 (2000년 2월)
    await page.selectOption("select[name=birth-day]", "17");
    await page.fill("input[name=address]", "경기도 성남시 분당구 정자동");
    // 필수 칸을 비운 채 제출 → 처음 빈 필수 칸(지원 직무)으로 이동
    await page.getByRole("button", { name: "지원서 제출" }).click();
    await expect(page.getByText(/필수 항목\(\*\)인 지원 직무/)).toBeVisible();
    await expect(page.locator("input[name=role]")).toBeFocused();
    await page.fill("input[name=role]", "Python 데이터 백엔드 개발자 지원");
    await page.getByRole("button", { name: "임시저장" }).click();
    await expect(page.getByText(/^임시저장 /)).toBeVisible();
    await page.reload();                                                    // 임시저장한 내용이 다시 채워진다
    await expect(page.locator("input[name=role]")).toHaveValue("Python 데이터 백엔드 개발자 지원");
    await expect(page.locator("select[name=birth-day]")).toHaveValue("17");
    await page.fill("input[name=intro]", "데이터가 믿을 수 있게 흐르도록 만드는 일을 하고 싶습니다.");
    await page.fill('input[name="학력사항-0-학교"]', "가람대학교");
    await page.fill('input[name="학력사항-0-학과"]', "컴퓨터공학과");
    await page.fill('input[name="학력사항-0-상태"]', "졸업");
    await page.fill('input[name="보유기술-0-분야"]', "데이터 처리");
    await page.fill('input[name="보유기술-0-기술내역"]', "Python, Spark, SQL");
    for (const k of ["지원동기", "기술수행경험 및 문제해결경험", "입사후포부", "성격의 장/단점"])   // 자기소개서 4문항 (팀 이력서 양식, 모두 필수)
      await page.fill(`textarea[name="essay-${k}"]`, `${k}: 데이터 파이프라인을 직접 만들며 배운 점을 적습니다.`);
    // 외부 AI 처리 동의는 필수 (기본값 없음): 고르지 않거나 거부하면 제출되지 않는다
    await page.getByRole("button", { name: "지원서 제출" }).click();
    await expect(page.getByText(/외부 AI 처리 동의을\(를\) 선택해/)).toBeVisible();
    await page.check("input[name=ai_consent][value=no]");
    await page.getByRole("button", { name: "지원서 제출" }).click();
    await expect(page.getByText("외부 AI 처리에 동의하지 않으면 지원서를 제출할 수 없습니다.")).toBeVisible();
    await page.check("input[name=ai_consent][value=yes]");
    await shot(page, "apply-form");
    await page.getByRole("button", { name: "지원서 제출" }).click();
    await expect(page).toHaveURL(/\/me\/applications/);
    await expect(page.getByText("서류 심사 중")).toBeVisible();
    await shot(page, "apply-done");
    // 접수 마감 전이라 고칠 수 있다
    await page.getByRole("link", { name: "지원서 수정" }).click();
    const tech = page.locator('input[name="보유기술-0-기술내역"]');
    await expect(tech).toHaveValue("Python, Spark, SQL"); // 낸 내용이 채워져 있음
    await tech.fill("Python, Spark, SQL, Airflow");
    await page.getByRole("button", { name: "수정 저장" }).click();
    await expect(page).toHaveURL(/\/me\/applications/);
    await page.getByRole("link", { name: "지원서 수정" }).click();
    await expect(tech).toHaveValue("Python, Spark, SQL, Airflow");
    await shot(page, "apply-edit");
    // 진행 중인 지원이 있으니 다른 공고에는 지원할 수 없다
    await page.goto("/#jobs");
    await expect(page.getByTestId("active-notice")).toBeVisible();
    await expect(page.getByText(/지원 불가 · .* 결과 발표 뒤 지원 가능/).first()).toBeVisible();
    await shot(page, "apply-blocked");
  });

  test("관리자: 응시 시작 전 설정 수정 (ADM-025)", async ({ page }) => {
    // 데모 시드에서 8명이 이미 2차를 마쳐 설정이 잠겨 있다 → 최고 관리자가 잠금을 풀고(진행 중 응시 없음) 시험한다
    await page.request.post("/api/auth/admin/login", { data: { login_id: "admin", password: PW, otp: totp(SECRET) } });
    const pid = (await (await page.request.get("/api/admin/postings")).json())[0].id;
    expect((await page.request.post(`/api/admin/postings/${pid}/interview-setting/unlock`)).ok()).toBeTruthy();
    await adminLogin(page);
    await page.getByRole("link", { name: "AI 면접 설정" }).click();
    await expect(page.getByText("응시 시작 전 · 수정 가능")).toBeVisible();
    // 시험 시간을 줄이려고 생각 시간을 2초로 (CHECK 0~120)
    await page.fill("input[name=think_sec_non_tech]", "2");
    await page.fill("input[name=think_sec_tech]", "2");
    await page.getByRole("button", { name: "저장" }).click();
    await expect(page.getByText("저장했습니다.")).toBeVisible();
    await shot(page, "admin-setting-edit");
  });

  test("관리자: 채용 공고 작성 → 게시 → 채용 홈에 보임 (ADM-022~024)", async ({ page }) => {
    await adminLogin(page);
    await page.getByRole("link", { name: "채용 공고" }).click();
    await page.getByRole("link", { name: "새 공고 작성" }).click();
    await page.fill("input[name=title]", "E2E 프론트엔드 신입");
    await page.selectOption("select[name=job_role]", "프론트엔드");
    await page.fill("input[name=headcount]", "3");
    await page.fill("textarea[name=description]", "우대: React·TypeScript, 웹 성능 측정, 접근성.");
    await page.getByRole("button", { name: /^작성/ }).click();
    await expect(page.getByText("작성 중", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "AI 면접 설정" }).last()).toBeVisible();     // 면접 설정이 함께 만들어짐
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "게시", exact: true }).click();
    await expect(page.getByText("게시 중", { exact: true })).toBeVisible();
    await expect(page.getByText(/김인사 게시$/)).toBeVisible();                                   // 기록
    await shot(page, "admin-posting");
    const home = await (await page.request.get("/api/site/postings")).json();             // 채용 홈: 접수 시작 전이면 '접수 예정'
    expect(home.find((x: { title: string }) => x.title === "E2E 프론트엔드 신입")?.phase).toBe("upcoming");
  });

  test("cand01: 안내 → 점검·본인 확인 → 시작 → 10문항 → 완료", async ({ page }) => {
    // 가짜 카메라 영상에는 얼굴이 없어서, 모델 파일이 없을 때처럼 얼굴 감지를 끄고 진행한다 (실제 카메라 확인은 /dev/camera-check)
    await page.route("**/models/face_landmarker.task", (r) => r.fulfill({ status: 404 }));
    await page.addInitScript(() => ((window as { __E2E_FAKE_FACE__?: boolean }).__E2E_FAKE_FACE__ = true)); // 시험용 Chrome에만
    await candidateLogin(page, "haneul.kim@naver.com"); // seed/demo_accounts.sql의 cand01
    await shot(page, "applications");
    await page.getByRole("link", { name: "2차 응시 안내" }).click();
    await expect(page.getByText("AI 화상면접 규칙")).toBeVisible();
    await expect(page.getByText("AI 활용 안내")).toBeVisible();                              // 11/12 AI 사용 사전 고지
    await expect(page.getByText(/합격·불합격은 채용 담당관이/)).toBeVisible();
    await expect(page.getByRole("heading", { name: /글로 답하기 신청/ })).toBeVisible();      // 응시 편의 신청
    await expect(page.getByRole("button", { name: "연습 시작" })).toBeVisible();             // 연습 면접은 면접 뒤에 확인 (가짜 카메라는 한 번 끄면 같은 Chrome에서 다시 안 켜짐)
    await shot(page, "guide");
    await page.getByRole("link", { name: "응시 시작" }).click();

    await page.getByRole("button", { name: "문의하기" }).click();                       // 점검 화면 문의하기 = 담당자 연락처 + 회사 방문 면접 안내
    await expect(page.getByTestId("contact")).toContainText("02-000-0000");
    await expect(page.getByTestId("contact")).toContainText("회사");
    await page.getByTestId("contact").getByRole("button", { name: "닫기" }).click();
    for (const k of ["consent_voice", "consent_face", "consent_ai", "consent_overseas"]) await page.check(`input[name=${k}]`);
    const save = page.getByRole("button", { name: "점검·동의 저장" });
    await expect(save).toBeEnabled({ timeout: 30_000 }); // 카메라·마이크(가짜 장치 소리)·브라우저 확인 끝
    await shot(page, "precheck");
    await save.click();
    await page.getByRole("button", { name: "촬영" }).click();
    await expect(page.getByRole("button", { name: "다시 확인" })).toBeVisible();
    await expect(page.getByTestId("identity-result")).toContainText("본인 확인 완료");   // 결과를 바로 보여 줌
    await expect(page.getByText("움직임 확인을 마쳤습니다")).toBeVisible({ timeout: 10_000 });   // 라이브니스 (가짜 얼굴이라 바로 통과)
    await shot(page, "precheck-identity");
    await page.getByRole("button", { name: "다음" }).click();

    const start = page.getByRole("button", { name: "AI 화상면접 시작" });
    await expect(start).toBeEnabled({ timeout: 60_000 }); // 1~3번 질문 준비
    await shot(page, "ready");
    await start.click();
    await expect(page).toHaveURL(/\/live/);

    let reviewedOnce = false;
    for (let i = 1; i <= 10; i++) {
      await expect(page.getByTestId("qnum")).toHaveText(`${i} / 10`, { timeout: 60_000 });
      await expect(page.getByText("● 녹음 중")).toBeVisible({ timeout: 60_000 }); // 생각 시간 + 질문 읽기 끝(최대 30초 더) 뒤 녹음 시작
      await expect(page.getByTestId("mic-meter")).not.toContainText("마이크 없음"); // 면접 중 마이크 인식 표시
      await expect(page.locator("main")).not.toContainText(/\d+(\.\d+)?점/); // 점수는 보이지 않음 (IV-43)
      if ([1, 3, 4, 10].includes(i)) await shot(page, `live-q${i}`);
      if (i === 2) await expect(page.getByRole("button", { name: "문의하기" })).toHaveCount(0);   // 면접 중에는 문의하기 없음
      if (i === 3) {                                                                      // 끊김 복구 (11/12): 인터넷이 끊겼다 돌아와 새로고침해도 같은 문항
        await page.context().setOffline(true);
        await page.waitForTimeout(3_000);
        await page.context().setOffline(false);
        await page.reload();
        await expect(page.getByTestId("qnum")).toHaveText("3 / 10", { timeout: 60_000 });
        await expect(page.getByText("● 녹음 중")).toBeVisible({ timeout: 60_000 });
        await page.getByRole("button", { name: "가+" }).click();                          // 글자 크기 (접근성)
        await expect(page.getByTestId("question")).toHaveClass(/text-xl/);
      }
      if (i <= 2) await page.waitForTimeout(8_000);   // 1·2번은 녹음해 둔 답변을 8초 말한 뒤 제출 → 인식 글이 나옴. 나머지는 바로 제출(무응답)
      await page.getByRole("button", { name: "답변 끝" }).click();
      // 답변 인식 글 확인 (11/11): 글이 있으면 보여 주고 '완료'를 눌러야 다음 질문. 무응답(가짜 마이크 소리를 못 알아들음)이면 바로 다음
      const reviewText = page.getByTestId("review-text");
      const next = i < 10 ? page.getByTestId("qnum").filter({ hasText: `${i + 1} / 10` }) : page.getByTestId("finished");
      await expect(reviewText.or(next)).toBeVisible({ timeout: 90_000 });
      if (i <= 2) await expect(reviewText).toContainText(/캐시|인덱스|응답|쿼리/);     // 녹음 답변이 실제 STT로 글이 됨
      if (await reviewText.isVisible()) {
        await expect(page.getByTestId("qnum")).toHaveText(`${i} / 10`);                    // 확인 전에는 다음 질문이 안 나옴
        if (!reviewedOnce) {                                                               // 한 번은 고쳐 본다 (끝에 마침표)
          await page.getByRole("button", { name: "수정하기" }).click();
          const box = page.locator("textarea[name=review_text]");
          await box.press("End");
          await box.type(".");
          await expect(page.getByText(/바뀐 정도 약 \d+% \/ 최대 30%/)).toBeVisible();
          await shot(page, "live-review");
          reviewedOnce = true;
        }
        await page.getByRole("button", { name: "완료", exact: true }).click();
      }
    }
    await expect(page).toHaveURL(/\/done/, { timeout: 60_000 });
    await expect(page.getByRole("heading", { name: /면접이 종료되었습니다/ })).toBeVisible();   // 마지막 답변 → 제출 안내 → 종료 화면
    await shot(page, "done");
    await page.getByRole("link", { name: "지원 현황으로" }).click();
    await expect(page.getByText("2차 응시 완료")).toBeVisible(); // C13-02
    await expect(page.getByRole("link", { name: "2차 응시 안내" })).toHaveCount(0);
    await page.goto("/interview/1/guide");   // 김하늘 지원 건 1 · 연습 면접 (11/12): 질문 음성 → 생각 10초 → 녹음 → 인식 글, 저장 없음
    await page.getByRole("button", { name: "연습 시작" }).click();
    await expect(page.getByText("● 녹음 중")).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(3_000);
    await page.getByRole("button", { name: "답변 끝" }).click();
    await expect(page.getByText("내 답변 (인식된 글)")).toBeVisible({ timeout: 90_000 });
    await shot(page, "guide-practice");
    await page.getByRole("button", { name: "다음 연습 질문" }).click();
    await expect(page.getByText(/연습 질문 2/)).toBeVisible();
  });

  test("관리자: 설정 잠김 확인 → 결과 검토 → 확정 → 2차 종합 점수", async ({ page }) => {
    await adminLogin(page);
    await page.getByRole("link", { name: "AI 면접 설정" }).click();
    await expect(page.getByText(/응시 시작됨 · 잠김/)).toBeVisible();
    await expect(page.locator("input[name=think_sec_tech]")).toBeDisabled();
    await expect(page.getByRole("button", { name: "저장" })).toBeDisabled();
    await shot(page, "admin-setting-locked");

    await page.getByRole("link", { name: "지원자 현황" }).click();
    await expect(page.getByText("남 30 · 여 20")).toBeVisible(); // D-01
    await page.getByRole("row", { name: /김하늘/ }).click();
    await expect(page.getByText("김하늘 이력서")).toBeVisible(); // D-02·P-02 이력서 원본
    await shot(page, "admin-applicants");

    await page.getByRole("link", { name: "AI 면접 결과" }).click();
    const row = page.getByRole("row", { name: /김하늘/ });
    await expect(row.getByText("검증 완료")).toBeVisible({ timeout: 30_000 }).catch(async () => {
      await page.reload(); // 최종 평가는 worker가 끝내면 생김
      await expect(row.getByText("검증 완료")).toBeVisible({ timeout: 30_000 });
    });
    await shot(page, "admin-list");
    await row.getByRole("link").click();

    await expect(page.locator("table").first().locator("tbody tr")).toHaveCount(10);
    await page.locator("table").first().locator("tbody tr").nth(2).click(); // 3번(코딩 약점 질문) 상세
    await expect(page.getByText("출제 근거")).toBeVisible();
    await shot(page, "admin-detail");
    // 얼굴 대조가 실제 모드이고 증명사진이 없으면 '사람 확인' 의심 건이 열림 → 담당자가 처리해야 최종 합격을 정할 수 있다 (DB 규칙)
    const open = page.getByPlaceholder("처리 사유");
    for (let n = await open.count(); n > 0; n = await open.count()) {
      await open.first().fill("면접 기록으로 본인 확인함 (시험)");
      await page.getByRole("button", { name: "결정", exact: true }).first().click();
      await expect(open).toHaveCount(n - 1);
    }

    const res = page.waitForResponse((r) => r.url().endsWith("/confirm") && r.request().method() === "POST");
    await page.getByRole("button", { name: "평가 확정" }).click();
    const body = await (await res).json();
    expect((await res).status()).toBe(200);
    expect(Number(body.stage2_score.interview_score)).toBeGreaterThan(0);
    expect(Number(body.stage2_score.total_score)).toBeGreaterThan(0); // 면접 60 + 코딩 40
    await expect(page.getByRole("button", { name: "확정됨" })).toBeVisible();
    await shot(page, "admin-confirmed");
    console.log(`2차 종합: 면접 ${body.stage2_score.interview_score} · 코딩 ${body.stage2_score.coding_score} → ${body.stage2_score.total_score}`);

    // 최종 합격 결정 (ADM-042): 확정된 9명이 종합 점수 순으로, AI 추천을 보고 담당자가 정한다
    await page.getByRole("link", { name: "최종 합격 결정" }).click();
    await expect(page.locator("table tbody tr")).toHaveCount(9);                      // 시드 8명 + 방금 확정한 김하늘 (11/12: 1차 합격은 AI 추천 안에서)
    await expect(page.getByText("합격 추천", { exact: true })).toHaveCount(4);          // 모집 2명 × 2 (예비 없음, 넉넉하게 뽑음)
    const top = page.locator("table tbody tr").first();
    const finalBtn = page.getByRole("button", { name: /결과 확정/ });
    await expect(finalBtn).toHaveCount(2);                                            // 목록 위·아래
    await top.getByRole("checkbox").check();                                          // 합격할 사람만 체크
    await expect(finalBtn.first()).toHaveText(/합격 1명 · 불합격 8명/);
    await shot(page, "admin-final-check");                                            // 체크한 상태 (확정 전)
    page.once("dialog", (d) => d.accept());
    await finalBtn.last().click();                                                    // 한 번에 확정 → 나머지 불합격, 모두에게 알림
    await expect(page.getByText(/9명에게 알림 18건/)).toBeVisible();
    await expect(page.getByText(/^1 · 8$/)).toBeVisible();                          // 결정 수 (합격·불합격)
    await expect(page.getByText(/확정·알림 완료/)).toBeVisible();
    await shot(page, "admin-final");
  });

  test("이준서(코딩 전): 점검·본인 확인 → 코딩 테스트 화면 → 예제 실행 → 제출(통과 수만) → 면접 안내는 코딩 뒤", async ({ playwright }, info) => {
    // 같은 Chrome에서 면접(cand01) 뒤에는 가짜 카메라 영상이 안 들어와서, 이 시험은 새 Chrome을 띄운다 (시험 환경만의 문제)
    const browser = await playwright.chromium.launch({ channel: "chrome", args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] });
    const ctx = await browser.newContext({ ...info.project.use, permissions: ["camera", "microphone"] } as object);
    const page = await ctx.newPage();
    await page.route("**/models/face_landmarker.task", (r) => r.fulfill({ status: 404 }));
    await page.addInitScript(() => ((window as { __E2E_FAKE_FACE__?: boolean }).__E2E_FAKE_FACE__ = true)); // 시험용 Chrome에만
    await candidateLogin(page, "junseo.lee@gmail.com");
    await page.getByRole("link", { name: "2차 응시 안내" }).click();
    await page.getByRole("link", { name: "응시 시작" }).click();
    for (const k of ["consent_voice", "consent_face", "consent_ai", "consent_overseas"]) await page.check(`input[name=${k}]`);
    const save = page.getByRole("button", { name: "점검·동의 저장" });
    await expect(save).toBeEnabled({ timeout: 30_000 });
    await save.click();
    await page.getByRole("button", { name: "촬영" }).click();
    await expect(page.getByRole("button", { name: "다시 확인" })).toBeVisible();
    await expect(page.getByTestId("identity-result")).toContainText("본인 확인 완료");   // 결과를 바로 보여 줌
    await page.getByRole("button", { name: "다음: 코딩 테스트" }).click();

    await expect(page).toHaveURL(/\/coding/, { timeout: 120_000 }); // 개발 서버가 편집기 포함 화면을 처음 컴파일하는 시간
    await expect(page.locator(".monaco-editor")).toBeVisible({ timeout: 120_000 }); // 설치된 편집기 (CDN 아님)
    await expect(page.getByTestId("coding-timer")).toHaveText(/^\d{2}:\d{2}$/);
    await page.getByRole("button", { name: "예제 실행" }).click();
    await expect(page.getByTestId("coding-result")).toContainText("예제 1: 틀림", { timeout: 60_000 }); // 빈 틀 코드
    await page.getByRole("button", { name: "제출", exact: true }).click();
    await expect(page.getByTestId("coding-result")).toContainText(/채점 케이스 0\/\d+ 통과/, { timeout: 120_000 });
    await expect(page.getByTestId("coding-result")).not.toContainText("점수");
    await shot(page, "coding");
    await page.goto(page.url().replace(/coding$/, "ready"));
    await expect(page).toHaveURL(/\/coding/); // 코딩을 마치기 전에는 면접 안내로 못 감

    // 직접 확인할 때 처음부터 볼 수 있게 이준서의 코딩·면접 기록을 되돌린다 (개발용 초기화 API, 최고 관리자)
    const app = (await (await page.request.get("/api/interview/applications")).json())[0].id;
    const cs = await (await page.request.get(`/api/coding/applications/${app}/session`)).json();
    const iv = await (await page.request.get(`/api/interview/applications/${app}/guide`)).json();
    await page.request.post("/api/auth/admin/login", { data: { login_id: "admin", password: PW, otp: totp(SECRET) } });
    expect((await page.request.post(`/api/admin/coding/${cs.id}/reset`)).ok()).toBeTruthy();
    expect((await page.request.post(`/api/admin/interviews/${iv.session_id}/reset`)).ok()).toBeTruthy();
    await browser.close();
  });

  test("1차 서류: 평가 기준(우대) → AI 1차 검토(S0) → 추천 순 → 합격 체크 → 결정 확인 한 번 → 지원자 알림 → 합격 안내", async ({ page }) => {
    page.on("dialog", (d) => d.accept()); // '확정할까요?' 확인
    await adminLogin(page);
    await page.getByRole("link", { name: "1차 서류 결정" }).click();
    await expect(page.locator("select").first()).toHaveValue(/\d+/);
    await expect(page.getByRole("columnheader", { name: "AI 적합도" })).toHaveCount(0);       // 1차 점수는 어디에도 없음
    await expect(page.getByTestId("criteria")).toContainText("모두 우대");                      // 평가 기준: 공고 설명에서 채움
    await page.getByRole("button", { name: /AI 1차 검토 실행 \(30명\)/ }).click();
    await expect(page.getByText(/AI 1차 검토를 30명에게 실행했습니다/)).toBeVisible();
    const pid = await page.locator("select").first().inputValue();
    await expect.poll(async () => (await (await page.request.get(`/api/admin/postings/${pid}/document`)).json()).rows
      .filter((r: { ai: { screened: boolean } }) => r.ai.screened).length, { timeout: 600_000 }).toBe(30);
    await page.reload();
    const confirmBtn = page.getByRole("button", { name: /결정 확인/ });
    await expect(confirmBtn).toHaveCount(2);                                                   // 목록 위·아래
    await expect(confirmBtn.first()).toBeDisabled();                                           // 아무도 체크하지 않음
    const first = page.getByRole("row").nth(1);
    await first.getByRole("checkbox").check();
    await expect(confirmBtn.first()).toHaveText(/합격 1명 · 불합격 29명/);
    await first.getByRole("checkbox").uncheck();                                               // 체크는 화면에만 (서버 기록 없음)
    await expect(confirmBtn.first()).toBeDisabled();
    await first.getByRole("button", { name: "상세" }).click();
    await expect(page.getByText("요건별 라벨")).toBeVisible();
    await shot(page, "doc-screened", false);
    // AI 추천이면 체크 (마지막 한 명은 체크하지 않음) → 체크하지 않은 사람은 '결정 확인' 때 불합격
    const board = await (await page.request.get(`/api/admin/postings/${pid}/document`)).json();
    const pick = (r: { id: number; ai: { conclusion: string | null } }, i: number) =>
      r.ai.conclusion === "추천" && i < board.rows.length - 1 ? "pass" : "reject";
    for (const [i, r] of board.rows.entries())
      if (pick(r, i) === "pass") await page.getByTestId(`doc-row-${r.id}`).getByRole("checkbox").check();
    await shot(page, "doc-decided", false);
    await confirmBtn.last().click();                                                           // 목록 맨 아래 버튼으로 한 번에
    await expect(page.getByText(/30명에게 알림 60건/)).toBeVisible();
    await expect(page.getByText(/발표 완료/)).toBeVisible();
    await expect(page.getByRole("button", { name: "합격 취소" }).first()).toBeVisible();       // 발표 뒤에는 부정행위 때만 사유를 적어 취소
    await shot(page, "doc-announced", false);

    const top = board.rows.find((r: { id: number; ai: { conclusion: string | null } }, i: number) => pick(r, i) === "pass").email;
    await page.context().clearCookies();
    await candidateLogin(page, top);
    await expect(page.getByTestId("bell-count")).toHaveText("1");
    await page.getByRole("button", { name: /알림 1건/ }).click();
    await page.getByRole("button", { name: /1차 서류 전형 결과 발표/ }).click();
    await expect(page.getByTestId("doc-result")).toHaveText("서류 전형에 합격하셨습니다.");
    await expect(page.getByText("응시 기간", { exact: true })).toBeVisible();
    await expect(page.getByTestId("bell-count")).toHaveCount(0);                     // 읽으면 숫자가 사라짐
    await shot(page, "doc-result");
  });
});
