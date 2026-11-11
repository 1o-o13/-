"""채용 요청·공고 관리 (ADM-020~024, 공통 DB 3장). ※ 임시: 공고 파트 정식 기능이 오면 교체 (11/11 사용자 요청으로 6.1에서 먼저 구현)

흐름 (공통 스키마 hiring_request·job_posting·posting_review·posting_assignee·posting_history 그대로):
  부서원이 채용 요청(submitted) → 채용 담당이 요청으로 공고 작성(draft, 요청은 converted) 또는 반려(rejected)
  → 부서 확인 요청(dept_review) → 요청 부서가 승인(approved) 또는 수정 요청(changes_requested → draft)
  → 채용 담당이 게시(published) → 접수·심사 → 마감(closed)
  부서 요청 없이 채용 담당이 바로 만든 공고는 부서 확인 없이 게시한다.
- 공고를 만들면 AI 면접 설정(interview_setting)·코딩 테스트 설정(개발 직군만)·정 담당자(만든 사람)를 함께 만든다
- 고칠 때마다 바뀐 칸을 posting_history에 남긴다. 지원자가 생긴 뒤에는 직무·직군·경력 구간을 못 바꾼다
- 일정 순서(접수 → 1차 발표 → 2차 응시 → 최종 발표)는 DB 규칙이 정답이다
"""
import os
from datetime import datetime
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api.admin.routes import READ, WRITE
from api.db import get_db
from api.interview.engine import DEPT

router = APIRouter(prefix="/api/admin")
JOB_ROLES = list(DEPT)                                # 회사 문서·질문 은행이 있는 직무만 (임시: 팀 미정)
CAREER = Literal["new", "junior", "senior"]
FIELDS = ("title", "job_role", "job_category", "career_level", "headcount", "description",
          "apply_start", "apply_end", "doc_announce_at", "stage2_start", "stage2_end", "final_announce_at")
LOCKED_AFTER_APPLY = ("job_role", "job_category", "career_level")


def _me(db, admin: dict) -> dict:
    return db.execute("SELECT id, role, name, department_id FROM admin_user WHERE id = %s", (admin["id"],)).fetchone()


def _posting(db, pid: int) -> dict:
    p = db.execute("""SELECT p.*, hr.department_id AS request_dept, d.name AS request_dept_name, u.name AS created_by_name
                      FROM job_posting p LEFT JOIN hiring_request hr ON hr.id = p.hiring_request_id
                      LEFT JOIN department d ON d.id = hr.department_id LEFT JOIN admin_user u ON u.id = p.created_by
                      WHERE p.id = %s""", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "공고가 없습니다")
    return p


def _rule_error(e: psycopg.Error) -> HTTPException:
    msg = str(e)
    if "job_posting_check" in msg or "apply_start" in msg:
        return HTTPException(422, "일정 순서가 맞지 않습니다: 접수 시작 < 접수 마감 ≤ 1차 발표 ≤ 2차 시작 < 2차 마감 ≤ 최종 발표")
    if "headcount" in msg:
        return HTTPException(422, "모집 인원은 1명 이상이어야 합니다")
    return HTTPException(422, "DB 규칙에 맞지 않습니다")


# ---------- 부서 채용 요청 (ADM-020·021) ----------

