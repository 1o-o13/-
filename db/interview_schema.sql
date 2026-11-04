-- AI 화상면접 파트 데이터 모델 (1차안) · PostgreSQL 17 · 2026-11-01
-- 원칙: STT 텍스트와 기록만 저장. 영상·얼굴 사진은 저장하지 않음. 답변 음성은 STT 후 삭제(삭제 시각 기록).
--       평가는 덮어쓰지 않고 새 행으로 쌓음. 상태값은 ENUM 대신 text + CHECK (마이그레이션이 쉬움).
-- 다른 파트 테이블(가정, 이름은 공통 파트와 맞출 것): job_posting, application, admin_user, coding_session

-- ===== 다른 파트 테이블 (경계 확인용 최소 정의. 실제 정의는 각 파트 소유) =====
CREATE TABLE IF NOT EXISTS job_posting (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, title text NOT NULL);
CREATE TABLE IF NOT EXISTS application (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    posting_id bigint NOT NULL REFERENCES job_posting(id), applicant_name text NOT NULL);
CREATE TABLE IF NOT EXISTS admin_user (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name text NOT NULL);
CREATE TABLE IF NOT EXISTS coding_session (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id bigint NOT NULL REFERENCES application(id));      -- 코딩 응시 (6.2 소유). 약점 요약은 coding_result.weakness_summary

-- ===== 1. 공고별 면접 설정 (ADM-025) =====
CREATE TABLE interview_setting (
    posting_id          bigint PRIMARY KEY REFERENCES job_posting(id),
    company_requirements text,                                          -- 회사 요구사항
    -- 영찬 RAG TRD v0.6: 10문항(재질문·꼬리 포함). 1번 이력서 본인 확인, 2번 결핍 가치, 3~10번 기술. 70점↑ 꼬리, 40~70 다른 주제, 40↓ 재질문 1회
    total_questions     smallint NOT NULL DEFAULT 10 CHECK (total_questions BETWEEN 3 AND 20),
    followup_max_depth  smallint NOT NULL DEFAULT 2  CHECK (followup_max_depth BETWEEN 0 AND 2),
    think_sec_non_tech  smallint NOT NULL DEFAULT 10 CHECK (think_sec_non_tech BETWEEN 0 AND 120),  -- 1·2번 생각 시간 (확인 필요)
    think_sec_tech      smallint NOT NULL DEFAULT 20 CHECK (think_sec_tech BETWEEN 0 AND 120),      -- 기술 질문 생각 시간 (확인 필요)
    answer_max_sec      smallint NOT NULL DEFAULT 180 CHECK (answer_max_sec BETWEEN 30 AND 600),
    silence_skip_sec    smallint NOT NULL DEFAULT 5  CHECK (silence_skip_sec BETWEEN 3 AND 30),     -- 이만큼 침묵하면 다음 문제 (5~6초 확인 필요)
    follow_score        smallint NOT NULL DEFAULT 70 CHECK (follow_score BETWEEN 1 AND 100),       -- 이 점수 이상이면 꼬리질문 (Q-21 보정)
    retry_score         smallint NOT NULL DEFAULT 40 CHECK (retry_score BETWEEN 0 AND 100),        -- 이 점수 미만이면 재질문 1회 (Q-21 보정)
    weight_content      smallint NOT NULL DEFAULT 60,
    weight_language     smallint NOT NULL DEFAULT 30,
    weight_nonverbal    smallint NOT NULL DEFAULT 10,
    llm_provider        text NOT NULL DEFAULT 'ollama'
                        CHECK (llm_provider IN ('ollama','anthropic','openai')),        -- 무료판 기본 ollama. 한 공고 안에서는 고정
    llm_eval_model      text NOT NULL DEFAULT 'qwen3:4b',             -- 유료판 예: claude-sonnet-5-5
    llm_fast_model      text NOT NULL DEFAULT 'qwen3:1.7b',             -- 30초 대체. 유료판 예: claude-haiku-5-5
    llm_local_model     text NOT NULL DEFAULT 'qwen3:4b',               -- 온프레미스. tier ≤ 2 문서·국외 전송 미동의는 항상 여기로 (RAG-17)
    locked_at           timestamptz,                                    -- 첫 응시 시작 시각. 이후 설정 변경 불가
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (weight_content + weight_language + weight_nonverbal = 100),
    CHECK (retry_score < follow_score)
);

