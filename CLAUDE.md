# CLAUDE.md — 6.1 실시간 AI 화상면접 개발 지시서

이 저장소에서 작업하는 Claude Code가 먼저 읽는 파일이다. **목표: 웹에서 로그인 → 2차 응시 안내 → 사전 점검·본인 확인 → AI 화상면접 10문항 → 응시 완료 → 관리자 결과 확인·확정까지 실제로 돌아가게 만든다.**

설계 근거는 `docs/`에 있다. 규칙이 헷갈리면 코드보다 문서를 먼저 확인한다.
- `docs/화상면접_PRD_6.1.pdf` — 무엇을, 왜
- `docs/화상면접_TRD_6.1.pdf` — 규칙·요구사항(IV-xx)·테이블·스택 (**가장 중요**)
- `docs/화상면접_화면정의서_6.1.pdf` — 화면 7개의 구성·동작·상태

---

## 0. 작업 원칙 (반드시 지킨다)

1. **구현 전 사고**: 가정을 적고, 해석이 여러 개면 고르지 말고 물어본다. 불분명하면 멈추고 질문한다.
2. **단순성**: 문제를 푸는 최소 코드. 요청 안 한 기능·추상화·설정 옵션 금지. 일어날 수 없는 경우의 예외 처리 금지.
3. **정밀한 수정**: 필요한 곳만 바꾼다. 기존 코드·주석·포맷을 임의로 고치지 않는다. 내 수정으로 안 쓰이게 된 것만 지운다.
4. **목표 중심**: 단계마다 아래 "검증"을 통과시키고 다음 단계로 간다. 통과 못 하면 넘어가지 않는다.
5. **버전 고정**: `requirements/*.lock.txt`, `requirements/frontend.package*.json`의 버전을 바꾸지 않는다. 새 패키지가 꼭 필요하면 **설치 전에** `uv pip compile`(또는 `npm install --dry-run`)로 기존 버전이 바뀌는지 확인하고, 바뀌면 멈추고 보고한다. 모델 이름(`qwen3:4b`, `qwen3:1.7b`, `bge-m3`)도 바꾸지 않는다.
6. **DB 스키마**: `db/common_schema.sql`(공통, 다른 파트 소유)은 바꾸지 않는다. `db/interview_schema.sql`(6.1)도 바꿔야 하면 먼저 이유를 보고하고 승인을 받는다. 스키마의 CHECK 제약이 규칙의 정답이다 — 코드를 제약에 맞춘다.
7. **비밀값**: API 키는 `.env`에만. 저장소에 커밋하지 않는다.
8. **개인정보**: LLM에 보내는 텍스트에서 이름·학교·연락처·이메일·주소·성별·생년월일·나이를 가린다(`resume_snapshot.인적사항`과 본문 모두). 영상·얼굴 사진은 저장하지 않고, 답변 음성은 STT 후 지운다.

---

## 1. 지금 있는 것 (건드리지 말고 가져다 쓴다)

| 경로 | 내용 |
|---|---|
| `db/common_schema.sql` | 공통 DB (지원자·공고·지원서·1차·코딩·2차 종합·회사 문서 등) |
| `db/interview_schema.sql` | 면접 테이블 13개 + 규칙 제약 |
| `db/test_*.py` | DB 규칙 시험 (pgserver로 임시 DB) |
| `app_6_1/flow.py` | `next_action()` 다음 질문 결정, `topic_score()` 주제 점수 |
| `app_6_1/llm.py` | 모델 연결·전환(`from_env`, `check_config`, `chat_model`, `structured`, `judge_with_fallback`, `route`) |
| `stubs_6_1/contracts.py` | 모듈 간 주고받는 형식 (Handoff, WeaknessSummary, CompanyDoc, QuestionContext, Question, Judgement, Turn, Evaluation) |
| `stubs_6_1/fake_modules.py` | 가짜 질문 생성·판정·최종 평가 (같은 형식) |
| `seed/test_data.sql` | 관리자 3명, 지원자 50명(이력서·1차 결과·인계 데이터·코딩 결과 포함), 공고 1개, 면접 설정 |
| `seed/corpus_v3*`, `scripts/load_corpus.py`, `scripts/embed_docs.py` | 회사 문서 356청크 적재·임베딩 |
| `requirements/` | 컨테이너별 고정 버전 (api·stt·face·tts·frontend) |
| `compose.ollama.yml` | Ollama (GPU 서버) |

