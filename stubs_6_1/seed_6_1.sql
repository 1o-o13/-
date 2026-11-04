-- 6.1 혼자 개발할 때 쓰는 시험 데이터 (I-2 코딩 결과·약점 요약, I-3 로그인·지원서·공고 대신 + 인성 질문 은행·회사 문서)
-- 순서: common_schema.sql → interview_schema.sql → 이 파일. 11/11 통합 뒤에는 쓰지 않는다.
INSERT INTO department(name) VALUES ('플랫폼개발팀');
INSERT INTO admin_user(login_id, password_hash, name, role, totp_secret_enc)
VALUES ('hr_stub', 'x', '시험 담당자', 'recruiter', 'x');
INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, status, published_at,
                        apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
SELECT '시험 공고 · 백엔드 신입', '백엔드', 'dev', 'new', 1, 'published', now(),
       now() - interval '1 day', now() + interval '5 day', now() + interval '6 day',
       now() + interval '7 day', now() + interval '10 day', now() + interval '12 day', id
FROM admin_user WHERE login_id = 'hr_stub';
INSERT INTO interview_setting(posting_id) SELECT id FROM job_posting WHERE title = '시험 공고 · 백엔드 신입';  -- 기본 ollama · qwen3
INSERT INTO candidate(email, name, phone, ci_hash) VALUES ('stub@example.com', '시험 지원자', '010-0000-0000', 'CI_STUB');
INSERT INTO application(posting_id, candidate_id, resume_snapshot)
SELECT p.id, c.id, '{"경력": "인턴 6개월"}'
FROM job_posting p, candidate c WHERE p.title = '시험 공고 · 백엔드 신입' AND c.ci_hash = 'CI_STUB';
INSERT INTO coding_session(application_id, status)                 -- 코딩 응시 (I-2 대신, 6.2 코딩 TRD 스키마)
SELECT id, 'completed' FROM application WHERE candidate_id = (SELECT id FROM candidate WHERE ci_hash = 'CI_STUB');
INSERT INTO coding_result(session_id, p1, p2, q3_base_tier, q3_tier, q3_partial, q3_converted, score_table_version, weakness_summary)
SELECT id, 90, 85, '골드3', '골드3', 70, 73, 'v1',                  -- 약점 요약 → 면접 3번(첫 기술 질문) 입력 (CT-33)
       '{"algorithms": ["BFS"], "failed_groups": [5], "weakness_tags": ["시간 복잡도"]}'
FROM coding_session;
-- 새벽소프트 문서 일부 (META_SPEC v0.3 형식, 실제 코퍼스는 scripts/load_corpus.py로 적재)
INSERT INTO company_doc_chunk(doc, sec, doc_title, sec_title, doc_type, tier, disclosure, topic, status, stages, dept, ct_band, related, forbid, body) VALUES
 ('PRJ-DRN-3','s1','스카이패스 — 3급','경로 계획','project',3,'public','DRN','done','{2차}','{BE}','중','{}','{}','격자 지도에서 BFS로 점검 경로를 계산한다'),
 ('PRJ-DRN-2','s1','스카이패스 — 2급','경로 지연','project',2,'abstract','DRN','ongoing','{2차}','{BE}','중','{RES-DRN-01}','{스카이허브}','출근 시간 경로 요청이 몰리면 계산이 늦어진다'),
 ('RES-DRN-01','s1','경로 연구','증분 탐색','research',1,'abstract','DRN','ongoing','{2차}','{BE}','중','{}','{}','변경된 구역만 다시 탐색하는 방법을 연구한다'),
 ('PRJ-MED-3','s1','루미스캔 — 3급','영상 수집','project',3,'public','MED','done','{2차}','{BE}','중','{}','{}','PACS에서 새 X-ray를 받아 큐에 넣는다'),
 ('PRJ-TKT-3','s1','줄서기 — 3급','대기열','project',3,'public','TKT','done','{2차}','{BE}','중','{}','{}','예매 대기열 순번을 Redis로 관리한다'),
 ('PRJ-TKT-2','s1','줄서기 — 2급','순번 꼬임','project',2,'abstract','TKT','ongoing','{2차}','{BE}','중','{}','{}','서버 재시작 때 대기 순번이 꼬인다'),
 ('PRJ-PAY-3','s1','정산 — 3급','일일 정산','project',3,'public','PAY','done','{2차}','{BE}','중','{}','{}','가맹점 정산을 배치로 계산한다');
