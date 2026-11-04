"""6.1이 다른 파트와 주고받는 형식 (영찬 RAG TRD v0.6 6장 기준). 진짜 모듈도 이 형식을 지키면 그대로 끼워진다."""
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "silent", "no_stt", "timeout", "parse_error"]


class Handoff(BaseModel):                 # 1차 인계 (handoff.json, 이력서 TRD 5.4)
    job_role: str
    applied_level: str
    deficit_value: str                    # 결핍 가치 (OWN·COL·INT·CUS·GRW) → 2번 질문
    deficit_reason: str
    check_list: list[str] = []            # 면접 확인 필요 목록: 1차 요건 중 '부족'·'근거 없음' (1번 질문이 먼저 씀, 활동다이어그램 1109 2·4쪽)


class WeaknessSummary(BaseModel):         # 코딩 리뷰 구조화 요약 (coding_result.weakness_summary, CT-33) → 3번 질문
    algorithms: list[str]
    failed_groups: list[int]
    weakness_tags: list[str]


class CompanyDoc(BaseModel):              # 검색 결과 청크 (company_doc_chunk, META_SPEC v0.3)
    chunk_id: str                         # doc#sec
    doc_type: str
    tier: int
    topic: str
    status: str | None = None
    related: list[str] = []
    forbid: list[str] = []
    body: str


class QuestionContext(BaseModel):         # 질문 생성 입력 (이름·학교·연락처는 가린 뒤 전달)
    application_id: int
    job_role: str
    resume_text: str
    handoff: Handoff
    weakness: WeaknessSummary | None = None   # 비개발 직군은 None
    ct_band: Literal["상", "중", "하"] | None = None
    project: str | None = None            # 이력서와 가장 비슷한 회사 프로젝트(topic). 3~10번 기술 질문은 이 프로젝트 문서만
    docs: list[CompanyDoc]                # 검색 후보 (진짜는 메타 필터 → BM25 ∥ bge-m3 → RRF → 재정렬)
    overseas_consent: bool = False        # 국외 전송 동의. 없으면 LLM은 전부 온프레미스 (RAG-17)
    llm: dict = {}                        # 응시에 복사된 모델: provider·eval·fast·local (실제 모듈만 씀)
    session_id: int | None = None         # LLM 호출 기록(llm_call)용


class Question(BaseModel):
    kind: Literal["non_tech", "tech"]
    question_type: Literal["main", "followup", "reask"] = "main"
    depth: int = Field(default=0, ge=0, le=2)
    tech_stack: str | None = None         # 기술 주제
    question_text: str = Field(min_length=1)
    basis: str
    source_doc_ids: list[str] = []
    min_tier: int | None = None           # 근거 중 가장 낮은 tier → LLM 경로 (RAG-17)
    key_points: list[str]
    model: str
    defense: dict = {}                    # 꼬리질문 모순 검사 결과 (FR-77) → interview_question.defense


class Judgement(BaseModel):
    status: Status = "ok"
    score: float | None = Field(default=None, ge=0, le=100)   # 기술: 루브릭 100점. 비기술·평가 실패는 None
    rubric: dict = {}                     # 정확성 30·회사 적용 30·깊이 25·구체성 15
    opinion: dict | None = None           # 비기술 의견
    quotes: list[str]
    rationale: str = Field(min_length=1)
    relevance: float | None = Field(default=None, ge=0, le=1)  # CE(질문, 답변) 관련성 (FR-81). 점수에 안 더하고 꼬리 분기에만. None = 측정 안 함
    lang_structure: int = Field(ge=0, le=10)
    lang_terms: int = Field(ge=0, le=10)
    lang_intent: int = Field(ge=0, le=10)
    model_tier: Literal["eval", "fast"]
    model: str
    latency_ms: int = Field(ge=0)


class Turn(BaseModel):                    # 최종 평가 입력의 한 줄 (물어본 순서대로)
    ask_order: int
    question: Question
    stt_text: str | None
    judgement: Judgement
    answer_sec: float
    finished_in_time: bool
    silence_ratio: float = Field(ge=0, le=1)


class Check(BaseModel):
    check_no: int = Field(ge=1, le=5)
    passed: bool
    checker: str
    detail: str | None = None


class Evaluation(BaseModel):
    version_no: int = Field(ge=1, le=2)
    topic_scores: dict[str, float]        # 주제 점수 T = S_d + 40 × 평균/100
    content_score: float = Field(ge=0, le=60)
    language_score: float = Field(ge=0, le=30)
    nonverbal_score: float = Field(ge=0, le=10)
    rationale: str
    project_topic: str | None = None      # 판정 기준 프로젝트
    fit_opinion: str = ""                 # 적합성 의견 (점수에 넣지 않음)
    growth_opinion: str = ""              # 확장성 의견 (점수에 넣지 않음)
    checks: list[Check]
    status: Literal["passed", "failed"]
    model: str
