-- AI 채용 솔루션 전체 데이터 모델 (예시) · PostgreSQL 17 · 2026-11-01
-- 화상면접 영역은 interview_schema.sql (이 파일 다음에 실행). 이 파일은 그 외 전부.
-- 기준: 화면정의서(ADM·CAN) + 기능정의서 기능 ID + 팀 결정. 상태값은 text + CHECK.
CREATE EXTENSION IF NOT EXISTS vector;   -- FAQ 검색(챗봇)용 pgvector

-- ============ 1. 계정·인증 (CAN-003·004, ADM-001·010·011) ============
CREATE TABLE department (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL UNIQUE
);

CREATE TABLE admin_user (                                    -- 최고관리자·시스템관리자·채용담당자·현업 부서
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login_id        text NOT NULL UNIQUE,
    password_hash   text NOT NULL,
    name            text NOT NULL,
    role            text NOT NULL CHECK (role IN ('super_admin','sys_admin','recruiter','dept_member')),
    department_id   bigint REFERENCES department(id),
    totp_secret_enc text,                                    -- 2단계 인증 (F-ADM-27), 암호화 저장
    allowed_ip      cidr,                                    -- 접속 제한
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (role <> 'dept_member' OR department_id IS NOT NULL),
    CHECK (role = 'dept_member' OR totp_secret_enc IS NOT NULL OR NOT is_active)   -- 관리자 계정은 2단계 인증 필수
);

CREATE TABLE candidate (                                     -- 지원자
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email           text NOT NULL UNIQUE,
    password_hash   text,                                    -- 소셜 로그인만 쓰면 NULL
    name            text NOT NULL,
    phone           text NOT NULL,
    ci_hash         text NOT NULL UNIQUE,                    -- 휴대폰 본인인증 식별값(CI) 해시 → 1인 1계정 (F-SYS-07)
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active','withdrawn')),
    withdrawn_at    timestamptz,
    rejoin_blocked_until timestamptz,                        -- 탈퇴 후 재가입 제한
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'withdrawn') = (withdrawn_at IS NOT NULL))
);

CREATE TABLE candidate_social_account (                      -- 구글·카카오·네이버
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_id    bigint NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    provider        text NOT NULL CHECK (provider IN ('google','kakao','naver')),
    provider_user_id text NOT NULL,
    UNIQUE (provider, provider_user_id),
    UNIQUE (candidate_id, provider)
);

CREATE TABLE login_history (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_type       text NOT NULL CHECK (user_type IN ('candidate','admin')),
    user_id         bigint NOT NULL,
    success         boolean NOT NULL,
    ip              inet,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ============ 2. 동의·정책 (ADM-012·013, CAN-003, F-CAN-19) ============
CREATE TABLE consent_document (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN ('terms','privacy','ai_usage')),   -- ai_usage: 답변 텍스트 외부 AI 전송 등
    version         integer NOT NULL CHECK (version >= 1),
    body            text NOT NULL,
    effective_at    timestamptz NOT NULL,
    UNIQUE (kind, version)
);

CREATE TABLE candidate_consent (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_id    bigint NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    consent_document_id bigint NOT NULL REFERENCES consent_document(id),
    agreed_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, consent_document_id)               -- 개정되면 새 버전에 다시 동의(재동의)
);

