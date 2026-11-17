@title 화상 면접 DB 설계서 (6.1)
@summary DB가 어떻게 구성되고, 테이블끼리 어느 칼럼을 통해 연결되는가. 연결 읽는 법, 영역 지도, SQL 도구 형식의 관계도, 조회 경로 6가지(그림 + SQL JOIN), 외래키 84개 전체 목록(삭제 동작 포함), 6.1 테이블 21개의 모든 칼럼, DB가 지키는 규칙, 개인정보·보관 정책을 정리했습니다.
@landscape yes

# 1. 개요
| 항목 | 내용 |
|---|---|
| DBMS | PostgreSQL 17 + pgvector 0.8.7 (`pgvector/pgvector:0.8.7-pg17`) |
| 규모 | 테이블 61개, 외래키 84개 (11/17 실제 DB 기준) |
| 스키마 파일 | `db/common_schema.sql` 공통 (다른 파트 소유, 바꾸지 않음) · `db/interview_schema.sql` 6.1 면접 21개 |
| 그래프 저장 | LangGraph 체크포인트 4개 (`checkpoints` 등, 라이브러리가 만듦) |
| 시험 | `db/test_interview_schema.py` — 규칙 위반을 넣어 DB가 거부하는지 확인 |
| 변경 원칙 | `interview_schema.sql`은 이유를 보고하고 승인받은 뒤에만 바꿈. 스키마의 CHECK 제약이 규칙의 정답이고, 코드를 제약에 맞춤 |

관계도는 `scripts/build_diagrams.py`가 실제 DB에서 칼럼·자료형·키를 읽어 그립니다. 그림 원본(고해상도 PNG)은 `docs/최종/그림/`에 있습니다.

# 2. 연결을 읽는 법
테이블은 **외래키(FK) 칼럼**을 통해 다른 테이블의 **기본키(PK) 칼럼**으로 들어갑니다. 예를 들어 `interview_session.application_id`에는 `application.id` 값이 들어 있고, 두 테이블은 `interview_session.application_id = application.id`로 이어집니다.

| 연결 종류 | 뜻 | 이 DB의 예 |
|---|---|---|
| 1 : N | 부모 1개에 자식이 여럿 | 응시 1개 → 질문 10개 (`interview_question.session_id`) |
| 1 : 1 | 자식 칼럼이 기본키이거나 유일해서 부모 1개에 자식 1개 | 질문 → 답변 (`interview_answer.question_id` UNIQUE), 공고 → 면접 설정 (`interview_setting.posting_id` PK) |
| 자기 참조 | 같은 테이블의 다른 행을 가리킴 | 꼬리·재질문 → 원래 질문 (`interview_question.parent_question_id`) |
| 값 참조 | 외래키 없이 값을 적어 둠 (DB가 검사하지 않음) | 질문의 근거 `source_doc_ids` ('doc#sec') → `company_doc_chunk` |
| 값 복사 | 바뀌면 안 되는 값을 시작할 때 옮겨 둠 | 코딩 약점 `coding_result.weakness_summary` → `interview_session.coding_weakness` |

**부모를 지우면 자식은 어떻게 되나 (삭제 동작)**

| 동작 | 뜻 | 이 DB의 예 |
|---|---|---|
| 같이 삭제 (CASCADE) | 부모가 지워지면 자식도 함께 지워짐 | 응시를 지우면 질문·답변·판정·평가·감독 기록이 모두 지워짐 (180일 파기가 이 방식) |
| 막음 (NO ACTION) | 자식이 남아 있으면 부모를 지울 수 없음 | 응시가 있는 지원 건은 지울 수 없음, 판정을 남긴 관리자는 지울 수 없음 |
| NULL로 비움 (SET NULL) | 부모가 지워지면 자식의 칼럼만 비움 | 문의·자료 요청의 지원 건 칼럼 |

**관계도 그림 읽는 법**
- 🔑 기본키(PK), 🔗 외래키(FK), `·NN` = NOT NULL.
- 선은 외래키 칼럼 줄에서 상대 테이블의 기본키 줄로 이어집니다. 짧은 막대 쪽이 '1', 갈라진 쪽(까마귀발)이 '여럿'입니다.
- 공통 테이블은 주요 칼럼만 보이고, 나머지는 '칼럼 n개 더'로 줄였습니다. 모든 칼럼은 12장 테이블 상세에 있습니다.

