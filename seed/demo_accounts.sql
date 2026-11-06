-- 직접 확인용 계정 정리 (tasks.ps1 seed가 test_data.sql 다음에 넣는다. pytest는 이 파일을 쓰지 않음)
-- 지원자 50명의 이력서·1차 결과·코딩 결과는 모두 남기고, 로그인은 2차 면접 대상 1명(cand01 김하늘 수준 상), 1차 불합격 1명(cand07 오세훈 수준 하, AI 비추천 · 11/12)과
-- 코딩 테스트 전 1명(cand02 이준서, 코딩 기록을 지워 코딩부터 보게 함)만 된다.
-- 관리자는 admin·hr01만 로그인, dev01·hr02는 가입 신청 뒤 승인 대기 (is_active = false → 로그인하면 '승인 대기' 안내)
BEGIN;
-- 외부 AI 처리(국외 전송) 동의서 1판: 지원서 제출 때 필수 동의 (활동다이어그램 1109). 문구는 임시
INSERT INTO consent_document(kind, version, body, effective_at)
VALUES ('ai_usage', 1, '서류 평가와 2차 AI 면접은 이름·학교·연락처 등을 가린 내용을 국외 AI 서비스로 보내 처리합니다. 사내 보안 문서가 들어간 처리는 국외로 보내지 않습니다. AI는 질문 생성과 답변 정리를 돕고 합격 결정은 채용 담당관이 합니다. 면접 기록은 최종 발표 후 180일이 지나면 파기합니다.', now())
ON CONFLICT DO NOTHING;
UPDATE candidate SET password_hash = NULL                     -- 비밀번호 없음 → 로그인 불가 (자료는 그대로)
 WHERE email NOT IN ('cand01@test.local', 'cand07@test.local', 'cand02@test.local');
-- 로그인되는 2명은 가입 틀(실제 메일 서비스·휴대폰 형식)에 맞는 시험 주소로. 비밀번호 Test1234!는 틀에 맞음
UPDATE candidate SET email = 'haneul.kim@naver.com' WHERE email = 'cand01@test.local';
UPDATE candidate SET email = 'sehun.oh@gmail.com' WHERE email = 'cand07@test.local';
UPDATE candidate SET email = 'junseo.lee@gmail.com' WHERE email = 'cand02@test.local';
DELETE FROM coding_session WHERE application_id IN (SELECT a.id FROM application a JOIN candidate c ON c.id = a.candidate_id
                                                    WHERE c.email = 'junseo.lee@gmail.com');   -- 문항·제출·결과는 CASCADE
-- 아직 아무 공고에도 지원하지 않은 지원자 1명 (지원서 작성·제출 확인용). 비밀번호 Test1234!
INSERT INTO candidate(email, password_hash, name, phone, ci_hash)
 SELECT 'jimin.park@naver.com', password_hash, '박지민', '010-4821-7730', 'CI_DEMO_NEW' FROM candidate WHERE email = 'haneul.kim@naver.com';
UPDATE admin_user SET is_active = false WHERE login_id = 'dev01';
INSERT INTO admin_user(login_id, password_hash, name, role, department_id, is_active)
 SELECT 'hr02', password_hash, '채용담당 이대기', 'recruiter', department_id, false FROM admin_user WHERE login_id = 'hr01';
-- 채용 홈 확인용 공고 (지원서 없음). 접수 중 2개 + 지난 공고 1개 (11/17: 공고가 너무 많아 8개에서 줄임). 2차 면접 시험은 기존 '2026 하반기 백엔드 신입'으로만
INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, description, status, published_at,
  apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
SELECT v.title, v.role, 'dev', v.lv, v.n, v.descr, v.st, now() - (v.s || ' day')::interval,
       now() - (v.s || ' day')::interval, now() + (v.e || ' day')::interval, now() + ((v.e + 3) || ' day')::interval,
       now() + ((v.e + 5) || ' day')::interval, now() + ((v.e + 12) || ' day')::interval, now() + ((v.e + 15) || ' day')::interval,
       (SELECT id FROM admin_user WHERE login_id = 'hr01')
FROM (VALUES
  ('결제 플랫폼 백엔드 시니어 (페이브릿지)', '백엔드', 'senior', 1, 'published', 1, 14,
   '필수: Java·Spring 5년 이상, 결제·정산 도메인, 대용량 트랜잭션·장애 대응. 우대: Kafka 이벤트 설계, 멱등성·보상 트랜잭션 경험.'),
  ('프론트엔드 개발자 경력 (React·TypeScript)', '프론트엔드', 'junior', 2, 'published', 3, 10,
   '필수: React·TypeScript 2년 이상, 상태 관리와 렌더링 성능. 우대: Next.js, 디자인 시스템 구축, 웹 접근성.')
) AS v(title, role, lv, n, st, s, e, descr);
INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, description, status, published_at,
  apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
