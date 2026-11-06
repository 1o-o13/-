-- 직접 확인용 (11/11): 김하늘(cand01)도 코딩 테스트부터 보게 코딩 기록을 지운다 → 사전 점검·본인 확인 → 코딩 테스트 → 화상 면접.
-- 3번(코딩 약점) 질문은 실제로 푼 코딩 결과로 코딩이 끝나는 즉시 다시 만든다 (worker prepare_q3_question).
-- tasks.ps1 e2e는 이 파일을 넣지 않는다 (E2E의 10문항 흐름은 코딩을 마친 김하늘로, 코딩 화면은 이준서로 확인)
BEGIN;
DELETE FROM coding_session WHERE application_id IN (SELECT a.id FROM application a JOIN candidate c ON c.id = a.candidate_id
                                                    WHERE c.email = 'haneul.kim@naver.com');   -- 문항·제출·결과는 CASCADE
DELETE FROM prepared_question WHERE slot = 3 AND application_id IN (SELECT a.id FROM application a JOIN candidate c ON c.id = a.candidate_id
                                                                   WHERE c.email = 'haneul.kim@naver.com');
COMMIT;