**시험 계정**: 비밀번호 모두 `Test1234!`
- 관리자: `admin`(최고 관리자), `hr01`(채용 담당), `dev01`(부서원). 2단계 인증 시험 비밀값 `JBSWY3DPEHPK3PXP` (시험 전용)
- 지원자: `cand01@test.local` ~ `cand50@test.local` — 모두 1차 통과·코딩 완료 상태(지원 상태 `stage2`)라 바로 면접으로 갈 수 있다.

**시험 데이터 중 가짜 값**: `document_evaluation`, `coding_result`의 모델 값이 `stub`인 행은 다른 파트 결과가 오기 전까지 쓰는 가짜다.

---

## 2. 면접 규칙 요약 (상세는 TRD 4~6장)

- 10문항, 번호 = 물어본 순서. 1·2번 비기술(1번 이력서 경험 확인, 2번 인계 데이터 `deficit_value`), 3~10번 기술.
- 3번은 `coding_result.weakness_summary` 기반. 난이도 대역 `ct_band`: 코딩 `q3_tier` 골드2·3=상, 골드4=중, 골드5·실버1=하.
- 기술 답변 0~100점(루브릭: 정확성 30·회사 적용 30·깊이 25·구체성 15), 비기술은 의견만.
- `next_action`: ≥70 & 깊이<2 → 꼬리질문 / <40 & 주제 재질문 안 함 → 재질문 / 응답 상태 ok 아님 → 다음 주제 / 그 밖 → 다음 주제 / 10문항 → 종료.
- 꼬리질문 깊이 1은 tier 2, 깊이 2는 tier 1 문서(related 먼저). 재질문은 같은 근거.
- 모델 경로 `route()`: 근거에 tier 1·2가 있으면 사내 모델 (국외 전송 동의는 응시 필수, 1109). 모든 LLM 호출은 `api/llm_gate.call()`.
- 구조: LangGraph 메인 그래프(`api/graph/main.py`, 지원 건 1개 = thread) + 면접 S2·S3(`api/graph/interview.py`). 오류가 나도 면접은 멈추지 않는다 (1109).
- 시간: 생각 10초(1·2번)/20초(3번~), 답변 최대 180초, 침묵 5초면 자동 제출, '답변 끝' 버튼. 판정 30초 넘으면 대체 모델, 60초면 점수 보류 + 다음 주제 (면접은 멈추지 않음, 1109).
- 답변 제출 → 다음 질문 표시 ≤60초.
- 감독: 탭 이탈 1번 경고, 2번째이거나 10초 이상이면 포기. 얼굴 없음 5초·여러 명·시선 이탈 5초 → 경고 + 의심 건(자동 불합격 없음).
- 최종 평가: 내용 60(임시: 주제 점수 평균 × 0.6)·언어 30·비언어 10, 5검사, 실패 시 1번 재평가. 담당자는 검증 통과 버전만 확정.

---

## 3. 만들 것 — 구조

```
api/            FastAPI 앱 (Python 3.12, requirements/api.lock.txt)
  main.py       라우터 등록, 시작 때 llm.check_config()
  db.py         psycopg 연결 (DATABASE_URL)
  auth.py       ※ 임시 로그인 (공통 기반이 오면 교체) — 지원자 이메일·비밀번호, 관리자 아이디·비밀번호+TOTP, JWT 쿠키
  interview/    지원자 면접 API, SSE, 진행 상태
  admin/        면접 설정·결과·확정 API
  modules.py    MODULE_MODE=stub → stubs_6_1.fake_modules / real → 실제 모듈. 한 곳에서만 고른다
worker/         Celery 작업 (stt, judge, question, evaluate, face) — 같은 MODULE_MODE를 따름
web/            Next.js 16.4.3 (requirements/frontend.package.json 그대로)
compose.yml     postgres(pgvector/pgvector:0.8.7-pg17), redis:8.2, api, worker, web (+ compose.ollama.yml 합쳐 쓰기)
Makefile        up / seed / test / e2e
```

`MODULE_MODE=stub`이면 GPU·모델 없이 노트북에서 전체 흐름이 돌아야 한다. 이때 STT는 `STT_MODE=stub`으로 업로드 음성 대신 질문의 `key_points`를 일부 포함한 고정 답변을 돌려주어 점수가 다양하게 나오게 한다(지원자 수준 `resume_snapshot.시험용 수준`에 따라 상=대부분 포함, 하=거의 없음).

---

## 4. 단계별 작업과 검증

각 단계 끝에 테스트를 추가하고 `make test`가 통과해야 다음으로 간다.