---

# 3. 영역 지도
![그림 1. DB 영역 지도 — application(지원 건)이 중심](fig:erd_overview.png)

---

| 영역 | 테이블 | 소유 |
|---|---|---|
| 채용·공고 | department, admin_user, hiring_request, job_posting, posting_assignee, posting_review, posting_history, announcement, notification, policy_setting | 공통 |
| 지원자·계정 | candidate, resume, candidate_consent, consent_document, candidate_social_account, notification_pref, login_history, data_request, inquiry | 공통 |
| 1차 서류 | document_criteria, document_evaluation, document_review, stage_result, dept_opinion | 공통 (6.1 임시 구현이 씀) |
| 코딩 테스트 | coding_setting, coding_session, coding_problem, coding_case, coding_attempt, coding_submission, coding_review, coding_result | 공통 (6.1 임시 구현이 씀) |
| 2차 AI 화상면접 | interview_setting ~ answer_accommodation (15개) | **6.1** |
| 질문·근거·LLM | question_bank, prepared_question, llm_call (6.1) · company_doc_chunk (공통) · checkpoints | 6.1 / 공통 |
| 단계·결과 | application_stage, application_stage_log, stage_transition (6.1) · stage2_score, stage2_exception, audit_log, ai_usage_log (공통) | 6.1 / 공통 |

---

# 4. 면접 테이블 관계도 ① 응시 · 질문 · 답변 · 판정 · 평가
![그림 2. 응시 → 질문 → 답변 → 판정, 응시 → 평가 → 검사·알림](fig:erd_interview.png)

---

| 테이블 | 쓰임 | 주요 규칙 |
|---|---|---|
| interview_setting | 공고별 면접 설정 (문항 수·기준 점수·시간·배점·모델) | 공고와 1 : 1. 재질문 기준 < 꼬리질문 기준. 첫 응시가 시작되면 `locked_at`으로 잠김 |
| interview_session | 응시 1회. 인계 데이터·코딩 약점·난이도 대역·동의·모델을 시작 때 복사 | 지원 건당 응시 번호(attempt_no) 1~3, (지원 건, 차수) 유일. exam_code 유일 |
| interview_question | 물어본 질문. 순서·종류·깊이·주제·근거 청크·최저 tier·방어 검사 결과 | (응시, 순서) 유일. 1·2번 비기술 / 3번~ 기술. 재질문은 원래 질문당 1개. 꼬리·재질문은 parent_question_id로 원래 질문을 가리킴 |
| interview_answer | 답변. 인식 원본·확인본·수정 비율, 음성 삭제 시각, 답변 방식(음성·글) | 질문당 1개 (재녹음 불가). 수정 비율 0~0.3. STT가 끝나면 음성 위치가 비어 있어야 함 |
| answer_judgement | 답변별 판정. 점수·루브릭·인용·의견·언어 점수·모델·지연 | 점수 0~100, 비기술은 점수 없음. 현재 판정은 답변당 1개(is_current), 다시 판정하면 새 행 |
| answer_signal | 표정·목소리 구간 기록 | 점수에 쓰지 않음 |
| interview_evaluation | 최종 평가. 주제 점수·내용·언어·비언어·총점·의견 | (응시, 버전) 유일, 버전 1·2. 검증 통과(passed)만 확정 가능 |
| evaluation_check | 5검사 결과 | (평가, 검사 번호) 유일, 번호 1~5 |
| ai_error_alert | 재평가까지 실패하면 담당자 알림 | 담당자가 처리 |

---

# 5. 면접 테이블 관계도 ② 본인 확인 · 감독 · 의심 건 · 장애 · 메모 · 응시 편의
![그림 3. 응시에 붙는 확인·감독 기록과 담당자 결정](fig:erd_interview2.png)

---

