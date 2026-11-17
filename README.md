# AI 실시간 화상면접 시스템 (AI 채용 솔루션 6.1 파트)

가상 회사 **새벽소프트**의 채용 2차 전형을 맡는 AI 화상면접 시스템입니다. AI가 지원자의 이력서·코딩 테스트 약점·회사 프로젝트 문서로 질문을 만들고, 답변을 같은 기준으로 채점해 근거와 함께 보여 줍니다. **합격·불합격은 언제나 채용 담당자가 정합니다.**

- 기간: 2026-11-04 ~ 2026-11-17 (팀 4명 중 6.1 AI 화상면접 파트)
- 개발 방식: AI 코딩 도구(Claude Code)를 활용한 바이브 코딩, 요구사항 정의·검증·판단은 직접

## 주요 기능
- **AI 화상면접 10문항:** 질문 음성(TTS) → 생각 시간 → 답변 녹음 → 음성 인식(STT) → 인식 글 확인 → 판정 → 다음 질문
- **점수에 따른 질문 분기:** 70점 이상이면 꼬리질문(최대 깊이 2), 40점 미만이면 재질문, 그 밖은 다음 주제 (`app_6_1/flow.py`)
- **회사 문서 근거 질문 (RAG):** BM25 + bge-m3 벡터 → RRF, 질문마다 근거 문서와 등급 기록
- **LLM 호출 관문:** 개인정보 가림, 내부 문서는 사내 모델만, 외부 전송 전 누출 검사, 호출 기록 (`api/llm_gate.py`)
- **본인 확인·감독:** 증명사진 얼굴 대조(InsightFace), 라이브니스, 탭 이탈·얼굴·시선 감독 → 의심 건 (자동 불합격 없음)
- **최종 평가와 확정:** 주제 점수 → 내용 60·언어 30·비언어 10, 자동 5검사, 담당자가 검증 통과본만 확정 → 2차 종합
- **관리자 화면:** 1차 서류 결정, 면접 리포트(질문·근거·답변·점수·루브릭), 최종 합격 결정·알림

## 기술 스택
| 구분 | 기술 |
|---|---|
| 백엔드 | Python 3.12, FastAPI, Celery, Redis, LangGraph |
| 프론트엔드 | Next.js 16, React 19, TypeScript, Tailwind CSS, MediaPipe |
| DB | PostgreSQL 17 + pgvector |
| AI | Claude Sonnet·Haiku(외부), Ollama qwen3:4b·1.7b(사내), bge-m3, faster-whisper, Supertonic, InsightFace, mDeBERTa(NLI) |
| 인프라·시험 | Docker Compose(컨테이너 11개), pytest, vitest, Playwright |

## 결과
| 항목 | 결과 |
|---|---|
| 자동 시험 | pytest 152 · vitest 35 · E2E 9 모두 통과 |
| 부하 | 동시 100명 면접 오류 0, 답변 제출 → 다음 질문 p95 0.58초 |
| STT 표시 지연 | 3분 답변도 약 19초 |
| 모델 비교 | STT 글자 오류 7.4% → 5.8%(용어 힌트), 얼굴 대조 본인 통과 80% → 100%(InsightFace) |
| 사내 모델 판정 | 형식 성공 63% → 100%, 1회 10.2초 → 7.8초 |
| 개인정보 | AI 입력 이력서 80명 검사 남은 개인정보 0, 음성은 STT 직후 삭제, 영상 미저장 |

## 문서
`docs/최종/`에 PDF·Word로 있습니다.
- PRD · TRD · 화면정의서 · 테스트 결과서 · 워크플로우 · DB 설계서

## 폴더 구조
```
api/        FastAPI 서버 (면접·관리자 API, LangGraph 그래프, LLM 관문, 검색)
worker/     Celery 작업 (STT → 판정 → 다음 질문 → 평가)
web/        Next.js 화면 (지원자·관리자 21개)
stt/ tts/ face/ nli/ judge/   모델·채점 컨테이너
db/         DB 스키마 (공통 + 면접 21개 테이블)
app_6_1/    진행 규칙·모델 연결
stubs_6_1/  모듈 간 형식·가짜 모듈 (GPU 없이 전체 흐름)
seed/       시험 데이터·가상 회사 문서
scripts/    적재·측정·문서 생성
bench/      모델 비교 실험
records/    시험·측정 기록
docs/       설계·최종 문서
```

## 실행
```bash
cp .env.example .env          # 비밀값은 .env에만
powershell -File tasks.ps1 up     # 컨테이너 실행
powershell -File tasks.ps1 seed   # 시험 데이터
powershell -File tasks.ps1 test   # pytest + vitest
powershell -File tasks.ps1 e2e    # 웹 전체 흐름 시험
```
`MODULE_MODE=stub`이면 GPU·모델 없이 가짜 모듈로 전체 흐름이 돌아갑니다. 웹: http://localhost:3000

> 새벽소프트와 지원자·이력서는 모두 개발·시험용 가상 데이터입니다.