-- ===== 2. 면접 응시 (CAN-008~013) =====
CREATE TABLE interview_session (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id      bigint NOT NULL REFERENCES application(id),
    attempt_no          smallint NOT NULL DEFAULT 1 CHECK (attempt_no BETWEEN 1 AND 3),   -- 재응시는 새 질문으로 새 행
    exam_code           text NOT NULL UNIQUE,                           -- 응시 고유 번호 (CAN-008)
    coding_session_id   bigint REFERENCES coding_session(id),           -- 비개발 직군은 NULL
    coding_weakness     jsonb,                                          -- 시작 때 복사한 코딩 약점 요약(CT-33). 3번 질문 입력, 비개발 직군은 NULL
    ct_band             text CHECK (ct_band IN ('상','중','하')),         -- 코딩 등급 → 난이도 (골드2·3 상, 골드4 중, 골드5·실버1 하)
    handoff             jsonb,                                          -- 1차 인계(handoff.json): 직무·레벨·결핍 가치. 2번 질문 입력
    project_topic       text,                                           -- 이력서와 가장 비슷한 회사 프로젝트(topic). 질문 준비 때 고정, 3~10번 기술 질문 근거
    overseas_consent    boolean NOT NULL DEFAULT false,                 -- 국외 전송 동의. 없으면 LLM 전부 온프레미스
    status              text NOT NULL DEFAULT 'ready' CHECK (status IN (
                          'ready','prechecked','in_progress','paused','completed','abandoned','system_error','retake_granted')),
    precheck            jsonb,                                          -- {chrome, camera, mic, upload_mbps, single_face}
    consent_at          timestamptz,                                    -- 유의사항·AI 활용 동의
    identity_status     text CHECK (identity_status IN ('match','unclear','mismatch')),     -- 시작 본인 확인 결과(지원자 비공개)
    llm_provider        text NOT NULL,                                  -- 설정에서 복사(응시 당시 값 보존)
    llm_eval_model      text NOT NULL,
    llm_fast_model      text NOT NULL,
    llm_local_model     text NOT NULL,
    extra_time_sec      integer NOT NULL DEFAULT 0 CHECK (extra_time_sec >= 0),   -- 시스템 장애로 받은 추가 시간
    started_at          timestamptz,
    ended_at            timestamptz,
    end_reason          text CHECK (end_reason IN ('finished','tab_leave','system_error','candidate_quit','admin_stop')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, attempt_no),
    CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at)
);