### 단계 1 — 실행 환경
- `compose.yml`, `Makefile`, `.env.example` 보완(DATABASE_URL, REDIS_URL, MODULE_MODE, STT_MODE, JWT_SECRET).
- `make seed` = `common_schema.sql` → `interview_schema.sql` → `seed/test_data.sql` → `load_corpus.py` → (Ollama 있으면) `embed_docs.py`.
- **검증**: `make up && make seed` 후 지원자 50명, 지원서 50건(stage2), 회사 문서 356청크. 기존 `db/`, `stubs_6_1/`, `app_6_1/` 시험 전부 통과.

### 단계 2 — 임시 로그인
- 지원자 회원가입(이메일·비밀번호·이름·연락처)·로그인, 관리자 로그인(+TOTP), 로그아웃. bcrypt, JWT 쿠키(HttpOnly).
- 지원자는 자기 지원서만, 관리자는 역할대로만 접근 (다른 사람 응시 접근 시 403).
- **검증**: pytest — 가입·로그인·로그아웃, 다른 지원자 응시 403, TOTP 틀리면 거부.

### 단계 3 — 면접 API (stub 모드)
지원자 API (prefix `/api/interview`):
| 메서드·경로 | 하는 일 | 화면 |
|---|---|---|
| GET `/applications/{app_id}/guide` | 응시 기간·진행 순서·규칙, 응시 가능 여부 | CAN-008 |
| POST `/applications/{app_id}/precheck` | 장치 점검 결과·동의(필수 3: 음성·AI 활용·국외 전송 + 얼굴 대조 별도 선택, 거부하면 사람 확인) 기록 — 활동다이어그램 1109 | CAN-009 |
| POST `/applications/{app_id}/identity` | 프레임 1장 → 대조 거리·구간 기록(사진 저장 안 함). 응답에 결과 노출 안 함 | CAN-009 |
| POST `/applications/{app_id}/start` | `interview_session` 생성: handoff·coding_weakness·ct_band·overseas_consent·모델 복사, 설정 잠금, 1~3번 질문 준비 | CAN-011 |
| GET `/sessions/{sid}/state` | 현재 번호·질문·종류·단계(생각/녹음/준비 중/종료)·남은 시간 — 재접속 복구용 | CAN-012 |
| GET `/sessions/{sid}/events` | SSE: 다음 질문 준비 완료, 종료, 오류 | CAN-012 |
| GET `/sessions/{sid}/questions/{qid}/audio` | 질문 음성 (stub 모드는 무음 wav 또는 404 → 화면은 글로 진행) | CAN-012 |
| POST `/sessions/{sid}/questions/{qid}/answer` | 음성 업로드 + answer_sec·silence_ratio·finished_in_time → STT → 판정 → `next_action` → 다음 질문 생성 (worker) | CAN-012 |
| POST `/sessions/{sid}/proctor` | 감독 이벤트 (tab_leave·face_missing·multi_face·gaze_away, 지속 초) → 경고/포기 판정 | CAN-012 |
| POST `/sessions/{sid}/inquiry` | 문의 → 원인 분류, 시스템 원인이면 추가 시간 | CAN-012 |

관리자 API (prefix `/api/admin`):
| 메서드·경로 | 하는 일 | 화면 |
|---|---|---|
| GET·PUT `/postings/{pid}/interview-setting` | 설정 조회·수정 (잠긴 뒤 수정 거부) | ADM-025 |
| GET `/interviews?posting_id=` | 응시 목록·상태·총점·의심 건 | ADM-033 목록 |
| GET `/interviews/{sid}` | 물어본 순서대로 질문·종류·근거 청크·STT·점수·루브릭·의견, 주제 점수, 총점, 5검사, 본인 확인·감독, 코딩 약점 | ADM-033 |
| POST `/interviews/{sid}/confirm` | 검증 통과 버전만 확정 → `stage2_score` 반영 | ADM-033 |
| POST `/interviews/{sid}/reattempt` | 재응시 부여 (최대 3차) | ADM-033 |
| POST `/interviews/{sid}/notes`, `/suspicions/{id}/decision` | 메모, 의심 건 처리 | ADM-033 |

