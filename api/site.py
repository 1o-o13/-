"""채용 사이트 공개 정보 (로그인 없이)와 지원서 제출.
※ 지원서 작성·제출(CAN-005·006)은 다른 파트 화면이 오기 전까지 쓰는 간단 버전이다."""
import json
from datetime import date

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from api.auth import current_candidate
from api.db import get_db

router = APIRouter(prefix="/api/site")
ACTIVE = ("submitted", "doc_passed", "stage2", "stage2_done")   # 진행 중인 지원 (최종 결과 전). 떨어짐·포기·취소·최종 결과는 끝난 지원


def active_elsewhere(db, candidate_id: int, pid: int) -> dict | None:
    """이 공고 말고 진행 중인 지원이 있으면 그 공고 (한 번에 한 공고만: 진행 중인 전형이 끝나야 다른 공고에 지원)"""
    return db.execute("""SELECT p.title, p.final_announce_at FROM application a JOIN job_posting p ON p.id = a.posting_id
                         WHERE a.candidate_id = %s AND a.posting_id <> %s AND a.status = ANY(%s)
                         ORDER BY p.final_announce_at LIMIT 1""", (candidate_id, pid, list(ACTIVE))).fetchone()


@router.get("/postings")
def postings(db=Depends(get_db, scope="function")):
    """게시된 공고와 일정 (지원 현황·점수 같은 개인 정보는 없음).
    phase: accepting(접수 중) / upcoming(접수 예정, 11/11) / screening(접수 마감·전형 진행 중) / past(지난 공고). 이 순서로"""
    return db.execute("""SELECT * FROM (
                           SELECT id, title, job_role, job_category, career_level, headcount, description, status,
                                  apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at,
                                  now() BETWEEN apply_start AND apply_end AS accepting,
                                  CASE WHEN status IN ('closed', 'finished') OR final_announce_at < now() THEN 'past'
                                       WHEN now() BETWEEN apply_start AND apply_end THEN 'accepting'
                                       WHEN now() < apply_start THEN 'upcoming' ELSE 'screening' END AS phase
                           FROM job_posting WHERE status IN ('published', 'closed', 'finished')) p
                         ORDER BY CASE phase WHEN 'accepting' THEN 0 WHEN 'upcoming' THEN 1 WHEN 'screening' THEN 2 ELSE 3 END,
                                  CASE WHEN phase = 'past' THEN NULL ELSE apply_end END, final_announce_at DESC""").fetchall()


# 자기소개서 문항: 팀 이력서 양식(v0.3 수정본)과 같은 4문항. (저장 이름, 화면에 보이는 질문)
# 임시: 공고별 문항 설정(F-ADM-36)이 오기 전까지 모든 공고 공통. 팀 결정: 입사후포부·성격은 1차 합격 뒤에만 평가에 쓴다(이력서 TRD)
ESSAYS = [
    ("지원동기", "새벽소프트와 이 직무에 지원한 이유를 적어 주세요."),
    ("기술수행경험 및 문제해결경험", "기술을 써서 문제를 해결한 경험을 원인·과정·결과 순서로 구체적으로 적어 주세요."),
    ("입사후포부", "입사 후 이루고 싶은 목표와 그 방법을 적어 주세요."),
    ("성격의 장/단점", "성격의 장점과 단점, 단점을 보완하려는 노력을 경험과 함께 적어 주세요."),
]
ESSAY_MAX = 1000
BIRTH_MIN = 1940   # 생년월일 선택 범위 시작 연도 (임시)


def essay_list(answers: dict[str, str]) -> list[dict]:
    """자기소개서 저장 모양: 문항 순서대로 [{문항, 질문, 답}] (jsonb 객체는 키 순서를 지키지 않고, 지원 당시 질문도 남긴다)"""
    return [{"문항": k, "질문": q, "답": answers[k]} for k, q in ESSAYS]


T = lambda n: Field("", max_length=n)        # noqa: E731  선택 글자 칸


class Education(BaseModel):                  # 학력사항: 기간 · 학교 / 학과 / 학점 · 졸업 여부
    기간: str = T(40)
    학교: str = Field(min_length=1, max_length=60)
    학과: str = T(60)
    학점: str = T(20)                          # 예: 3.72·4.5
    상태: str = T(20)                          # 졸업 / 재학 / 휴학 / 수료


class Award(BaseModel):                      # 수상경력
    수상일: str = T(20)
    수상명: str = Field(min_length=1, max_length=80)
    수여기관: str = T(60)
    내용: str = T(300)


class Career(BaseModel):                     # 경력사항
    기간: str = T(40)
    회사: str = Field(min_length=1, max_length=60)
    직무: str = T(60)
    총기간: str = T(30)
    요약: str = T(200)