-- ===== 3. 질문. 번호 = 물어본 순서(1~10). 1번 이력서 본인 확인·2번 결핍 가치(비기술, 의견만) / 3~10번 기술 주제
--      (본 질문 tier 3 · 꼬리 1 tier 2 · 꼬리 2 tier 1, 재질문은 같은 근거로 형식만 바꿈) =====
CREATE TABLE interview_question (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          bigint NOT NULL REFERENCES interview_session(id) ON DELETE CASCADE,
    kind                text NOT NULL CHECK (kind IN ('non_tech','tech')),
    question_type       text NOT NULL DEFAULT 'main' CHECK (question_type IN ('main','followup','reask')),  -- 본·꼬리·되묻기
    depth               smallint NOT NULL DEFAULT 0 CHECK (depth BETWEEN 0 AND 2),  -- 꼬리질문 깊이 (재질문은 원래 질문 깊이)
    tech_stack          text,                                           -- 기술 주제 (40~70점이면 다른 주제로)
    parent_question_id  bigint,                                         -- 꼬리질문·되묻기면 바로 앞 질문 id
    ask_order           smallint NOT NULL CHECK (ask_order BETWEEN 1 AND 20),  -- 질문 번호 = 물어본 순서. 물어볼 때 저장
    question_text       text NOT NULL,
    basis               text,                                           -- 출제 근거 (ADM-033)
    source_doc_ids      jsonb,                                          -- 근거 청크 ID 목록 (doc#sec). 기술 질문만
    min_tier            smallint CHECK (min_tier BETWEEN 0 AND 3),     -- 프롬프트에 들어간 근거 중 가장 낮은 tier → LLM 경로
    rag_check           jsonb,                                          -- 재정렬 점수 (0.6 이상만 근거), 대체 사용 여부
    defense             jsonb,                                          -- 질문 방어 (CE 0.5, 금지어 수정·가림)
    key_points          jsonb,                                          -- 판정 체크리스트(핵심 요소)
    generated_by_model  text NOT NULL,
    generated_at        timestamptz NOT NULL DEFAULT now(),
    asked_at            timestamptz,
    UNIQUE (id, session_id),
    FOREIGN KEY (parent_question_id, session_id) REFERENCES interview_question(id, session_id),   -- 꼬리질문은 같은 응시 안에서만
    CHECK ((ask_order <= 2) = (kind = 'non_tech')),                    -- 1·2번 인성, 3번부터 기술
    CHECK (kind = 'non_tech' OR tech_stack IS NOT NULL),
    CHECK (kind = 'tech' OR question_type = 'main'),                    -- 인성 질문에는 꼬리질문·되묻기 없음
    CHECK ((question_type = 'main') = (parent_question_id IS NULL)),
    CHECK (question_type <> 'followup' OR depth >= 1),
    CHECK (question_type <> 'main' OR depth = 0)
);
-- 같은 질문에 되묻기는 한 번만
CREATE UNIQUE INDEX uq_question_reask ON interview_question (parent_question_id) WHERE question_type = 'reask';
CREATE UNIQUE INDEX uq_question_ask_order ON interview_question (session_id, ask_order);

-- ===== 4. 답변 (STT 텍스트만) =====
CREATE TABLE interview_answer (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question_id         bigint NOT NULL UNIQUE REFERENCES interview_question(id) ON DELETE CASCADE,  -- 재녹화 불가: 질문당 1개
    stt_text            text,                                           -- 무응답이면 NULL
    stt_model           text NOT NULL DEFAULT 'faster-whisper large-v3-turbo',
    answer_sec          numeric(6,1) CHECK (answer_sec >= 0),
    finished_in_time    boolean NOT NULL,                               -- 비언어 점수: 시간 안에 마침
    silence_ratio       numeric(4,3) CHECK (silence_ratio BETWEEN 0 AND 1),  -- 3초 이상 침묵 비율
    no_response         boolean NOT NULL DEFAULT false,
    audio_object_key    text,                                           -- 임시 음성 위치. STT 후 NULL로 비움
    audio_deleted_at    timestamptz,                                    -- 음성 삭제 증빙
    upload_retry_count  smallint NOT NULL DEFAULT 0 CHECK (upload_retry_count BETWEEN 0 AND 3),
    submitted_at        timestamptz NOT NULL DEFAULT now(),
    stt_done_at         timestamptz,
    -- 11/11 지원자 STT 확인·수정: 인식 원본은 남기고 stt_text는 확인한 글(판정에 씀). 인식 오류를 고치는 정도만(글자 차이 30% 이하)
    stt_original        text,                                           -- 지원자가 보기 전 STT 원본 (무응답·STT 실패면 NULL)
    stt_confirmed_at    timestamptz,                                    -- 지원자가 '완료'를 누른(또는 60초가 지난) 시각. 이때 판정 시작
    stt_edit_ratio      numeric(4,3) CHECK (stt_edit_ratio BETWEEN 0 AND 0.3),   -- 원본 대비 바뀐 비율
    CHECK (stt_edit_ratio IS NULL OR stt_original IS NOT NULL),
    -- 11/12 글로 답하기(응시 편의, 사전 신청 + 담당관 승인): text면 stt_text = 지원자가 쓴 글, 음성·STT 없음
    answer_mode         text NOT NULL DEFAULT 'voice' CHECK (answer_mode IN ('voice','text')),
    CHECK (no_response OR stt_text IS NOT NULL OR stt_done_at IS NULL),
    CHECK (stt_done_at IS NULL OR audio_object_key IS NULL)            -- STT가 끝났으면 음성 위치가 남아 있으면 안 됨
);

-- ===== 5. 턴별 판정 (면접 중, 꼬리질문 분기 근거) =====
CREATE TABLE answer_judgement (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    answer_id           bigint NOT NULL REFERENCES interview_answer(id) ON DELETE CASCADE,
    status              text NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','silent','no_stt','timeout','parse_error')),
    score               numeric(5,2) CHECK (score BETWEEN 0 AND 100),  -- 기술: 루브릭 합(정확성 30·회사 적용 30·깊이 25·구체성 15). 비기술·평가 실패는 NULL
    rubric              jsonb,                                          -- 항목별 점수·강점 인용(good_quote)·약점
    opinion             jsonb,                                          -- 비기술: 의견·인용·이력서 일치 여부·확인할 점
    lang_structure      smallint CHECK (lang_structure BETWEEN 0 AND 10),   -- 언어: 구조
    lang_terms          smallint CHECK (lang_terms BETWEEN 0 AND 10),       -- 용어 정확성
    lang_intent         smallint CHECK (lang_intent BETWEEN 0 AND 10),      -- 질문 의도 부합
    key_points_met      jsonb,
    quotes              jsonb,                                           -- 근거 인용 (STT 원문 안에 있어야 함)
    rationale           text NOT NULL,
    model_tier          text NOT NULL CHECK (model_tier IN ('eval','fast')),  -- fast = 30초 대체로 판정
    provider            text NOT NULL,
    model               text NOT NULL,
    latency_ms          integer CHECK (latency_ms >= 0),
    is_current          boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_judgement_current ON answer_judgement (answer_id) WHERE is_current;

-- ===== 6. 최종 평가 (ADM-033). 덮어쓰지 않고 버전으로 쌓음 =====
CREATE TABLE interview_evaluation (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          bigint NOT NULL REFERENCES interview_session(id) ON DELETE CASCADE,
    version_no          smallint NOT NULL CHECK (version_no BETWEEN 1 AND 2),   -- 1 = 첫 평가, 2 = 1회 재평가
    topic_scores        jsonb NOT NULL,                                 -- 주제 점수 T = S_d + 40 × 평균/100 (S0 0·S1 30·S2 60, 메인 3.9 제안). 배점은 Q-15 미결
    content_score       numeric(5,2) NOT NULL CHECK (content_score BETWEEN 0 AND 60),
    language_score      numeric(5,2) NOT NULL CHECK (language_score BETWEEN 0 AND 30),
    nonverbal_score     numeric(5,2) NOT NULL CHECK (nonverbal_score BETWEEN 0 AND 10),
    total_score         numeric(5,2) GENERATED ALWAYS AS (content_score + language_score + nonverbal_score) STORED,
    rationale           text NOT NULL,
    project_topic       text,                                           -- 판정 기준 프로젝트
    fit_opinion         text,                                           -- 적합성: 지금 이 프로젝트에 투입 가능한가 (의견, 점수 아님)
    growth_opinion      text,                                           -- 확장성: 다른 프로젝트로 옮겨도 해낼 수 있는가 (의견, 점수 아님)
    provider            text NOT NULL,
    model               text NOT NULL,
    status              text NOT NULL DEFAULT 'checking' CHECK (status IN ('checking','passed','failed')),
    confirmed_by        bigint REFERENCES admin_user(id),               -- 담당자 확정 (점수 수정은 불가)
    confirmed_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, version_no),
    CHECK (confirmed_at IS NULL OR status = 'passed')
);

-- ===== 7. 검증 AI 5검사 =====
CREATE TABLE evaluation_check (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evaluation_id       bigint NOT NULL REFERENCES interview_evaluation(id) ON DELETE CASCADE,
    check_no            smallint NOT NULL CHECK (check_no BETWEEN 1 AND 5),
    -- 1 형식·범위, 2 인용 실재, 3 체크리스트 일치, 4 금지 요소(성별·나이·외모·출신·말투), 5 근거–점수 정합(빠른 LLM)
    passed              boolean NOT NULL,
    detail              text,
    checker             text NOT NULL,                                  -- 'code' 또는 모델명
    checked_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (evaluation_id, check_no)
);

-- ===== 8. AI 평가 오류 알림 (ADM-036). 서류·코딩과 같이 쓰도록 stage 구분 =====
CREATE TABLE ai_error_alert (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage               text NOT NULL CHECK (stage IN ('document','coding','interview')),
    application_id      bigint NOT NULL REFERENCES application(id),
    interview_evaluation_id bigint REFERENCES interview_evaluation(id),
    problem_part        text NOT NULL,                                  -- 어느 부분이 문제인지
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','done')),
    handled_by          bigint REFERENCES admin_user(id),
    handled_at          timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (stage <> 'interview' OR interview_evaluation_id IS NOT NULL)
);

-- ===== 9. 본인 확인 (얼굴 대조 결과만. 사진 저장 안 함) =====
CREATE TABLE identity_check (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          bigint NOT NULL REFERENCES interview_session(id) ON DELETE CASCADE,
    phase               text NOT NULL CHECK (phase IN ('start','retake','recheck')),   -- recheck = 60초마다
    retake_no           smallint NOT NULL DEFAULT 0 CHECK (retake_no BETWEEN 0 AND 3),
    distance            numeric(5,4) CHECK (distance BETWEEN 0 AND 2),  -- ArcFace 코사인 거리, 얼굴 못 찾으면 NULL
    band                text NOT NULL CHECK (band IN ('match','unclear','mismatch','no_face')),
    model               text NOT NULL DEFAULT 'ArcFace',
    checked_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (band = 'no_face' OR distance IS NOT NULL),
    liveness            text CHECK (liveness IN ('pass','fail'))    -- 11/12 시작 전 1회: 고개 돌리기·눈 깜빡이기 (사진·영상 대리 응시 방지). recheck는 NULL
);

-- ===== 9-1. 응시 편의 신청 (11/12): 말하기가 어려운 지원자의 '글로 답하기'. 지원자가 응시 전에 신청 → 담당관이 승인·거절 =====
CREATE TABLE answer_accommodation (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id      bigint NOT NULL UNIQUE REFERENCES application(id) ON DELETE CASCADE,   -- 지원 건당 1개 (다시 신청하면 내용을 바꿈)
    kind                text NOT NULL DEFAULT 'text_answer' CHECK (kind IN ('text_answer')),
    reason              text NOT NULL CHECK (length(reason) BETWEEN 5 AND 500),
    status              text NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','approved','rejected')),
    decided_by          bigint REFERENCES admin_user(id),
    decided_at          timestamptz,
    decision_note       text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'requested') = (decided_by IS NULL AND decided_at IS NULL))   -- 사람이 결정해야만 승인·거절
);