| 테이블 | 쓰임 | 주요 규칙 |
|---|---|---|
| identity_check | 본인 확인 거리·구간(일치·애매·불일치·얼굴 없음), 60초 재확인, 라이브니스 | 사진은 저장하지 않고 거리값만. 재촬영 번호 0~3 |
| proctor_event | 탭 이탈·얼굴 없음·여러 명·시선 이탈 등 감독 이벤트와 조치 | 어느 문항에서 생겼는지 question_id |
| suspicion_case | 의심 건과 담당자 결정 | 담당자가 결정해야만 '결정됨' (자동 불합격 없음) |
| interview_incident | 장애 원인 분류와 추가 시간 | 응시자 원인이면 추가 시간 0 |
| interview_note | 담당자 메모 | AI 점수는 고칠 수 없고 메모만 |
| answer_accommodation | 글로 답하기 신청·승인 | 지원 건당 1개. 담당자가 정해야만 승인·거절 |

---

# 6. 지원 건 중심 관계도
![그림 4. 공고·지원자 → 지원 건 → 1차·코딩·질문·LLM·단계·2차 종합](fig:erd_support.png)

---

| 테이블 | 쓰임 |
|---|---|
| application | 지원 건. 지원자·공고, 제출 당시 이력서 스냅숏(JSON), 증명사진 위치 |
| document_evaluation | 1차 AI 검토 근거(criteria_scores)와 면접 인계 데이터(handoff) |
| coding_session · coding_result | 코딩 응시와 결과. 3번 등급·환산 점수·약점 요약(weakness_summary) → 면접 3번 질문 |
| prepared_question · question_bank | 직무별 질문 은행 → 지원 건마다 미리 만든 질문(1차 합격 즉시, 3번은 코딩 직후). 검증 결과(verify) 기록 |
| company_doc_chunk | 회사 문서 청크. 메타(tier·주제·난이도·금지어) + bge-m3 임베딩 1024차원. 질문의 근거는 외래키 없이 청크 id(doc#sec)로 참조 |
| llm_call | 모든 LLM 호출 기록 (목적·프롬프트 버전·모델·tier·토큰·지연·성공). 프롬프트 본문은 남기지 않음 |
| application_stage · application_stage_log · stage_transition | 상세 단계 11종, 이동 기록, 허용된 이동 25개 |
| stage2_score | 2차 종합 (면접 60% + 코딩 40%), 과락, AI 순위·추천 |
| stage_result | 단계별 결정(1차·최종)과 결정한 담당자 |

---

# 7. 조회 경로 ① 지원자 → 면접 답변·판정
어느 지원자의 면접 문항별 답변과 점수를 볼 때 지나는 길입니다. 테이블 6개를 외래키 5개로 잇습니다.

![조회 경로 ① 지원자 → 지원 건 → 응시 → 질문 → 답변 → 판정](fig:path_1.png)

```
-- 김하늘(지원자)의 가장 최근 응시, 문항별 질문·답변·점수
SELECT q.ask_order, q.kind, q.question_type, q.depth, ans.stt_text, j.score, j.model
FROM candidate c
JOIN application a          ON a.candidate_id = c.id            -- 지원자 → 지원 건
JOIN interview_session s    ON s.application_id = a.id          -- 지원 건 → 응시 (최대 3차)
JOIN interview_question q   ON q.session_id = s.id              -- 응시 → 질문 10개
JOIN interview_answer ans   ON ans.question_id = q.id           -- 질문 → 답변 (1 : 1)
LEFT JOIN answer_judgement j ON j.answer_id = ans.id AND j.is_current   -- 답변 → 현재 판정
WHERE c.email = 'haneul.kim@naver.com'
  AND s.attempt_no = (SELECT max(attempt_no) FROM interview_session WHERE application_id = a.id)
ORDER BY q.ask_order;
```

- **꼬리질문 따라가기:** `interview_question.parent_question_id = 원래 질문.id`로 같은 테이블을 한 번 더 조인하면, 어느 본 질문에서 이어진 꼬리질문인지 알 수 있습니다.
- **판정 이력:** 다시 판정하면 이전 판정은 `is_current = false`로 남습니다. 이력까지 보려면 `is_current` 조건을 빼면 됩니다.

---

# 8. 조회 경로 ② 공고 → 면접 설정, ③ 면접 점수 → 2차 종합
![조회 경로 ② 공고 → 면접 설정](fig:path_2.png)

![조회 경로 ③ 응시 → 최종 평가 → 5검사 / 지원 건 → 2차 종합](fig:path_3.png)

```
-- 공고별 2차 순위: 면접 평가(확정본) · 5검사 · 2차 종합
SELECT p.title, a.id AS 지원, e.version_no, e.total_score AS 면접, e.status AS 검증,
       count(*) FILTER (WHERE ch.passed) AS 통과_검사수, s2.total_score AS 종합, s2.ai_rank, s2.ai_recommendation
FROM job_posting p
JOIN interview_setting st   ON st.posting_id = p.id              -- 공고 → 설정 (1 : 1, 기준 점수)
JOIN application a          ON a.posting_id = p.id               -- 공고 → 지원 건
JOIN interview_session s    ON s.application_id = a.id
JOIN interview_evaluation e ON e.session_id = s.id AND e.confirmed_at IS NOT NULL   -- 확정한 버전만
JOIN evaluation_check ch    ON ch.evaluation_id = e.id           -- 5검사
JOIN stage2_score s2        ON s2.application_id = a.id          -- 지원 건 → 2차 종합 (1 : 1)
WHERE p.id = 1
GROUP BY p.title, a.id, e.version_no, e.total_score, e.status, s2.total_score, s2.ai_rank, s2.ai_recommendation
ORDER BY s2.ai_rank;
```

`stage2_score`는 담당자가 면접 평가를 **확정할 때** 만들어지고, 같은 공고 지원자 전체의 순위·추천이 다시 매겨집니다.

---

# 9. 조회 경로 ④ 코딩 → 3번 질문, ⑤ 질문의 근거 문서
![조회 경로 ④ 코딩 테스트 → 면접 3번 질문](fig:path_4.png)

```
-- 면접 3번 질문이 어떤 코딩 약점에서 나왔는지
SELECT s.id AS 응시, cr.q3_tier, s.ct_band, s.coding_weakness, q.question_text
FROM interview_session s
JOIN coding_session cs    ON cs.id = s.coding_session_id        -- 응시 → 코딩 응시 (비개발 직군은 NULL)
JOIN coding_result cr     ON cr.session_id = cs.id              -- 코딩 응시 → 결과 (1 : 1)
JOIN interview_question q ON q.session_id = s.id AND q.ask_order = 3
WHERE s.application_id = 1;
```

`coding_weakness`는 면접 시작 때 `coding_result.weakness_summary`를 **복사**한 값이라, 면접 도중 코딩 결과가 바뀌어도 질문 근거가 흔들리지 않습니다.

---

![조회 경로 ⑤ 질문 은행 → 미리 만든 질문 → 실제 질문 → 근거 문서](fig:path_5.png)

```
-- 실제로 물어본 질문의 근거 문서 본문 (source_doc_ids는 'doc#sec' 문자열 배열)
SELECT q.ask_order, q.min_tier, d.doc, d.sec, d.tier, d.topic, left(d.body, 80) AS 근거_앞부분
FROM interview_question q
CROSS JOIN LATERAL jsonb_array_elements_text(q.source_doc_ids) AS src(chunk)
JOIN company_doc_chunk d ON d.doc = split_part(src.chunk, '#', 1)
                        AND d.sec = split_part(src.chunk, '#', 2)    -- 값 참조 (외래키 아님)
WHERE q.session_id = 11
ORDER BY q.ask_order;
```

근거 문서는 외래키 대신 값으로 참조합니다. 회사 문서를 다시 넣어도(청크 재적재) 지난 면접 기록이 지워지거나 막히지 않게 하려는 것입니다.

---

# 10. 조회 경로 ⑥ 감독 → 의심 건 → 담당자 결정
![조회 경로 ⑥ 응시 → 감독 이벤트 → 의심 건 → 담당자 결정](fig:path_6.png)

```
-- 응시별 감독 이벤트와 의심 건 처리 결과
SELECT s.exam_code, pe.event_type, q.ask_order, pe.duration_ms, pe.action,
       sc.reason, sc.status, sc.decision, u.name AS 결정한_담당자
FROM interview_session s
JOIN proctor_event pe          ON pe.session_id = s.id                 -- 응시 → 감독 이벤트
LEFT JOIN interview_question q ON q.id = pe.question_id                -- 몇 번 문항에서
LEFT JOIN suspicion_case sc    ON sc.interview_session_id = s.id       -- 응시 → 의심 건
LEFT JOIN admin_user u         ON u.id = sc.decided_by                 -- 결정한 담당자
WHERE s.application_id = 1          -- 감독 이벤트가 없던 응시면 0행
ORDER BY pe.occurred_at;
```

---

# 11. 외래키 전체 목록
@include _db_fk.md

---

# 12. 테이블 상세 (6.1 테이블 21개, 모든 칼럼)
@include _db_tables.md

---

# 13. DB가 지키는 규칙
규칙이 많은 부분은 코드보다 DB 제약으로 먼저 막았습니다. `interview_schema.sql`에 CHECK 제약이 93개 있습니다.

| 분류 | 규칙 | 방법 |
|---|---|---|
| 질문 구성 | 번호(1~10) 중복 금지, 1·2번은 비기술, 3번부터 기술 | 유일 색인 + CHECK |
| 재질문 | 원래 질문당 재질문 1개 | 부분 유일 색인 (`question_type = 'reask'`) |
| 답변 | 질문당 답변 1개 (재녹음 불가), 수정 비율 0~0.3, STT 뒤 음성 위치 비움 | UNIQUE + CHECK |
| 점수 | 기술 0~100, 비기술은 점수 없음, 응답 상태 ok가 아니면 0점 | CHECK |
| 평가 | 버전 1·2, 검사 번호 1~5, 검증 통과만 확정 | UNIQUE + CHECK |
| 설정 | 재질문 기준 < 꼬리질문 기준, 배점 합 100 | CHECK |
| 재응시 | 지원 건당 최대 3차 | UNIQUE (지원 건, 차수) + CHECK |
| 사람의 결정 | 의심 건 결정·글로 답하기 승인은 결정한 담당자와 시각이 있어야만 확정 | CHECK (결정자·시각 필수) |
| 단계 이동 | 허용된 이동 25개만 | 트리거 `trg_application_stage` + `stage_transition` |
| 감사 | 판정·평가는 덮어쓰지 않고 새 행·새 버전 | is_current 부분 유일 색인, 버전 번호 |

---

# 14. 개인정보와 보관
| 데이터 | 어디에 | 얼마나 |
|---|---|---|
| 답변 음성 | 공유 볼륨 `/audio` (DB에는 위치만) | STT 직후 삭제, `audio_deleted_at` 기록 |
| 영상 | 저장하지 않음 (브라우저 안에서 감독에만 씀) | — |
| 본인 확인 프레임 | 저장하지 않음 (대조 거리만 identity_check에) | — |
| 증명사진 | 볼륨 `/photos` (지원서의 `photo_object_key`) | 지원서와 함께 |
| 이력서 개인정보 | application.resume_snapshot | AI에 보낼 때만 LLM 관문이 가림 |
| 면접 기록 (응시·질문·답변 글·판정·평가·감독·의심 건·메모·LLM 호출 기록) | 면접 테이블 | 최종 발표 후 180일 뒤 매일 03:00 자동 파기 (응시 삭제 → 딸린 기록 CASCADE), 파기 건수만 audit_log |
| 프롬프트 본문 | 남기지 않음 | llm_call에는 목적·버전·토큰만 |

---

# 15. 단계별로 쓰는 테이블
| 업무 단계 | 쓰는 테이블 (쓰기) |
|---|---|
| 지원 | application, application_stage(submitted) |
| 1차 서류 | document_evaluation → stage_result → application_stage, announcement, notification |
| 질문 미리 만들기 | prepared_question (question_bank·company_doc_chunk를 읽음), llm_call |
| 점검·본인 확인 | interview_session(precheck·동의), identity_check |
| 코딩 테스트 | coding_session, coding_attempt, coding_submission, coding_result |
| 면접 | interview_question, interview_answer, answer_judgement, answer_signal, proctor_event, suspicion_case, interview_incident, llm_call |
| 평가 · 확정 | interview_evaluation, evaluation_check, ai_error_alert → stage2_score |
| 최종 결정 | stage_result(final), application_stage(final_pass·final_fail), announcement, notification |
