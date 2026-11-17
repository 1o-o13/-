6.1이 만든 테이블 21개의 모든 칼럼입니다. 설명과 허용 값은 `db/interview_schema.sql`의 주석과 CHECK 제약에서 가져왔습니다. '키' 칸의 FK는 어느 테이블·칼럼으로 들어가는지 함께 적었습니다.

## interview_setting

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `posting_id` | bigint | 필수 | PK · FK → `job_posting.id` |  |
| `company_requirements` | text |  |  | 회사 요구사항 |
| `total_questions` | smallint | 필수 |  | 기본값 10 |
| `followup_max_depth` | smallint | 필수 |  | 기본값 2 |
| `think_sec_non_tech` | smallint | 필수 |  | 1·2번 생각 시간 (확인 필요) · 기본값 10 |
| `think_sec_tech` | smallint | 필수 |  | 기술 질문 생각 시간 (확인 필요) · 기본값 20 |
| `answer_max_sec` | smallint | 필수 |  | 기본값 180 |
| `silence_skip_sec` | smallint | 필수 |  | 이만큼 침묵하면 다음 문제 (5~6초 확인 필요) · 기본값 5 |
| `follow_score` | smallint | 필수 |  | 이 점수 이상이면 꼬리질문 (Q-21 보정) · 기본값 70 |
| `retry_score` | smallint | 필수 |  | 이 점수 미만이면 재질문 1회 (Q-21 보정) · 기본값 40 |
| `weight_content` | smallint | 필수 |  | 기본값 60 |
| `weight_language` | smallint | 필수 |  | 기본값 30 |
| `weight_nonverbal` | smallint | 필수 |  | 기본값 10 |
| `llm_provider` | text | 필수 |  | 무료판 기본 ollama. 한 공고 안에서는 고정 · 값: ollama,anthropic,openai · 기본값 'ollama' |
| `llm_eval_model` | text | 필수 |  | 유료판 예: claude-sonnet-5-5 · 기본값 'qwen3:4b' |
| `llm_fast_model` | text | 필수 |  | 30초 대체. 유료판 예: claude-haiku-5-5 · 기본값 'qwen3:1.7b' |
| `llm_local_model` | text | 필수 |  | 온프레미스. tier ≤ 2 문서·국외 전송 미동의는 항상 여기로 (RAG-17) · 기본값 'qwen3:4b' |
| `locked_at` | timestamptz |  |  | 첫 응시 시작 시각. 이후 설정 변경 불가 |
| `updated_at` | timestamptz | 필수 |  | 기본값 now() |