-- ===== 10. 응시 중 이벤트 (이탈·얼굴 감지·연결) =====
CREATE TABLE proctor_event (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          bigint NOT NULL REFERENCES interview_session(id) ON DELETE CASCADE,
    event_type          text NOT NULL CHECK (event_type IN (
                          'tab_leave','window_blur','face_missing','multi_face','gaze_away','identity_mismatch',
                          'network_drop','reconnect','upload_fail')),         -- gaze_away: 시선 화면 밖(부정행위 감지용, 점수에는 안 씀)
    occurred_at         timestamptz NOT NULL,
    duration_ms         integer CHECK (duration_ms >= 0),
    occurrence_no       smallint,                                       -- 이 종류 몇 번째 (탭 이탈 누적 2회 판단)
    action              text NOT NULL CHECK (action IN ('logged','warned','abandoned','suspected')),
    question_id         bigint REFERENCES interview_question(id),
    meta                jsonb
);

-- ===== 11. 부정행위 의심 건 (ADM-035). 서류·코딩과 같이 쓰도록 stage 구분 =====
CREATE TABLE suspicion_case (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage               text NOT NULL CHECK (stage IN ('document','coding','interview')),
    application_id      bigint NOT NULL REFERENCES application(id),
    interview_session_id bigint REFERENCES interview_session(id),
    reason              text NOT NULL CHECK (reason IN (
                          'tab_leave','face_missing','multi_face','gaze_away','identity_unclear','identity_mismatch','paste','plagiarism')),
    evidence            jsonb,                                          -- 관련 이벤트·대조 id 목록 (영상 없음)
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open','explanation_requested','explained','decided')),
    explanation_due_at  timestamptz,                                    -- 소명 기한
    explanation_text    text,
    decision            text CHECK (decision IN ('normal','warning','disqualified')),
    decision_reason     text,
    decided_by          bigint REFERENCES admin_user(id),
    decided_at          timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'decided') = (decision IS NOT NULL AND decided_by IS NOT NULL AND decided_at IS NOT NULL)),  -- 사람이 결정해야만 확정
    CHECK (stage <> 'interview' OR interview_session_id IS NOT NULL)
);