class Cert(BaseModel):                       # 보유자격증
    취득일: str = T(20)
    자격증명: str = Field(min_length=1, max_length=60)
    발급기관: str = T(60)


class Activity(BaseModel):                   # 교육사항 & 활동사항
    기간: str = T(40)
    기관: str = T(60)
    과정: str = Field(min_length=1, max_length=80)
    내용: str = T(300)


class CareerDetail(BaseModel):               # 경력직무 상세
    회사: str = Field(min_length=1, max_length=60)
    기간: str = T(40)
    수행직무: str = Field(min_length=1, max_length=1000)


class Skill(BaseModel):                      # 보유기술: 분야 · 기술내역 · 설명
    분야: str = Field(min_length=1, max_length=40)
    기술내역: str = Field(min_length=1, max_length=100)
    설명: str = T(300)


class Project(BaseModel):                    # 프로젝트 소개서
    주제: str = T(80)
    이름: str = Field(min_length=1, max_length=80)
    주소: str = T(200)
    기간: str = T(40)
    인원: str = T(40)
    동기목표: str = T(500)
    개발환경: str = T(300)
    담당역할: str = T(500)
    작업과정성과: str = Field(min_length=1, max_length=1500)
    느낀점: str = T(500)


class ResumeIn(BaseModel):                   # 팀 이력서 양식(4쪽)과 같은 항목. 이름·연락처·이메일은 계정 정보
    성별: str | None = Field(None, pattern=r"^(남|여)$")
    생년월일: date | None = None
    주소: str | None = Field(None, max_length=100)
    Github: str = T(200)                     # 없으면 빈칸 (화면에는 '등록 계정 없음')
    지원직무: str = Field(min_length=1, max_length=60)        # 머리말: 예) Python 백엔드 개발자 지원
    소개: list[str] = Field(min_length=1, max_length=2)       # 머리말 소개 두 줄 (첫 줄 필수)
    학력사항: list[Education] = Field(min_length=1, max_length=5)
    수상경력: list[Award] = Field(default_factory=list, max_length=10)
    경력사항: list[Career] = Field(default_factory=list, max_length=10)
    보유자격증: list[Cert] = Field(default_factory=list, max_length=10)
    교육활동: list[Activity] = Field(default_factory=list, max_length=10)
    경력직무상세: list[CareerDetail] = Field(default_factory=list, max_length=10)
    보유기술: list[Skill] = Field(default_factory=list, max_length=15)
    프로젝트소개서: list[Project] = Field(default_factory=list, max_length=3)
    자기소개서: dict[str, str] = Field(default_factory=dict)  # ESSAYS의 저장 이름 → 답 (모두 필수)
    외부AI동의: bool | None = None             # 외부 AI 처리(국외 전송) 동의. 필수 — 거부(False)·미선택(None)이면 제출 불가 (활동다이어그램 1109 1·5쪽, NFR-07)

    @field_validator("생년월일")
    @classmethod
    def _birth(cls, v: date | None) -> date | None:
        if v and not (BIRTH_MIN <= v.year <= date.today().year - 15):   # 화면 선택지와 같은 범위 (만 15세 이상)
            raise ValueError("생년월일을 확인해 주세요")
        return v

    @field_validator("소개")
    @classmethod
    def _intro(cls, v: list[str]) -> list[str]:
        v = [x.strip()[:120] for x in v if x.strip()]
        if not v:
            raise ValueError("소개 첫 줄을 적어 주세요")
        return v

    @field_validator("자기소개서")
    @classmethod
    def _essays(cls, v: dict[str, str]) -> dict[str, str]:
        out = {}
        for key, _ in ESSAYS:
            ans = (v.get(key) or "").strip()
            if not ans:
                raise ValueError(f"자기소개서 '{key}' 문항을 적어 주세요")
            if len(ans) > ESSAY_MAX:
                raise ValueError(f"자기소개서 '{key}' 문항은 {ESSAY_MAX}자 이내로 적어 주세요")
            out[key] = ans
        return out


def _age(b: date) -> int:
    t = date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def summary_fields(r: dict) -> dict:
    """요약 칸 (기존 코드·화면이 쓰는 한 줄 값): 학력·경력·기술·자기소개 — 양식 항목에서 만든다"""
    edu = r.get("학력사항") or []
    car = r.get("경력사항") or []
    techs = [t.strip() for s in r.get("보유기술") or [] for t in s["기술내역"].split(",") if t.strip() and t.strip() != "기재사항 없음"]
    return {"학력": (f"{edu[0]['학교']} {edu[0]['학과']} {edu[0]['상태']}".strip() if edu else ""),
            "경력": ", ".join(f"{c['회사']} {c['직무']} {c['총기간']}".strip() for c in car) or "없음",
            "기술": list(dict.fromkeys(techs)), "자기소개": " ".join(r.get("소개") or [])}