## interview_session

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `application_id` | bigint | 필수 | FK → `application.id` |  |
| `attempt_no` | smallint | 필수 |  | 재응시는 새 질문으로 새 행 · 기본값 1 |
| `exam_code` | text | 필수 |  | 응시 고유 번호 (CAN-008) |
| `coding_session_id` | bigint |  | FK → `coding_session.id` | 비개발 직군은 NULL |
| `coding_weakness` | jsonb |  |  | 시작 때 복사한 코딩 약점 요약(CT-33). 3번 질문 입력, 비개발 직군은 NULL |
| `ct_band` | text |  |  | 코딩 등급 → 난이도 (골드2·3 상, 골드4 중, 골드5·실버1 하) · 값: 상,중,하 |
| `handoff` | jsonb |  |  | 1차 인계(handoff.json): 직무·레벨·결핍 가치. 2번 질문 입력 |
| `project_topic` | text |  |  | 이력서와 가장 비슷한 회사 프로젝트(topic). 질문 준비 때 고정, 3~10번 기술 질문 근거 |
| `overseas_consent` | boolean | 필수 |  | 국외 전송 동의. 없으면 LLM 전부 온프레미스 · 기본값 false |
| `status` | text | 필수 |  | 값:  ready,prechecked,in_progress,paused,completed,abandoned,system_error,retake_granted · 기본값 'ready' |
| `precheck` | jsonb |  |  | {chrome, camera, mic, upload_mbps, single_face} |
| `consent_at` | timestamptz |  |  | 유의사항·AI 활용 동의 |
| `identity_status` | text |  |  | 시작 본인 확인 결과(지원자 비공개) · 값: match,unclear,mismatch |
| `llm_provider` | text | 필수 |  | 설정에서 복사(응시 당시 값 보존) |
| `llm_eval_model` | text | 필수 |  |  |
| `llm_fast_model` | text | 필수 |  |  |
| `llm_local_model` | text | 필수 |  |  |
| `extra_time_sec` | int | 필수 |  | 시스템 장애로 받은 추가 시간 · 기본값 0 |
| `started_at` | timestamptz |  |  |  |
| `ended_at` | timestamptz |  |  |  |
| `end_reason` | text |  |  | 값: finished,tab_leave,system_error,candidate_quit,admin_stop |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## interview_question

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `session_id` | bigint | 필수 | FK → `interview_session.id` |  |
| `kind` | text | 필수 |  | 값: non_tech,tech |
| `question_type` | text | 필수 |  | 본·꼬리·되묻기 · 값: main,followup,reask · 기본값 'main' |
| `depth` | smallint | 필수 |  | 꼬리질문 깊이 (재질문은 원래 질문 깊이) · 기본값 0 |
| `tech_stack` | text |  |  | 기술 주제 (40~70점이면 다른 주제로) |
| `parent_question_id` | bigint |  | FK → `interview_question.id` | 꼬리질문·되묻기면 바로 앞 질문 id |
| `ask_order` | smallint | 필수 |  | 질문 번호 = 물어본 순서. 물어볼 때 저장 |
| `question_text` | text | 필수 |  |  |
| `basis` | text |  |  | 출제 근거 (ADM-033) |
| `source_doc_ids` | jsonb |  |  | 근거 청크 ID 목록 (doc#sec). 기술 질문만 |
| `min_tier` | smallint |  |  | 프롬프트에 들어간 근거 중 가장 낮은 tier → LLM 경로 |
| `rag_check` | jsonb |  |  | 재정렬 점수 (0.6 이상만 근거), 대체 사용 여부 |
| `defense` | jsonb |  |  | 질문 방어 (CE 0.5, 금지어 수정·가림) |
| `key_points` | jsonb |  |  | 판정 체크리스트(핵심 요소) |
| `generated_by_model` | text | 필수 |  |  |
| `generated_at` | timestamptz | 필수 |  | 기본값 now() |
| `asked_at` | timestamptz |  |  |  |

## interview_answer

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `question_id` | bigint | 필수 | FK → `interview_question.id` | 재녹화 불가: 질문당 1개 |
| `stt_text` | text |  |  | 무응답이면 NULL |
| `stt_model` | text | 필수 |  | 기본값 'faster-whisper large-v3-turbo' |
| `answer_sec` | numeric |  |  |  |
| `finished_in_time` | boolean | 필수 |  | 비언어 점수: 시간 안에 마침 |
| `silence_ratio` | numeric |  |  | 3초 이상 침묵 비율 |
| `no_response` | boolean | 필수 |  | 기본값 false |
| `audio_object_key` | text |  |  | 임시 음성 위치. STT 후 NULL로 비움 |
| `audio_deleted_at` | timestamptz |  |  | 음성 삭제 증빙 |
| `upload_retry_count` | smallint | 필수 |  | 기본값 0 |
| `submitted_at` | timestamptz | 필수 |  | 기본값 now() |
| `stt_done_at` | timestamptz |  |  |  |
| `stt_original` | text |  |  | 지원자가 보기 전 STT 원본 (무응답·STT 실패면 NULL) |
| `stt_confirmed_at` | timestamptz |  |  | 지원자가 '완료'를 누른(또는 60초가 지난) 시각. 이때 판정 시작 |
| `stt_edit_ratio` | numeric |  |  | 원본 대비 바뀐 비율 |
| `answer_mode` | text | 필수 |  | 값: voice,text · 기본값 'voice' |

## answer_judgement

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `answer_id` | bigint | 필수 | FK → `interview_answer.id` |  |
| `status` | text | 필수 |  | 값: ok,silent,no_stt,timeout,parse_error · 기본값 'ok' |
| `score` | numeric |  |  | 기술: 루브릭 합(정확성 30·회사 적용 30·깊이 25·구체성 15). 비기술·평가 실패는 NULL |
| `rubric` | jsonb |  |  | 항목별 점수·강점 인용(good_quote)·약점 |
| `opinion` | jsonb |  |  | 비기술: 의견·인용·이력서 일치 여부·확인할 점 |
| `lang_structure` | smallint |  |  | 언어: 구조 |
| `lang_terms` | smallint |  |  | 용어 정확성 |
| `lang_intent` | smallint |  |  | 질문 의도 부합 |
| `key_points_met` | jsonb |  |  |  |
| `quotes` | jsonb |  |  | 근거 인용 (STT 원문 안에 있어야 함) |
| `rationale` | text | 필수 |  |  |
| `model_tier` | text | 필수 |  | fast = 30초 대체로 판정 · 값: eval,fast |
| `provider` | text | 필수 |  |  |
| `model` | text | 필수 |  |  |
| `latency_ms` | int |  |  |  |
| `is_current` | boolean | 필수 |  | 기본값 true |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## answer_signal

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `answer_id` | bigint | 필수 | FK → `interview_answer.id` |  |
| `source` | text | 필수 |  | 값: face,voice |
| `t_start_ms` | int | 필수 |  |  |
| `t_end_ms` | int | 필수 |  |  |
| `label` | text | 필수 |  | 예: 자신감 있는 목소리·작은 목소리·미소·긴장·시선 아래 |
| `value` | jsonb |  |  | 수치 (음량·높낮이·말 빠르기, 표정 계수 평균) |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## interview_evaluation

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `session_id` | bigint | 필수 | FK → `interview_session.id` |  |
| `version_no` | smallint | 필수 |  | 1 = 첫 평가, 2 = 1회 재평가 |
| `topic_scores` | jsonb | 필수 |  | 주제 점수 T = S_d + 40 × 평균/100 (S0 0·S1 30·S2 60, 메인 3.9 제안). 배점은 Q-15 미결 |
| `content_score` | numeric | 필수 |  |  |
| `language_score` | numeric | 필수 |  |  |
| `nonverbal_score` | numeric | 필수 |  |  |
| `total_score` | numeric |  |  |  |
| `rationale` | text | 필수 |  |  |
| `project_topic` | text |  |  | 판정 기준 프로젝트 |
| `fit_opinion` | text |  |  | 적합성: 지금 이 프로젝트에 투입 가능한가 (의견, 점수 아님) |
| `growth_opinion` | text |  |  | 확장성: 다른 프로젝트로 옮겨도 해낼 수 있는가 (의견, 점수 아님) |
| `provider` | text | 필수 |  |  |
| `model` | text | 필수 |  |  |
| `status` | text | 필수 |  | 값: checking,passed,failed · 기본값 'checking' |
| `confirmed_by` | bigint |  | FK → `admin_user.id` | 담당자 확정 (점수 수정은 불가) |
| `confirmed_at` | timestamptz |  |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## evaluation_check

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `evaluation_id` | bigint | 필수 | FK → `interview_evaluation.id` |  |
| `check_no` | smallint | 필수 |  |  |
| `passed` | boolean | 필수 |  |  |
| `detail` | text |  |  |  |
| `checker` | text | 필수 |  | 'code' 또는 모델명 |
| `checked_at` | timestamptz | 필수 |  | 기본값 now() |

## ai_error_alert

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `stage` | text | 필수 |  | 값: document,coding,interview |
| `application_id` | bigint | 필수 | FK → `application.id` |  |
| `interview_evaluation_id` | bigint |  | FK → `interview_evaluation.id` |  |
| `problem_part` | text | 필수 |  | 어느 부분이 문제인지 |
| `status` | text | 필수 |  | 값: open,acknowledged,done · 기본값 'open' |
| `handled_by` | bigint |  | FK → `admin_user.id` |  |
| `handled_at` | timestamptz |  |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## identity_check

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `session_id` | bigint | 필수 | FK → `interview_session.id` |  |
| `phase` | text | 필수 |  | recheck = 60초마다 · 값: start,retake,recheck |
| `retake_no` | smallint | 필수 |  | 기본값 0 |
| `distance` | numeric |  |  | ArcFace 코사인 거리, 얼굴 못 찾으면 NULL |
| `band` | text | 필수 |  | 값: match,unclear,mismatch,no_face |
| `model` | text | 필수 |  | 기본값 'ArcFace' |
| `checked_at` | timestamptz | 필수 |  | 기본값 now() |
| `liveness` | text |  |  | 11/12 시작 전 1회: 고개 돌리기·눈 깜빡이기 (사진·영상 대리 응시 방지). recheck는 NULL · 값: pass,fail |

## proctor_event

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `session_id` | bigint | 필수 | FK → `interview_session.id` |  |
| `event_type` | text | 필수 |  | gaze_away: 시선 화면 밖(부정행위 감지용, 점수에는 안 씀) · 값:  tab_leave,window_blur,face_missing,multi_face,gaze_away,identity_mismatch, network_drop,reconnect,upload_fail |
| `occurred_at` | timestamptz | 필수 |  |  |
| `duration_ms` | int |  |  |  |
| `occurrence_no` | smallint |  |  | 이 종류 몇 번째 (탭 이탈 누적 2회 판단) |
| `action` | text | 필수 |  | 값: logged,warned,abandoned,suspected |
| `question_id` | bigint |  | FK → `interview_question.id` |  |
| `meta` | jsonb |  |  |  |

## suspicion_case

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `stage` | text | 필수 |  | 값: document,coding,interview |
| `application_id` | bigint | 필수 | FK → `application.id` |  |
| `interview_session_id` | bigint |  | FK → `interview_session.id` |  |
| `reason` | text | 필수 |  | 값:  tab_leave,face_missing,multi_face,gaze_away,identity_unclear,identity_mismatch,paste,plagiarism |
| `evidence` | jsonb |  |  | 관련 이벤트·대조 id 목록 (영상 없음) |
| `status` | text | 필수 |  | 값: open,explanation_requested,explained,decided · 기본값 'open' |
| `explanation_due_at` | timestamptz |  |  | 소명 기한 |
| `explanation_text` | text |  |  |  |
| `decision` | text |  |  | 값: normal,warning,disqualified |
| `decision_reason` | text |  |  |  |
| `decided_by` | bigint |  | FK → `admin_user.id` |  |
| `decided_at` | timestamptz |  |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## interview_incident

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `session_id` | bigint | 필수 | FK → `interview_session.id` |  |
| `error_code` | text | 필수 |  | 예: LLM_TIMEOUT_60S, UPLOAD_FAIL_3X |
| `cause` | text | 필수 |  | 값: system,candidate,unknown |
| `chat_started_at` | timestamptz | 필수 |  |  |
| `chat_ended_at` | timestamptz |  |  |  |
| `extra_time_sec` | int | 필수 |  | 기본값 0 |
| `outcome` | text |  |  | 값: resumed,stopped_reported,retake_granted |
| `report_sent_at` | timestamptz |  |  | 담당자 리포트 |

## interview_note

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `session_id` | bigint | 필수 | FK → `interview_session.id` |  |
| `author_id` | bigint | 필수 | FK → `admin_user.id` |  |
| `body` | text | 필수 |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## answer_accommodation

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `application_id` | bigint | 필수 | FK → `application.id` | 지원 건당 1개 (다시 신청하면 내용을 바꿈) |
| `kind` | text | 필수 |  | 값: text_answer · 기본값 'text_answer' |
| `reason` | text | 필수 |  |  |
| `status` | text | 필수 |  | 값: requested,approved,rejected · 기본값 'requested' |
| `decided_by` | bigint |  | FK → `admin_user.id` |  |
| `decided_at` | timestamptz |  |  |  |
| `decision_note` | text |  |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## llm_call

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `session_id` | bigint |  | FK → `interview_session.id` | 면접 밖 호출(1차 서류 등)은 NULL |
| `application_id` | bigint |  | FK → `application.id` |  |
| `purpose` | text | 필수 |  | q1_verify·tech_main·judge·doc_screen … |
| `prompt_version` | text | 필수 |  | 프롬프트 파일 해시 8자리 |
| `provider` | text | 필수 |  |  |
| `model` | text | 필수 |  |  |
| `min_tier` | smallint |  |  |  |
| `input_tokens` | int | 필수 |  | 기본값 0 |
| `output_tokens` | int | 필수 |  | 기본값 0 |
| `latency_ms` | int | 필수 |  |  |
| `ok` | boolean | 필수 |  |  |
| `route_note` | text |  |  | LEAK_BLOCKED·AUTH_ERROR·RETRY n |
| `error` | text |  |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## question_bank

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `job_role` | text | 필수 |  | job_posting.job_role (백엔드·프론트엔드·AI·데이터·임베디드) |
| `topic` | text | 필수 |  | 회사 프로젝트 주제 |
| `chunk_id` | text | 필수 |  | 근거 청크 doc#sec (tier 3) |
| `question_text` | text | 필수 |  |  |
| `key_points` | jsonb | 필수 |  |  |
| `model` | text | 필수 |  |  |
| `verified` | boolean | 필수 |  | 코드 검증 통과만 출제 후보 · 기본값 false |
| `verify_note` | text |  |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## prepared_question

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `application_id` | bigint | 필수 | FK → `application.id` |  |
| `slot` | smallint | 필수 |  | 1·2 비기술, 3 코딩 약점 본 질문, 4~10 기술 본 질문 후보(순서대로 출제) |
| `kind` | text | 필수 |  | 값: non_tech,tech |
| `tech_stack` | text |  |  |  |
| `question_text` | text | 필수 |  |  |
| `basis` | text |  |  |  |
| `source_doc_ids` | jsonb |  |  |  |
| `min_tier` | smallint |  |  |  |
| `key_points` | jsonb | 필수 |  |  |
| `model` | text | 필수 |  |  |
| `bank_id` | bigint |  | FK → `question_bank.id` |  |
| `status` | text | 필수 |  | 값: ready,failed |
| `verify` | jsonb | 필수 |  | 검사 항목별 결과 |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## application_stage

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `application_id` | bigint | 필수 | PK · FK → `application.id` |  |
| `stage` | text | 필수 |  | 값: submitted,screen_failed,screen_passed,screen_rejected,coding_waiting, scheduled,coding,interview,final_pass,final_fail,withdrawn |
| `updated_at` | timestamptz | 필수 |  | 기본값 now() |

## application_stage_log

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `id` | bigint | 필수 | PK |  |
| `application_id` | bigint | 필수 | FK → `application.id` |  |
| `from_stage` | text |  |  |  |
| `to_stage` | text | 필수 |  |  |
| `actor_type` | text | 필수 |  | 값: admin,candidate,system |
| `actor_id` | bigint |  |  |  |
| `reason` | text |  |  |  |
| `created_at` | timestamptz | 필수 |  | 기본값 now() |

## stage_transition

| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |
|---|---|---|---|---|
| `from_stage` | text | 필수 | PK |  |
| `to_stage` | text | 필수 | PK |  |