- 진행 결정은 반드시 `app_6_1/flow.next_action()`만 쓴다. 질문·판정·평가는 `api/modules.py`를 거쳐 부른다.
- 10번째 판정 뒤 최종 평가(5검사, 실패 시 재평가 1번) 작업을 큐에 넣는다.
- **검증**: pytest(httpx) — cand01로 start부터 10문항 끝까지 stub 답변을 넣어 DB 규칙 위반 없이 종료, 평가 v1 검증 통과, hr01이 확정하면 `stage2_score` 생성. 재접속(state) 시 같은 문항. 탭 이탈 2번 → 포기. 잠긴 설정 PUT 거부. 답변 제출 → 다음 질문 준비까지 stub 모드 5초 안.

### 단계 4 — 화면 (Next.js)
화면정의서 그대로: `/login`, `/signup`, `/me/applications`(CAN-007 간단 목록), `/interview/[appId]/guide`(CAN-008), `/precheck`(CAN-009), `/ready`(CAN-011), `/live`(CAN-012), `/done`(CAN-013), `/admin/login`, `/admin/postings/[pid]/interview-setting`(ADM-025), `/admin/interviews`, `/admin/interviews/[sid]`(ADM-033).
- CAN-012: 질문 음성 재생 + 글, 번호·종류·남은 시간, 생각 시간 카운트다운 → MediaRecorder(음성만) → 5초 침묵(Web Audio 음량)·'답변 끝'·180초로 제출, 재녹음 없음. SSE로 다음 질문. 새로고침 시 `/state`로 복구.
- 감독: `visibilitychange`·`blur`로 탭 이탈, `@mediapipe/tasks-vision` FaceLandmarker로 얼굴 없음·여러 명·시선 이탈 → `/proctor`. 영상은 브라우저 밖으로 보내지 않는다(본인 확인 프레임 1장만 예외).
- 지원자 화면에 점수·판정을 절대 보여 주지 않는다.
- **검증**: `next build`, `tsc` 통과. vitest — 침묵 감지·타이머·탭 이탈 카운트 단위 시험.

### 단계 5 — 웹 전체 흐름 (E2E, stub 모드)
- Playwright로 (새로 추가하는 패키지이므로 0장 5번대로 버전 영향 확인 후 고정): 신규 가입·로그인 확인 → cand01 로그인 → 안내 → 점검(가짜 카메라·마이크: `--use-fake-device-for-media-stream`) → 시작 → 10문항 → 완료 → hr01 로그인 → ADM-033 확인 → 확정 → 2차 종합 점수 생성.
- 관리자: ADM-025 설정 수정 → 응시 시작 후 잠김 확인.
- **검증**: `make e2e` 통과, 단계별 스크린샷 저장.

### 단계 6 — 실제 모듈 (GPU 서버, MODULE_MODE=real)
- 질문 생성·판정·최종 평가: `llm.chat_model` + `structured`로 contracts 형식 그대로 출력. 판정은 `judge_with_fallback`, 모델은 `route()`로.
- 회사 문서 검색 `retrieve()`: 조건 필터 → BM25 ∥ bge-m3 → RRF(k=60) → 재정렬(≥0.6). **BM25 형태소 분석기(kiwipiepy)와 재정렬 모델 패키지는 코딩 파트와 같은 것을 써야 하므로, 설치 전에 멈추고 버전을 물어본다.** 그 전까지는 벡터 검색만으로 동작하게 두고 표시한다.
- 질문 방어 검사: 근거 일치(재정렬 ≥0.5) + 근거 청크 `forbid` 단어 포함 시 재생성.
- STT faster-whisper(stt 컨테이너), 얼굴 대조 DeepFace ArcFace(face 컨테이너), 질문 음성 Supertonic(tts 컨테이너, CPU).
- **검증**: `scripts/check_ollama.py` 통과, 답변 1개 판정 ≤30초, 동시 10명 답변 → 다음 질문 ≤60초 측정 기록.

---

## 5. 정해지지 않은 것 (임의로 정하지 말고 임시값임을 코드 주석에 남긴다)

- 인계 데이터 위치: 지금은 `document_evaluation.handoff` (공통 DB에 임시 추가, 팀 확정 전)
- 약점 요약 필드: algorithms · failed_groups · weakness_tags
- 내용 60점 환산(임시: 주제 점수 평균 × 0.6), 비언어 10점 산식(임시: 시간 안에 마침 50% + 침묵 비율 50%)
- 생각 시간 10·20초, 침묵 5초
- 모델 이름 통일(qwen3:4b / qwen3.5:4b) — 바꾸지 말 것
- 로그인·회원가입은 공통 기반 파트가 정식 구현 — 지금 것은 임시(`api/auth.py` 한 파일에 모은다)