-- ===== 12. 장애·챗봇 (CAN-012 문의하기) =====
CREATE TABLE interview_incident (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          bigint NOT NULL REFERENCES interview_session(id) ON DELETE CASCADE,
    error_code          text NOT NULL,                                  -- 예: LLM_TIMEOUT_60S, UPLOAD_FAIL_3X
    cause               text NOT NULL CHECK (cause IN ('system','candidate','unknown')),
    chat_started_at     timestamptz NOT NULL,
    chat_ended_at       timestamptz,
    extra_time_sec      integer NOT NULL DEFAULT 0 CHECK (extra_time_sec >= 0),
    outcome             text CHECK (outcome IN ('resumed','stopped_reported','retake_granted')),
    report_sent_at      timestamptz,                                    -- 담당자 리포트
    CHECK (cause = 'system' OR extra_time_sec = 0)                     -- 응시자 결함이면 추가 시간 없음
);

-- ===== 13. 담당자 메모 (F-ADM-45) =====
CREATE TABLE interview_note (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          bigint NOT NULL REFERENCES interview_session(id) ON DELETE CASCADE,
    author_id           bigint NOT NULL REFERENCES admin_user(id),
    body                text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- ===== 14. LLM 호출 기록 (활동다이어그램 1109 5쪽, 11/9 승인). 프롬프트 본문은 남기지 않는다 =====
CREATE TABLE llm_call (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          bigint REFERENCES interview_session(id) ON DELETE CASCADE,   -- 면접 밖 호출(1차 서류 등)은 NULL
    application_id      bigint REFERENCES application(id) ON DELETE CASCADE,
    purpose             text NOT NULL,                                  -- q1_verify·tech_main·judge·doc_screen …
    prompt_version      text NOT NULL,                                  -- 프롬프트 파일 해시 8자리
    provider            text NOT NULL,
    model               text NOT NULL,
    min_tier            smallint CHECK (min_tier BETWEEN 0 AND 3),
    input_tokens        integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens       integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    latency_ms          integer NOT NULL CHECK (latency_ms >= 0),
    ok                  boolean NOT NULL,
    route_note          text,                                           -- LEAK_BLOCKED·AUTH_ERROR·RETRY n
    error               text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_llm_call_session ON llm_call (session_id, created_at);

-- ===== 15. 직무별 회사 질문 은행 (11/10 승인). 회사가 미리 뽑아 둔 기술 본 질문. 근거는 tier 3 공개 청크 =====
CREATE TABLE question_bank (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_role            text NOT NULL,                                  -- job_posting.job_role (백엔드·프론트엔드·AI·데이터·임베디드)
    topic               text NOT NULL,                                  -- 회사 프로젝트 주제
    chunk_id            text NOT NULL,                                  -- 근거 청크 doc#sec (tier 3)
    question_text       text NOT NULL,
    key_points          jsonb NOT NULL,
    model               text NOT NULL,
    verified            boolean NOT NULL DEFAULT false,                 -- 코드 검증 통과만 출제 후보
    verify_note         text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_role, chunk_id)
);

-- ===== 16. 지원 건마다 미리 만든 질문 (11/10 승인). 1차 합격 즉시 1·2번 + 기술 본 질문 후보, 코딩이 끝나면 3번. 검증 통과(ready)만 출제 =====
CREATE TABLE prepared_question (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id      bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    slot                smallint NOT NULL CHECK (slot BETWEEN 1 AND 10),   -- 1·2 비기술, 3 코딩 약점 본 질문, 4~10 기술 본 질문 후보(순서대로 출제)
    kind                text NOT NULL CHECK (kind IN ('non_tech','tech')),
    tech_stack          text,
    question_text       text NOT NULL,
    basis               text,
    source_doc_ids      jsonb,
    min_tier            smallint CHECK (min_tier BETWEEN 0 AND 3),
    key_points          jsonb NOT NULL,
    model               text NOT NULL,
    bank_id             bigint REFERENCES question_bank(id),
    status              text NOT NULL CHECK (status IN ('ready','failed')),
    verify              jsonb NOT NULL,                                 -- 검사 항목별 결과
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, slot),
    CHECK ((slot <= 2) = (kind = 'non_tech'))
);