CREATE TABLE policy_setting (                                -- 지원 정책·보관 기간 등 (ADM-012·013)
    key             text PRIMARY KEY,                        -- 예: retention_days_failed, rejoin_block_days
    value           jsonb NOT NULL,
    updated_by      bigint REFERENCES admin_user(id),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- ============ 3. 채용 요청·공고 (ADM-020~025) ============
CREATE TABLE hiring_request (                                -- 현업 부서 채용 요청
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    department_id   bigint NOT NULL REFERENCES department(id),
    requested_by    bigint NOT NULL REFERENCES admin_user(id),
    title           text NOT NULL,
    job_role        text NOT NULL,
    headcount       smallint NOT NULL CHECK (headcount > 0),
    career_level    text NOT NULL CHECK (career_level IN ('new','junior','senior')),   -- 신입 0~2, 주니어 3~5, 시니어 6+
    reason          text,
    status          text NOT NULL DEFAULT 'submitted' CHECK (status IN ('draft','submitted','accepted','rejected','converted')),
    handled_by      bigint REFERENCES admin_user(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job_posting (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hiring_request_id bigint UNIQUE REFERENCES hiring_request(id),   -- 요청 1건 → 공고 1건
    title           text NOT NULL,
    job_role        text NOT NULL,
    job_category    text NOT NULL CHECK (job_category IN ('dev','non_dev')),   -- dev면 코딩 테스트 있음
    career_level    text NOT NULL CHECK (career_level IN ('new','junior','senior')),
    headcount       smallint NOT NULL CHECK (headcount > 0),
    description     text,
    status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','dept_review','published','closed','finished')),
    apply_start     timestamptz NOT NULL,
    apply_end       timestamptz NOT NULL,
    doc_announce_at timestamptz NOT NULL,                    -- 1차(서류) 발표
    stage2_start    timestamptz NOT NULL,                    -- 2차(코딩+면접) 응시 기간
    stage2_end      timestamptz NOT NULL,
    final_announce_at timestamptz NOT NULL,
    created_by      bigint NOT NULL REFERENCES admin_user(id),
    published_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (apply_start < apply_end AND apply_end <= doc_announce_at AND doc_announce_at <= stage2_start
           AND stage2_start < stage2_end AND stage2_end <= final_announce_at),
    CHECK (status IN ('draft','dept_review') OR published_at IS NOT NULL)
);

CREATE TABLE posting_assignee (                              -- 정·부 담당자 (F-ADM-64, 담당 공고 권한 F-ADM-28)
    posting_id      bigint NOT NULL REFERENCES job_posting(id) ON DELETE CASCADE,
    admin_user_id   bigint NOT NULL REFERENCES admin_user(id),
    role            text NOT NULL CHECK (role IN ('main','sub')),
    PRIMARY KEY (posting_id, admin_user_id)
);
CREATE UNIQUE INDEX uq_posting_main ON posting_assignee (posting_id) WHERE role = 'main';

CREATE TABLE posting_review (                                -- 게시 전 요청 부서 확인 (ADM-023)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES job_posting(id) ON DELETE CASCADE,
    reviewer_id     bigint NOT NULL REFERENCES admin_user(id),
    decision        text NOT NULL CHECK (decision IN ('approved','changes_requested')),
    comment         text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE posting_history (                               -- 공고 수정 이력 (F-ADM-34·61)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES job_posting(id) ON DELETE CASCADE,
    changed_by      bigint NOT NULL REFERENCES admin_user(id),
    change          jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_criteria (                             -- 서류 평가 기준 (F-ADM-68)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES job_posting(id) ON DELETE CASCADE,
    item            text NOT NULL,
    weight          smallint NOT NULL CHECK (weight BETWEEN 1 AND 100),
    description     text,
    UNIQUE (posting_id, item)
);

CREATE TABLE coding_setting (                                -- 코딩 테스트 설정 (ADM-025, F-ADM-38·39)
    posting_id      bigint PRIMARY KEY REFERENCES job_posting(id) ON DELETE CASCADE,
    languages       text[] NOT NULL CHECK (cardinality(languages) >= 1),
    time_limit_min  smallint NOT NULL DEFAULT 90 CHECK (time_limit_min BETWEEN 10 AND 300)
);

-- ============ 4. 지원·서류 (CAN-005·006·007, ADM-030·031) ============
CREATE TABLE resume (                                        -- 작성 중 자동 저장·지난 지원서 불러오기 (F-CAN-11·12)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_id    bigint NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    content         jsonb NOT NULL,                          -- 학력·경력·자기소개 등 양식 (F-ADM-36)
    photo_object_key text,                                   -- 본인 확인용 사진 (평가에 사용 안 함)
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE application (                                   -- 지원서 (공고 × 지원자)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES job_posting(id),
    candidate_id    bigint NOT NULL REFERENCES candidate(id),
    resume_snapshot jsonb NOT NULL,                          -- 제출 시점 내용 고정
    photo_object_key text,
    status          text NOT NULL DEFAULT 'submitted' CHECK (status IN (
                      'submitted','doc_passed','doc_failed','stage2','stage2_done',
                      'final_passed','reserve','final_failed','withdrawn','abandoned')),
    submitted_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (posting_id, candidate_id)                        -- 1인 1지원 (F-SYS-01)
);

CREATE TABLE document_evaluation (                           -- AI 서류 적합도 (F-AI-02), 버전으로 쌓음
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    version_no      smallint NOT NULL CHECK (version_no BETWEEN 1 AND 2),
    fit_score       numeric(5,2) NOT NULL CHECK (fit_score BETWEEN 0 AND 100),
    criteria_scores jsonb NOT NULL,                          -- document_criteria 항목별 점수
    deduction       smallint NOT NULL DEFAULT 0 CHECK (deduction BETWEEN -10 AND 0),   -- 성실도 감점(복사 -5, 누락 -3 …)
    rationale       text NOT NULL,
    handoff         jsonb,                                   -- 1차 → 화상 면접 인계: job_role·applied_level·deficit_value·deficit_reason (형식 11/6 확정)
    provider        text NOT NULL,
    model           text NOT NULL,
    status          text NOT NULL DEFAULT 'checking' CHECK (status IN ('checking','passed','failed')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, version_no)
);

CREATE TABLE document_review (                               -- 담당자 서류 의견 (F-ADM-71)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    reviewer_id     bigint NOT NULL REFERENCES admin_user(id),
    opinion         text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE stage_result (                                  -- 전형 결과 확정: 사람만 (서류·최종)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    stage           text NOT NULL CHECK (stage IN ('document','final')),
    result          text NOT NULL CHECK (result IN ('pass','fail','reserve')),
    reserve_rank    smallint CHECK (reserve_rank BETWEEN 1 AND 5),   -- 예비 최대 5명 (F-ADM-48)
    reason          text,
    decided_by      bigint NOT NULL REFERENCES admin_user(id),
    decided_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_id, stage),
    CHECK ((result = 'reserve') = (reserve_rank IS NOT NULL)),
    CHECK (stage = 'final' OR result <> 'reserve')
);

-- ============ 5. 2차 응시: 일정 예외·코딩 (CAN-008·010, ADM-032·034) ============
CREATE TABLE stage2_exception (                              -- 개별 응시 기간 연장·재응시 예외 (F-ADM-42)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN ('extend','retake')),
    until_at        timestamptz NOT NULL,
    reason          text NOT NULL,
    approved_by     bigint NOT NULL REFERENCES admin_user(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- 코딩 테스트 테이블: 6.2 「코딩 테스트 TRD 및 프로토타입 검토」(11/1, 11/4 갱신) 9장 저장 스키마 초안을 그대로 옮김
CREATE TABLE coding_session (                                -- 응시 1회 (문항·남은 시간은 서버가 관리, CT-30·31)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    attempt_no      smallint NOT NULL DEFAULT 1 CHECK (attempt_no BETWEEN 1 AND 3),
    status          text NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','completed','abandoned','system_error')),
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    UNIQUE (application_id, attempt_no)
);

CREATE TABLE coding_problem (                                -- 재현·대체 문제 풀 (CT-01·02·07)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slot            smallint NOT NULL CHECK (slot BETWEEN 1 AND 3),
    tier            text NOT NULL CHECK (tier IN ('실버1','골드5','골드4','골드3','골드2')),
    type            text NOT NULL,                           -- 알고리즘 유형 (등급별 허용표 안에서)
    mode            text NOT NULL CHECK (mode IN ('stdio','function')),
    origin          text NOT NULL CHECK (origin IN ('collected','generated')),   -- 수집 출처 수정본 / LLM 즉석 출제
    statement       text NOT NULL,                           -- 수정 지문
    solution_python text NOT NULL,                           -- 정답 코드 (두 언어, CT-04)
    solution_java   text NOT NULL,
    brute_force     text,                                    -- 완전탐색 풀이 (size 1~2 교차 검증)
    wrong_codes     jsonb NOT NULL DEFAULT '[]',             -- 오답 코드 3~5개 + 분류(사소한 실수/접근 오류, CT-17)
    generator       text NOT NULL,
    validator       text NOT NULL,
    seed            bigint NOT NULL,
    time_limits     jsonb NOT NULL,                          -- 언어별 제한 시간 (CT-22)
    prompt_version  text,
    source_doc_ids  jsonb,                                   -- 3번: 검색된 정돌테크 문서 (CT-14)
    validated_at    timestamptz                              -- 교차 검증 통과 시각
);

CREATE TABLE coding_case (                                   -- 채점 기준 (CT-21)
    problem_id      bigint NOT NULL REFERENCES coding_problem(id) ON DELETE CASCADE,
    case_no         int NOT NULL,
    size            smallint NOT NULL CHECK (size BETWEEN 1 AND 5),   -- 그룹 = size
    input           text NOT NULL,
    expected        text NOT NULL,                           -- 브라우저로 보내지 않음 (NFR-CT-02)
    is_sample       boolean NOT NULL DEFAULT false,          -- 예제는 점수에서 뺌
    in_grading_set  boolean NOT NULL DEFAULT true,
    kills           jsonb NOT NULL DEFAULT '[]',             -- 걸러낸 오답 코드 번호
    PRIMARY KEY (problem_id, case_no)
);

CREATE TABLE coding_attempt (                                -- 문항 배정 기록 (CT-30)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      bigint NOT NULL REFERENCES coding_session(id) ON DELETE CASCADE,
    slot            smallint NOT NULL CHECK (slot BETWEEN 1 AND 3),
    problem_id      bigint NOT NULL REFERENCES coding_problem(id),
    language        text NOT NULL CHECK (language IN ('python','java')),
    assigned_reason jsonb,                                   -- 등급 산식·유형 선택 이유
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz,
    UNIQUE (session_id, slot)
);

CREATE TABLE coding_submission (                             -- 모든 제출 (CT-25·32)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    attempt_id      bigint NOT NULL REFERENCES coding_attempt(id) ON DELETE CASCADE,
    submitted_at    timestamptz NOT NULL DEFAULT now(),
    language        text NOT NULL CHECK (language IN ('python','java')),
    code            text NOT NULL,
    case_results    jsonb NOT NULL,                          -- 케이스별 판정·시간
    group_scores    jsonb NOT NULL,                          -- 그룹(size)별 점수
    partial_score   numeric(5,2) NOT NULL CHECK (partial_score BETWEEN 0 AND 100),
    paste_attempts  smallint NOT NULL DEFAULT 0 CHECK (paste_attempts >= 0)   -- 붙여넣기 시도 (F-SYS-18)
);

CREATE TABLE coding_review (                                 -- 코드 리뷰 (CT-11·18). 면접 담당자 화면·화상 면접 입력
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    attempt_id      bigint NOT NULL REFERENCES coding_attempt(id) ON DELETE CASCADE,
    rubric          jsonb NOT NULL,                          -- 항목별 의견·근거 줄 (가독성·복잡도·경계 처리·언어 관용법)
    summary         jsonb NOT NULL,                          -- 구조화 요약: 사용 알고리즘·실패 그룹·약점 태그
    quality_level   text NOT NULL,                           -- LLM 품질 평가(실력 수준). 코딩 점수에는 넣지 않음
    critic_used     boolean NOT NULL DEFAULT false,          -- review_critic 보완 여부
    no_evidence     boolean NOT NULL DEFAULT false,          -- '문서 근거 없음' 표시
    model           text NOT NULL,
    prompt_version  text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE coding_result (                                 -- 관리자 첫 화면 (CT-24·33·35)
    session_id      bigint PRIMARY KEY REFERENCES coding_session(id) ON DELETE CASCADE,
    p1              numeric(5,2) NOT NULL CHECK (p1 BETWEEN 0 AND 100),     -- 1번 부분 점수
    p2              numeric(5,2) NOT NULL CHECK (p2 BETWEEN 0 AND 100),
    q3_base_tier    text NOT NULL CHECK (q3_base_tier IN ('실버1','골드5','골드4','골드3','골드2')),
    q3_tier         text NOT NULL CHECK (q3_tier IN ('실버1','골드5','골드4','골드3','골드2')),   -- 상향 반영
    upgrade_reason  jsonb,                                   -- 상향 사유 (신호·LLM 설명, CT-17)
    q3_partial      numeric(5,2) NOT NULL CHECK (q3_partial BETWEEN 0 AND 100),
    q3_converted    numeric(5,2) NOT NULL CHECK (q3_converted BETWEEN 0 AND 100),  -- 시작 점수(등급) + 40 × p/100 → 2차 종합의 코딩 점수
    score_table_version text NOT NULL,
    fallback_flags  jsonb,                                   -- 대체 경로 사용 기록 (CT-07·15)
    weakness_summary jsonb NOT NULL                          -- 1·2·3번 리뷰 구조화 요약 → 화상 면접 3번(첫 기술 질문) 입력 (CT-33)
);

-- ============ 6. 2차 종합·최종 (ADM-040·041·042·043) ============
CREATE TABLE stage2_score (                                  -- 2차 종합 (F-SYS-08)
    application_id  bigint PRIMARY KEY REFERENCES application(id) ON DELETE CASCADE,
    interview_score numeric(5,2) NOT NULL CHECK (interview_score BETWEEN 0 AND 100),   -- interview_evaluation.total_score
    coding_score    numeric(5,2) CHECK (coding_score BETWEEN 0 AND 100),             -- coding_result.q3_converted. 비개발 직군은 NULL
    total_score     numeric(5,2) GENERATED ALWAYS AS (
                      CASE WHEN coding_score IS NULL THEN interview_score
                           ELSE round(interview_score * 0.6 + coding_score * 0.4, 2) END) STORED,
    fail_cut        boolean GENERATED ALWAYS AS (interview_score < 50 OR coalesce(coding_score, 100) < 40) STORED,
    ai_rank         integer CHECK (ai_rank >= 1),
    ai_recommendation text NOT NULL DEFAULT 'none' CHECK (ai_recommendation IN ('pass','reserve','none')),
    computed_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (NOT fail_cut OR ai_recommendation = 'none')       -- 과락이면 AI 추천 불가
);

CREATE TABLE dept_opinion (                                  -- 요청 부서 결과 검토·의견 (ADM-041)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  bigint NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    author_id       bigint NOT NULL REFERENCES admin_user(id),
    opinion         text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE announcement (                                  -- 결과 발표 (F-ADM-19·46)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    posting_id      bigint NOT NULL REFERENCES job_posting(id),
    stage           text NOT NULL CHECK (stage IN ('document','final')),
    status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','checked','published','corrected')),
    checked_by      bigint REFERENCES admin_user(id),        -- 발표 전 검수
    published_by    bigint REFERENCES admin_user(id),
    published_at    timestamptz,
    UNIQUE (posting_id, stage),
    CHECK (status IN ('draft') OR checked_by IS NOT NULL),
    CHECK (status NOT IN ('published','corrected') OR (published_by IS NOT NULL AND published_at IS NOT NULL))
);

CREATE TABLE notification (                                  -- 메일·문자 (결과 내용 없이 링크만)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_id    bigint REFERENCES candidate(id) ON DELETE CASCADE,
    admin_user_id   bigint REFERENCES admin_user(id),
    channel         text NOT NULL CHECK (channel IN ('email','sms')),
    template        text NOT NULL,                           -- doc_result_ready, stage2_reminder, final_result_ready, ai_error …
    announcement_id bigint REFERENCES announcement(id),
    status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','failed')),
    sent_at         timestamptz,
    CHECK (num_nonnulls(candidate_id, admin_user_id) = 1)
);

CREATE TABLE notification_pref (                             -- 알림 수신 설정 (F-CAN-18)
    candidate_id    bigint PRIMARY KEY REFERENCES candidate(id) ON DELETE CASCADE,
    email           boolean NOT NULL DEFAULT true,
    sms             boolean NOT NULL DEFAULT true
);

-- ============ 7. 운영 (ADM-015·044·050, CAN-014·015) ============
CREATE TABLE audit_log (                                     -- 감사 로그 (F-ADM-25): 내보내기·결정·설정 변경
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_type      text NOT NULL CHECK (actor_type IN ('admin','candidate','system')),
    actor_id        bigint,
    action          text NOT NULL,                           -- export_passed_list, decide_final, publish_announcement …
    target_type     text NOT NULL,
    target_id       bigint,
    detail          jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE inquiry (                                       -- 1:1 문의 (F-CAN-17)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_id    bigint NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
    application_id  bigint REFERENCES application(id) ON DELETE SET NULL,
    title           text NOT NULL,
    body            text NOT NULL,
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','closed')),
    answer          text,
    answered_by     bigint REFERENCES admin_user(id),
    answered_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (status = 'open' OR (answer IS NOT NULL AND answered_by IS NOT NULL))
);

CREATE TABLE faq (                                           -- FAQ + 챗봇 검색
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question        text NOT NULL,
    answer          text NOT NULL,
    embedding       vector(1024),                            -- bge-m3 / KURE-v1 (Ollama, 무료). 유료판 text-embedding-3-small은 1536
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE company_doc_chunk (                             -- 정돌테크 문서 청크 (영찬 META_SPEC v0.3, ## 섹션 1개 = 청크 1개). 1차·코딩 3번·화상 공용
    doc             text NOT NULL,                           -- 문서 ID (예: PRJ-MED-3)
    sec             text NOT NULL,                           -- 섹션 ID (예: s1). 청크 ID = doc#sec
    doc_title       text NOT NULL,
    sec_title       text NOT NULL,
    doc_type        text NOT NULL,                           -- project, incident, open_issue, research, test_result, talent, unit_code, criteria, notice
    tier            smallint NOT NULL CHECK (tier BETWEEN 0 AND 3),   -- 3 공개(본 질문) · 2 사내(꼬리 1) · 1 대외 연구(꼬리 2) · 0 사다리 밖
    disclosure      text NOT NULL CHECK (disclosure IN ('public','abstract','internal')),   -- internal은 어떤 프롬프트에도 넣지 않음
    topic           text,                                    -- MED·DRN·TKT·COMMON
    status          text,                                    -- done·ongoing·resolved·unresolved
    stages          text[] NOT NULL DEFAULT '{}',            -- 1차·2차
    dept            text[] NOT NULL DEFAULT '{}',            -- AI·BE·FE·EMB·DATA (직무 필터)
    level           text[] NOT NULL DEFAULT '{}',            -- 신입·주니어·시니어
    ct_band         text,                                    -- 상·중·하 (코딩 등급에서 온 난이도)
    related         text[] NOT NULL DEFAULT '{}',            -- 꼬리 1 근거 → 꼬리 2 연구 문서
    forbid          text[] NOT NULL DEFAULT '{}',            -- 질문에 나오면 막는 단어 (tier ≤ 2)
    body            text NOT NULL,
    embedding       vector(1024),                            -- bge-m3 ([회사 | 문서 | 난이도 | 부서 | 섹션] 머리말 + 본문). scripts/embed_docs.py가 채움
    PRIMARY KEY (doc, sec)
);

CREATE TABLE notice (                                        -- 공지사항 (F-ADM-52)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title           text NOT NULL,
    body            text NOT NULL,
    created_by      bigint NOT NULL REFERENCES admin_user(id),
    published_at    timestamptz
);

CREATE TABLE data_request (                                  -- 서류 반환·개인정보 삭제 요청 (ADM-044, F-CAN-09)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_id    bigint NOT NULL REFERENCES candidate(id),
    application_id  bigint REFERENCES application(id) ON DELETE SET NULL,
    kind            text NOT NULL CHECK (kind IN ('document_return','delete_personal')),
    status          text NOT NULL DEFAULT 'received' CHECK (status IN ('received','processing','done','rejected')),
    handled_by      bigint REFERENCES admin_user(id),
    handled_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_usage_log (                                  -- AI 비용 관리 (F-ADM-53)
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feature         text NOT NULL CHECK (feature IN ('document_eval','question_gen','judgement','final_eval','verify','coding_gen','chatbot','embedding')),
    provider        text NOT NULL,
    model           text NOT NULL,
    input_tokens    integer NOT NULL CHECK (input_tokens >= 0),
    output_tokens   integer NOT NULL CHECK (output_tokens >= 0),
    application_id  bigint REFERENCES application(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ============ 최종 합격 규칙 (테이블을 넘나드는 규칙은 트리거) ============
-- 최종 '합격·예비'는 2차 점수가 있고 과락이 아니며, 미결 부정행위 의심 건이 없어야 확정 가능
CREATE FUNCTION check_final_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s record; open_cases int;
BEGIN
  IF NEW.stage = 'final' AND NEW.result IN ('pass','reserve') THEN
    SELECT * INTO s FROM stage2_score WHERE application_id = NEW.application_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'final_without_stage2_score' USING ERRCODE = 'check_violation'; END IF;
    IF s.fail_cut THEN RAISE EXCEPTION 'final_pass_with_fail_cut' USING ERRCODE = 'check_violation'; END IF;
    IF to_regclass('suspicion_case') IS NOT NULL THEN
      EXECUTE 'SELECT count(*) FROM suspicion_case WHERE application_id = $1 AND status <> ''decided''' INTO open_cases USING NEW.application_id;
      IF open_cases > 0 THEN RAISE EXCEPTION 'final_pass_with_open_suspicion' USING ERRCODE = 'check_violation'; END IF;
    END IF;
  END IF;
  IF NEW.stage = 'final' AND NOT EXISTS (SELECT 1 FROM stage_result WHERE application_id = NEW.application_id AND stage = 'document' AND result = 'pass') THEN
    RAISE EXCEPTION 'final_without_document_pass' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_final_decision BEFORE INSERT OR UPDATE ON stage_result FOR EACH ROW EXECUTE FUNCTION check_final_decision();

-- 지원서 제출은 공고 접수 기간 안에, 게시된 공고에만
CREATE FUNCTION check_application_window() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p record;
BEGIN
  SELECT status, apply_start, apply_end INTO p FROM job_posting WHERE id = NEW.posting_id;
  IF p.status <> 'published' OR NEW.submitted_at NOT BETWEEN p.apply_start AND p.apply_end THEN
    RAISE EXCEPTION 'apply_outside_window' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_application_window BEFORE INSERT ON application FOR EACH ROW EXECUTE FUNCTION check_application_window();

-- 인덱스
CREATE INDEX ix_application_posting_status ON application (posting_id, status);
CREATE INDEX ix_application_candidate ON application (candidate_id);
CREATE INDEX ix_stage2_rank ON stage2_score (ai_rank);
CREATE INDEX ix_audit_target ON audit_log (target_type, target_id);
CREATE INDEX ix_notification_status ON notification (status) WHERE status = 'queued';