class RequestIn(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    job_role: str
    headcount: int = Field(ge=1, le=100)
    career_level: CAREER
    reason: str | None = Field(None, max_length=1000)


@router.get("/hiring-requests")
def hiring_requests(admin=Depends(READ), db=Depends(get_db, scope="function")):
    """부서원은 자기 부서 요청만, 채용 담당·최고관리자는 전부"""
    me = _me(db, admin)
    mine = me["role"] == "dept_member"
    return db.execute(f"""SELECT r.id, r.title, r.job_role, r.headcount, r.career_level, r.reason, r.status, r.created_at,
                                 d.name AS department, u.name AS requested_by, h.name AS handled_by,
                                 (SELECT p.id FROM job_posting p WHERE p.hiring_request_id = r.id) AS posting_id
                          FROM hiring_request r JOIN department d ON d.id = r.department_id JOIN admin_user u ON u.id = r.requested_by
                          LEFT JOIN admin_user h ON h.id = r.handled_by
                          {"WHERE r.department_id = %s" if mine else ""} ORDER BY r.id DESC""",
                      (me["department_id"],) if mine else ()).fetchall()


@router.post("/hiring-requests", status_code=201)
def create_request(body: RequestIn, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """채용 요청: 부서원(자기 부서)·채용 담당·최고관리자. 부서가 없는 관리자는 요청할 수 없다"""
    me = _me(db, admin)
    if me["role"] == "sys_admin":
        raise HTTPException(403, "권한이 없습니다")
    if body.job_role not in JOB_ROLES:
        raise HTTPException(422, f"직무는 {', '.join(JOB_ROLES)} 중 하나")
    if me["department_id"] is None:
        raise HTTPException(409, "소속 부서가 없어 요청할 수 없습니다")
    return db.execute("""INSERT INTO hiring_request(department_id, requested_by, title, job_role, headcount, career_level, reason)
                         VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, status""",
                      (me["department_id"], me["id"], body.title, body.job_role, body.headcount, body.career_level, body.reason)).fetchone()


@router.post("/hiring-requests/{rid}/reject")
def reject_request(rid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """요청 반려 (채용 담당). 아직 공고로 만들지 않은 요청만"""
    r = db.execute("""UPDATE hiring_request SET status = 'rejected', handled_by = %s
                      WHERE id = %s AND status IN ('submitted', 'accepted') RETURNING id, status""", (admin["id"], rid)).fetchone()
    if r is None:
        raise HTTPException(409, "반려할 수 없는 요청입니다")
    return r


# ---------- 공고 (ADM-022~024) ----------

class PostingIn(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    job_role: str
    job_category: Literal["dev", "non_dev"]
    career_level: CAREER
    headcount: int = Field(ge=1, le=100)
    description: str = Field(min_length=10, max_length=5000)
    apply_start: datetime
    apply_end: datetime
    doc_announce_at: datetime
    stage2_start: datetime
    stage2_end: datetime
    final_announce_at: datetime
    hiring_request_id: int | None = None
    languages: list[Literal["python", "java"]] = ["python", "java"]   # 코딩 테스트 언어 (개발 직군)
    coding_minutes: int = Field(90, ge=10, le=300)


@router.get("/postings/all")
def all_postings(admin=Depends(READ), db=Depends(get_db, scope="function")):
    """공고 관리 목록: 상태·지원자 수·담당자·부서 확인 상태"""
    return db.execute("""SELECT p.id, p.title, p.job_role, p.job_category, p.career_level, p.headcount, p.status, p.apply_start, p.apply_end,
                                p.final_announce_at, p.published_at, d.name AS request_dept,
                                (SELECT count(*) FROM application a WHERE a.posting_id = p.id AND a.status <> 'withdrawn') AS applicants,
                                (SELECT u.name FROM posting_assignee pa JOIN admin_user u ON u.id = pa.admin_user_id
                                 WHERE pa.posting_id = p.id AND pa.role = 'main') AS main_assignee,
                                (SELECT r.decision FROM posting_review r WHERE r.posting_id = p.id ORDER BY r.id DESC LIMIT 1) AS review
                         FROM job_posting p LEFT JOIN hiring_request hr ON hr.id = p.hiring_request_id
                         LEFT JOIN department d ON d.id = hr.department_id
                         ORDER BY p.id DESC""").fetchall()


@router.get("/postings/{pid}")
def posting_detail(pid: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    p, me = _posting(db, pid), _me(db, admin)
    return {"posting": p,
            "can_review": p["status"] == "dept_review" and (me["role"] == "super_admin"
                                                          or (me["role"] == "dept_member" and me["department_id"] == p["request_dept"])),
            "coding": db.execute("SELECT languages, time_limit_min FROM coding_setting WHERE posting_id = %s", (pid,)).fetchone(),
            "assignees": db.execute("""SELECT u.id, u.name, pa.role FROM posting_assignee pa JOIN admin_user u ON u.id = pa.admin_user_id
                                       WHERE pa.posting_id = %s ORDER BY pa.role""", (pid,)).fetchall(),
            "reviews": db.execute("""SELECT r.decision, r.comment, r.created_at, u.name AS reviewer FROM posting_review r
                                     JOIN admin_user u ON u.id = r.reviewer_id WHERE r.posting_id = %s ORDER BY r.id""", (pid,)).fetchall(),
            "history": db.execute("""SELECT h.change, h.created_at, u.name AS by FROM posting_history h JOIN admin_user u ON u.id = h.changed_by
                                     WHERE h.posting_id = %s ORDER BY h.id""", (pid,)).fetchall(),
            "applicants": db.execute("SELECT count(*) AS n FROM application WHERE posting_id = %s AND status <> 'withdrawn'", (pid,)).fetchone()["n"],
            "job_roles": JOB_ROLES}


@router.post("/postings", status_code=201)
def create_posting(body: PostingIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """공고 작성(draft). 부서 요청에서 만들면 요청은 converted. 면접·코딩 설정·정 담당자를 함께 만든다"""
    if body.job_role not in JOB_ROLES:
        raise HTTPException(422, f"직무는 {', '.join(JOB_ROLES)} 중 하나")
    if body.job_category == "dev" and not body.languages:
        raise HTTPException(422, "코딩 테스트 언어를 하나 이상 고르세요")
    try:
        with db.transaction():
            if body.hiring_request_id is not None:
                if db.execute("""UPDATE hiring_request SET status = 'converted', handled_by = %s
                                 WHERE id = %s AND status IN ('submitted', 'accepted') RETURNING id""",
                              (admin["id"], body.hiring_request_id)).fetchone() is None:
                    raise HTTPException(409, "공고로 만들 수 없는 요청입니다 (이미 공고로 만들었거나 반려됨)")
            p = db.execute(f"""INSERT INTO job_posting(hiring_request_id, {", ".join(FIELDS)}, created_by)
                               VALUES (%s, {", ".join(["%s"] * len(FIELDS))}, %s) RETURNING id""",
                           (body.hiring_request_id, *[getattr(body, f) for f in FIELDS], admin["id"])).fetchone()
            pid = p["id"]
            # AI 면접 설정: 기본값(10문항·생각 10/20초 등) + 이 서버의 모델 설정 (.env). 담당자가 'AI 면접 설정'에서 고친다
            provider = os.environ.get("LLM_PROVIDER", "ollama")
            db.execute("""INSERT INTO interview_setting(posting_id, company_requirements, llm_provider, llm_eval_model, llm_fast_model)
                          VALUES (%s, %s, %s, %s, %s)""",
                       (pid, body.description, provider, os.environ.get("LLM_EVAL_MODEL", "qwen3:4b"),
                        os.environ.get("LLM_FAST_MODEL", "qwen3:1.7b")))
            if body.job_category == "dev":
                db.execute("INSERT INTO coding_setting(posting_id, languages, time_limit_min) VALUES (%s, %s, %s)",
                           (pid, body.languages, body.coding_minutes))
            db.execute("INSERT INTO posting_assignee(posting_id, admin_user_id, role) VALUES (%s, %s, 'main')", (pid, admin["id"]))
            db.execute("INSERT INTO posting_history(posting_id, changed_by, change) VALUES (%s, %s, %s)",
                       (pid, admin["id"], Jsonb({"action": "작성"})))
    except psycopg.errors.CheckViolation as e:
        raise _rule_error(e) from None
    return {"id": pid, "status": "draft"}


@router.put("/postings/{pid}")
def update_posting(pid: int, body: PostingIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """공고 수정. 마감 전까지. 지원자가 생긴 뒤에는 직무·직군·경력 구간을 못 바꾼다. 바뀐 칸을 이력에 남긴다.
    부서 확인 중인 공고를 고치면 다시 작성 중(draft)으로 (바뀐 내용을 다시 확인받는다)"""
    p = _posting(db, pid)
    if p["status"] in ("closed", "finished"):
        raise HTTPException(409, "마감한 공고는 고칠 수 없습니다")
    new = {f: getattr(body, f) for f in FIELDS}
    changed = {f: [str(p[f]), str(new[f])] for f in FIELDS if p[f] != new[f]}
    if not changed:
        return {"id": pid, "changed": []}
    applied = db.execute("SELECT 1 FROM application WHERE posting_id = %s LIMIT 1", (pid,)).fetchone()
    if applied and any(f in changed for f in LOCKED_AFTER_APPLY):
        raise HTTPException(409, "지원자가 있어 직무·직군·경력 구간은 바꿀 수 없습니다")
    if body.job_role not in JOB_ROLES:
        raise HTTPException(422, f"직무는 {', '.join(JOB_ROLES)} 중 하나")
    try:
        with db.transaction():
            db.execute(f"""UPDATE job_posting SET {", ".join(f"{f} = %s" for f in FIELDS)},
                               status = CASE WHEN status = 'dept_review' THEN 'draft' ELSE status END WHERE id = %s""",
                       (*new.values(), pid))
            if "job_category" in changed:
                if body.job_category == "dev":
                    db.execute("""INSERT INTO coding_setting(posting_id, languages, time_limit_min) VALUES (%s, %s, %s)
                                  ON CONFLICT (posting_id) DO NOTHING""", (pid, body.languages, body.coding_minutes))
                else:
                    db.execute("DELETE FROM coding_setting WHERE posting_id = %s", (pid,))
            if body.job_category == "dev":
                db.execute("UPDATE coding_setting SET languages = %s, time_limit_min = %s WHERE posting_id = %s",
                           (body.languages, body.coding_minutes, pid))
            db.execute("INSERT INTO posting_history(posting_id, changed_by, change) VALUES (%s, %s, %s)",
                       (pid, admin["id"], Jsonb({"action": "수정", "fields": changed})))
    except psycopg.errors.CheckViolation as e:
        raise _rule_error(e) from None
    return {"id": pid, "changed": list(changed)}


@router.post("/postings/{pid}/submit-review")
def submit_review(pid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """요청 부서에 게시 전 확인 요청 (부서 요청으로 만든 공고만)"""
    p = _posting(db, pid)
    if p["hiring_request_id"] is None:
        raise HTTPException(409, "부서 요청 없이 만든 공고는 확인 없이 바로 게시합니다")
    if p["status"] != "draft":
        raise HTTPException(409, "작성 중인 공고만 확인을 요청할 수 있습니다")
    db.execute("UPDATE job_posting SET status = 'dept_review' WHERE id = %s", (pid,))
    db.execute("INSERT INTO posting_history(posting_id, changed_by, change) VALUES (%s, %s, %s)",
               (pid, admin["id"], Jsonb({"action": "부서 확인 요청"})))
    return {"status": "dept_review"}


class ReviewIn(BaseModel):
    decision: Literal["approved", "changes_requested"]
    comment: str | None = Field(None, max_length=1000)


@router.post("/postings/{pid}/review")
def review_posting(pid: int, body: ReviewIn, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """요청 부서 확인 (ADM-023): 요청한 부서의 부서원 또는 최고관리자. 수정 요청이면 작성 중으로 돌아가고 사유가 필요하다"""
    p, me = _posting(db, pid), _me(db, admin)
    if p["status"] != "dept_review":
        raise HTTPException(409, "부서 확인 중인 공고가 아닙니다")
    if not (me["role"] == "super_admin" or (me["role"] == "dept_member" and me["department_id"] == p["request_dept"])):
        raise HTTPException(403, "요청한 부서만 확인할 수 있습니다")
    if body.decision == "changes_requested" and not (body.comment or "").strip():
        raise HTTPException(422, "수정 요청은 사유를 적어 주세요")
    db.execute("INSERT INTO posting_review(posting_id, reviewer_id, decision, comment) VALUES (%s, %s, %s, %s)",
               (pid, me["id"], body.decision, body.comment))
    if body.decision == "changes_requested":
        db.execute("UPDATE job_posting SET status = 'draft' WHERE id = %s", (pid,))
    return {"decision": body.decision}


@router.post("/postings/{pid}/publish")
def publish_posting(pid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """게시 (ADM-024): 부서 요청 공고는 부서 승인 뒤에만. 게시하면 채용 홈에 보이고 접수 기간에 지원할 수 있다"""
    p = _posting(db, pid)
    if p["hiring_request_id"] is not None:
        last = db.execute("SELECT decision FROM posting_review WHERE posting_id = %s ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        if p["status"] != "dept_review" or not last or last["decision"] != "approved":
            raise HTTPException(409, "요청 부서의 확인(승인)을 받은 뒤 게시할 수 있습니다")
    elif p["status"] != "draft":
        raise HTTPException(409, "작성 중인 공고만 게시할 수 있습니다")
    db.execute("UPDATE job_posting SET status = 'published', published_at = now() WHERE id = %s", (pid,))
    db.execute("INSERT INTO posting_history(posting_id, changed_by, change) VALUES (%s, %s, %s)",
               (pid, admin["id"], Jsonb({"action": "게시"})))
    return {"status": "published"}


@router.post("/postings/{pid}/close")
def close_posting(pid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """마감: 채용 홈에서 '지난 공고'로. 게시된 공고만"""
    if db.execute("UPDATE job_posting SET status = 'closed' WHERE id = %s AND status = 'published' RETURNING id", (pid,)).fetchone() is None:
        raise HTTPException(409, "게시 중인 공고만 마감할 수 있습니다")
    db.execute("INSERT INTO posting_history(posting_id, changed_by, change) VALUES (%s, %s, %s)",
               (pid, admin["id"], Jsonb({"action": "마감"})))
    return {"status": "closed"}


@router.delete("/postings/{pid}")
def delete_posting(pid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """작성 중인(게시 전) 공고 삭제. 부서 요청에서 만든 공고면 요청을 다시 '접수'로 돌린다"""
    p = _posting(db, pid)
    if p["status"] not in ("draft", "dept_review"):
        raise HTTPException(409, "게시한 공고는 지울 수 없습니다 (마감하세요)")
    with db.transaction():
        for t in ("interview_setting", "coding_setting", "document_criteria"):
            db.execute(f"DELETE FROM {t} WHERE posting_id = %s", (pid,))
        db.execute("DELETE FROM job_posting WHERE id = %s", (pid,))   # 담당자·확인·이력은 CASCADE
        if p["hiring_request_id"]:
            db.execute("UPDATE hiring_request SET status = 'submitted' WHERE id = %s", (p["hiring_request_id"],))
    return {"deleted": pid}