-- ===== 17. 답변 구간별 표정·목소리 표기 (11/10 승인). 점수에 쓰지 않고 관리자 리포트에 표기만. 사진·음성은 저장하지 않고 수치만 =====
CREATE TABLE answer_signal (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    answer_id           bigint NOT NULL REFERENCES interview_answer(id) ON DELETE CASCADE,
    source              text NOT NULL CHECK (source IN ('face','voice')),
    t_start_ms          integer NOT NULL CHECK (t_start_ms >= 0),
    t_end_ms            integer NOT NULL CHECK (t_end_ms >= t_start_ms),
    label               text NOT NULL,                                  -- 예: 자신감 있는 목소리·작은 목소리·미소·긴장·시선 아래
    value               jsonb,                                          -- 수치 (음량·높낮이·말 빠르기, 표정 계수 평균)
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_signal_answer ON answer_signal (answer_id, source, t_start_ms);

-- ===== 18. 지원 건 상세 단계 11종 (DB TRD 11-08 migration 0017, 활동다이어그램 1109 6쪽, 11/10 승인) =====
-- 공통 스키마 application.status(다른 파트 소유)는 그대로 두고, 6.1 쪽에 문서의 상태 11종과 허용 전이만 받는 규칙을 둔다.
-- 행이 없는 지원 건(시드·옛 자료)은 application.status에서 읽어 낸다 (v_application_stage).
CREATE TABLE stage_transition (                                 -- 허용 전이 표 (status_transitions)
    from_stage          text NOT NULL,
    to_stage            text NOT NULL,
    PRIMARY KEY (from_stage, to_stage)
);
INSERT INTO stage_transition VALUES
    ('submitted','screen_failed'), ('submitted','screen_passed'), ('submitted','screen_rejected'),
    ('screen_passed','coding_waiting'), ('screen_rejected','screen_passed'),
    ('coding_waiting','scheduled'), ('scheduled','coding_waiting'), ('scheduled','coding'), ('scheduled','interview'),
    ('coding','interview'), ('interview','final_pass'), ('interview','final_fail'),
    ('final_pass','interview'), ('final_fail','interview'),                       -- 최종 발표 전 결정 취소
    -- 1차 합격 뒤 부정행위 발견(지원서와 지원자가 다름 등): 사유·결정자 필수 (11/10)
    ('screen_passed','screen_rejected'), ('coding_waiting','screen_rejected'), ('scheduled','screen_rejected'),
    ('coding','screen_rejected'), ('interview','screen_rejected'),
    -- 최종 전에는 어디서든 지원 취소
    ('submitted','withdrawn'), ('screen_passed','withdrawn'), ('coding_waiting','withdrawn'), ('scheduled','withdrawn'),
    ('coding','withdrawn'), ('interview','withdrawn');

CREATE TABLE application_stage (
    application_id      bigint PRIMARY KEY REFERENCES application(id) ON DELETE CASCADE,
    stage               text NOT NULL CHECK (stage IN ('submitted','screen_failed','screen_passed','screen_rejected','coding_waiting',
                          'scheduled','coding','interview','final_pass','final_fail','withdrawn')),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE application_stage_log (                            -- 바뀐 기록 (쌓기만). 누가·왜
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id      bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    from_stage          text,
    to_stage            text NOT NULL,
    actor_type          text NOT NULL CHECK (actor_type IN ('admin','candidate','system')),
    actor_id            bigint,
    reason              text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (to_stage <> 'screen_rejected' OR from_stage IN ('submitted') OR (reason IS NOT NULL AND actor_type = 'admin'))   -- 합격 취소는 사유·담당관 필수
);

CREATE FUNCTION trg_stage_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.stage <> OLD.stage
       AND NOT EXISTS (SELECT 1 FROM stage_transition WHERE from_stage = OLD.stage AND to_stage = NEW.stage) THEN
        RAISE EXCEPTION 'stage_transition_denied: % -> %', OLD.stage, NEW.stage USING ERRCODE = 'check_violation';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER trg_application_stage BEFORE UPDATE ON application_stage FOR EACH ROW EXECUTE FUNCTION trg_stage_transition();

-- 행이 없으면 공통 상태에서 읽어 낸 단계 (시드·옛 자료). 코드는 처음 옮길 때 이 값으로 행을 만든다
-- 6.1 스키마만 따로 시험할 때(공통 application에 status 칸이 없는 최소 정의)는 보기를 만들지 않는다
DO $view$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'application' AND column_name = 'status') THEN
    EXECUTE $sql$
CREATE VIEW v_application_stage AS
SELECT a.id AS application_id, coalesce(st.stage, CASE
        WHEN a.status = 'submitted' THEN 'submitted'
        WHEN a.status IN ('doc_failed') THEN 'screen_rejected'
        WHEN a.status = 'doc_passed' THEN 'screen_passed'
        WHEN a.status = 'withdrawn' THEN 'withdrawn'
        WHEN a.status IN ('final_passed', 'reserve') THEN 'final_pass'
        WHEN a.status = 'final_failed' THEN 'final_fail'
        WHEN a.status IN ('stage2_done', 'abandoned') OR EXISTS (SELECT 1 FROM interview_session s WHERE s.application_id = a.id
                                                                   AND s.status <> 'prechecked' AND s.status <> 'ready') THEN 'interview'
        WHEN EXISTS (SELECT 1 FROM coding_session c WHERE c.application_id = a.id) THEN 'coding'
        ELSE 'scheduled' END) AS stage,
    st.updated_at
FROM application a LEFT JOIN application_stage st ON st.application_id = a.id
    $sql$;
  END IF;
END $view$;

-- ===== 조회용 인덱스 =====
CREATE INDEX ix_session_application ON interview_session (application_id);
CREATE INDEX ix_session_status ON interview_session (status);
CREATE INDEX ix_event_session ON proctor_event (session_id, event_type, occurred_at);
CREATE INDEX ix_identity_session ON identity_check (session_id, checked_at);
CREATE INDEX ix_suspicion_open ON suspicion_case (status) WHERE status <> 'decided';
CREATE INDEX ix_alert_open ON ai_error_alert (status) WHERE status <> 'done';
CREATE INDEX ix_answer_audio_pending ON interview_answer (submitted_at) WHERE audio_object_key IS NOT NULL;