def _snapshot(db, candidate_id: int, body: ResumeIn) -> dict:
    """화면 입력 → 이력서 저장 모양 (팀 양식 항목 + 요약 칸). 이름·연락처·이메일은 계정 정보"""
    c = db.execute("SELECT name, phone, email FROM candidate WHERE id = %s", (candidate_id,)).fetchone()
    form = body.model_dump(exclude={"성별", "생년월일", "주소", "Github", "자기소개서", "외부AI동의"})
    snap = {"인적사항": {"이름": c["name"], "성별": body.성별, "생년월일": body.생년월일.isoformat() if body.생년월일 else None,
                       "나이": _age(body.생년월일) if body.생년월일 else None, "연락처": c["phone"], "이메일": c["email"],
                       "Github": body.Github or None, "주소": body.주소},
            **form, "자기소개서": essay_list(body.자기소개서)}
    return {**snap, **summary_fields(snap)}


@router.get("/postings/{pid}/my-application")
def my_application(pid: int, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """이 공고에 낸 내 지원서 (수정 화면에 채워 넣을 값). 지원 안 했으면 404"""
    a = db.execute("""SELECT a.id, a.status, a.resume_snapshot AS r, now() BETWEEN p.apply_start AND p.apply_end AS accepting
                      FROM application a JOIN job_posting p ON p.id = a.posting_id
                      WHERE a.posting_id = %s AND a.candidate_id = %s""", (pid, candidate_id)).fetchone()
    if a is None:
        raise HTTPException(404, "이 공고에 낸 지원서가 없습니다")
    r, me = a["r"], a["r"].get("인적사항") or {}
    form = {k: r.get(k, []) for k in ("학력사항", "수상경력", "경력사항", "보유자격증", "교육활동", "경력직무상세", "보유기술", "프로젝트소개서")}
    return {"application_id": a["id"], "editable": a["accepting"] and a["status"] == "submitted",
            "resume": {"성별": me.get("성별"), "생년월일": me.get("생년월일"), "주소": me.get("주소"), "Github": me.get("Github") or "",
                       "지원직무": r.get("지원직무", ""), "소개": r.get("소개") or [r.get("자기소개", "")], **form,
                       "자기소개서": {x["문항"]: x["답"] for x in r.get("자기소개서", [])}}}


DRAFT_MAX = 100_000   # 임시저장 한 건 최대 크기 (JSON 글자 수)


def _drop_draft(db, candidate_id: int, pid: int) -> None:
    db.execute("DELETE FROM resume WHERE candidate_id = %s AND content->'임시저장'->>'공고' = %s", (candidate_id, str(pid)))


@router.get("/postings/{pid}/draft")
def get_draft(pid: int, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """이 공고에 쓰다 만 지원서 (F-CAN-11). 공통 resume 테이블에 '임시저장' 표시를 달아 둔다. 없으면 404"""
    r = db.execute("""SELECT content, updated_at FROM resume WHERE candidate_id = %s AND content->'임시저장'->>'공고' = %s
                      ORDER BY id DESC LIMIT 1""", (candidate_id, str(pid))).fetchone()
    if r is None:
        raise HTTPException(404, "임시저장한 지원서가 없습니다")
    return {"form": r["content"]["양식"], "saved_at": r["updated_at"]}


@router.put("/postings/{pid}/draft")
def save_draft(pid: int, form: dict, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """임시저장: 필수 칸 검사 없이 화면 값을 그대로 둔다. 공고마다 한 건 (새로 저장하면 바꿈). 제출하면 지운다"""
    if len(json.dumps(form, ensure_ascii=False)) > DRAFT_MAX:
        raise HTTPException(413, "임시저장 내용이 너무 깁니다")
    if db.execute("SELECT 1 FROM application WHERE posting_id = %s AND candidate_id = %s", (pid, candidate_id)).fetchone():
        raise HTTPException(409, "이미 제출한 지원서입니다. 수정 저장을 써 주세요")
    with db.transaction():
        _drop_draft(db, candidate_id, pid)
        row = db.execute("INSERT INTO resume(candidate_id, content) VALUES (%s, %s) RETURNING updated_at",
                         (candidate_id, Jsonb({"임시저장": {"공고": str(pid)}, "양식": form}))).fetchone()
    return {"saved_at": row["updated_at"]}


@router.get("/essay-questions")
def essay_questions():
    """지원서 화면의 자기소개서 문항 (저장 이름·질문·글자 수 제한)"""
    return {"questions": [{"key": k, "question": q} for k, q in ESSAYS], "max": ESSAY_MAX}


@router.put("/postings/{pid}/apply")
def update_application(pid: int, body: ResumeIn, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """지원서 수정: 접수 마감 전이고 아직 서류 심사 중(submitted)일 때만. 마지막으로 저장한 내용이 제출본이 된다"""
    _need_ai_consent(body)
    snap = _snapshot(db, candidate_id, body)
    with db.transaction():
        row = db.execute("""UPDATE application a SET resume_snapshot = %s, submitted_at = now() FROM job_posting p
                            WHERE p.id = a.posting_id AND a.posting_id = %s AND a.candidate_id = %s AND a.status = 'submitted'
                              AND now() BETWEEN p.apply_start AND p.apply_end RETURNING a.id""",
                         (Jsonb(snap), pid, candidate_id)).fetchone()
        if row is None:
            raise HTTPException(409, "접수 마감이 지났거나 심사가 시작되어 고칠 수 없습니다")
        db.execute("INSERT INTO resume(candidate_id, content) VALUES (%s, %s)", (candidate_id, Jsonb(snap)))
    return {"application_id": row["id"]}


def _need_ai_consent(body: ResumeIn) -> None:
    if body.외부AI동의 is not True:
        raise HTTPException(400, "외부 AI 처리(국외 전송)에 동의해야 지원서를 제출할 수 있습니다")


def _record_ai_consent(db, candidate_id: int) -> None:
    """동의 기록: 최신 ai_usage 동의서에 (이미 있으면 그대로)"""
    db.execute("""INSERT INTO candidate_consent(candidate_id, consent_document_id)
                  SELECT %s, id FROM consent_document WHERE kind = 'ai_usage' ORDER BY version DESC LIMIT 1
                  ON CONFLICT DO NOTHING""", (candidate_id,))


@router.post("/postings/{pid}/apply", status_code=201)
def apply(pid: int, body: ResumeIn, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """지원서 제출 → 서류 심사 중(submitted). 접수 기간·게시 공고만(DB 트리거), 공고마다 한 번만(DB UNIQUE). 마감 전까지 수정 가능.
    진행 중인 다른 지원(서류 심사 ~ 2차 면접 ~ 최종 발표 전)이 있으면 거부. 외부 AI 처리 동의가 없으면 거부"""
    _need_ai_consent(body)
    other = active_elsewhere(db, candidate_id, pid)
    if other:
        raise HTTPException(409, f"진행 중인 지원('{other['title']}')이 있어 다른 공고에 지원할 수 없습니다. "
                                 f"{other['final_announce_at']:%m월 %d일} 결과 발표 뒤에 지원해 주세요")
    snap = _snapshot(db, candidate_id, body)
    try:
        with db.transaction():
            db.execute("INSERT INTO resume(candidate_id, content) VALUES (%s, %s)", (candidate_id, Jsonb(snap)))
            row = db.execute("""INSERT INTO application(posting_id, candidate_id, resume_snapshot) VALUES (%s, %s, %s)
                                RETURNING id""", (pid, candidate_id, Jsonb(snap))).fetchone()
            _drop_draft(db, candidate_id, pid)                     # 제출했으면 임시저장은 지운다
            _record_ai_consent(db, candidate_id)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "이미 지원한 공고입니다")
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(404, "공고가 없습니다")
    except psycopg.errors.CheckViolation:
        raise HTTPException(409, "접수 기간이 아닌 공고입니다")
    return {"application_id": row["id"]}


# 채용 담당 연락처 (임시: 가상 회사 값. 담당자 개인 전화번호 칸이 공통 스키마에 없어 팀 대표 연락처를 씀)
CONTACT = {"team": "새벽소프트 채용팀", "phone": "02-000-0000", "email": "recruit@saebyeoksoft.example", "hours": "평일 09:00~18:00",
           "onsite": "온라인 면접을 이어 갈 수 없으면 담당자와 일정을 잡아 회사(새벽소프트 본사)에 방문해 같은 방식으로 면접을 볼 수 있습니다."}


@router.get("/contact")
def contact(posting_id: int | None = None, db=Depends(get_db, scope="function")):
    """채용 담당자 연락처 (홈페이지 바닥글·면접 문의하기). 공고가 있으면 정 담당자 이름도"""
    who = db.execute("""SELECT u.name FROM posting_assignee pa JOIN admin_user u ON u.id = pa.admin_user_id
                        WHERE pa.posting_id = %s AND pa.role = 'main'""", (posting_id,)).fetchone() if posting_id else None
    return {**CONTACT, "assignee": who["name"] if who else None}