SELECT v.title, v.role, 'dev', v.lv, v.n, v.descr, 'finished', now() - (v.ago || ' day')::interval,
       now() - (v.ago || ' day')::interval, now() - ((v.ago - 14) || ' day')::interval, now() - ((v.ago - 18) || ' day')::interval,
       now() - ((v.ago - 21) || ' day')::interval, now() - ((v.ago - 28) || ' day')::interval, now() - ((v.ago - 31) || ' day')::interval,
       (SELECT id FROM admin_user WHERE login_id = 'hr01')
FROM (VALUES
  ('2026 상반기 백엔드 신입', '백엔드', 'new', 3, 200, 'Python 또는 Java로 REST API 개발, SQL과 인덱스 이해.')
) AS v(title, role, lv, n, ago, descr);
INSERT INTO interview_setting(posting_id) SELECT id FROM job_posting p WHERE NOT EXISTS (SELECT 1 FROM interview_setting s WHERE s.posting_id = p.id);
INSERT INTO coding_setting(posting_id, languages) SELECT id, ARRAY['python','java'] FROM job_posting p
 WHERE NOT EXISTS (SELECT 1 FROM coding_setting s WHERE s.posting_id = p.id);
-- 직접 확인용: 생각 시간을 5초로 줄인다 (기본 10·20초. 공고 설정은 첫 응시 시작 전이라 아직 잠기지 않음)
UPDATE interview_setting SET think_sec_non_tech = 5, think_sec_tech = 5;
-- 실제 모듈(MODULE_MODE=real): 외부 모델은 Claude, tier ≤ 2 근거·국외 전송 미동의는 이 PC의 사내 모델 qwen3:4b (RAG-17)
UPDATE interview_setting SET llm_provider = 'anthropic', llm_eval_model = 'claude-sonnet-5-5', llm_fast_model = 'claude-haiku-5-5',
                             llm_local_model = 'qwen3:4b';

-- 1차(서류) 결과: 50명 중 10명 합격(2차 대상), 나머지 40명은 서류 불합격.
-- 합격 10명 = AI 1차 검토 '추천'(공고 지원자의 상위 30% = 15명, 저장분 seed/doc_screen_cache.json, 11/12) 중 적합도 상위 10명.
-- 저장분을 다시 만들면(AI 재검토) 이 목록도 다시 맞춘다. 오세훈(데모 계정)은 AI 비추천이라 1차 불합격
UPDATE application a SET status = 'doc_failed'
  FROM candidate c
 WHERE c.id = a.candidate_id AND a.status = 'stage2'
   AND c.email NOT IN ('junseo.lee@gmail.com', 'cand03@test.local', 'cand23@test.local', 'haneul.kim@naver.com', 'cand22@test.local',
                       'cand29@test.local', 'cand49@test.local', 'cand26@test.local', 'cand39@test.local', 'cand31@test.local');
UPDATE stage_result SET result = 'fail' WHERE stage = 'document'                    -- 담당자 서류 결정 기록도 같게 (공통 stage_result)
   AND application_id IN (SELECT id FROM application WHERE status = 'doc_failed');
-- 서류 불합격자의 코딩 기록은 없앤다 (코딩 테스트는 1차 합격자만 봄). 합격자 중 2차를 마친 8명은 scripts/simulate_stage2.py가 만든다
DELETE FROM coding_session WHERE application_id IN (SELECT id FROM application WHERE status = 'doc_failed');
-- 1차 결과는 이미 발표된 상태 (announcement + 지원자별 메일·문자 발송 기록). 지원자 홈페이지 알림함에 '1차 서류 전형 결과 발표'가 보인다
INSERT INTO announcement(posting_id, stage, status, checked_by, published_by, published_at)
SELECT p.id, 'document', 'published', u.id, u.id, p.doc_announce_at FROM job_posting p, admin_user u
 WHERE p.title = '2026 하반기 백엔드 신입' AND u.login_id = 'hr01';
INSERT INTO notification(candidate_id, channel, template, announcement_id, status, sent_at)
SELECT a.candidate_id, ch, 'doc_result_ready', n.id, 'sent', n.published_at
  FROM application a JOIN announcement n ON n.posting_id = a.posting_id AND n.stage = 'document', (VALUES ('email'), ('sms')) v(ch)
 WHERE n.posting_id = (SELECT id FROM job_posting WHERE title = '2026 하반기 백엔드 신입');
COMMIT;
