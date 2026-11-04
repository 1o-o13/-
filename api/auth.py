"""※ 임시 로그인 — 공통 기반 파트(6.3, I-3)가 정식 구현하면 이 파일을 통째로 교체한다.

- 지원자: 이메일·비밀번호 회원가입·로그인 / 관리자: 아이디·비밀번호 + TOTP(2단계 인증)
- 비밀번호 bcrypt, 로그인 상태는 JWT(HS256)를 HttpOnly 쿠키로
- 다른 코드는 아래 의존성만 쓴다: current_candidate, current_admin(*roles), own_application
"""
import hashlib
import os
import re
import time

import bcrypt
import jwt
import psycopg
import pyotp
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from api.db import get_db

COOKIE = "session"              # 지원자 로그인
ADMIN_COOKIE = "admin_session"  # 관리자 로그인 (따로 둬서 한 브라우저에서 지원자·관리자를 동시에 로그인할 수 있게, 11/10)
COOKIES = {"candidate": COOKIE, "admin": ADMIN_COOKIE}
TTL_SEC = {"candidate": 3600, "admin": 4 * 3600}   # 지원자 1시간(쓰는 동안 자동 연장, api/main.py), 관리자 4시간(임시)
SLIDE_AFTER_SEC = 60        # 지원자 쿠키는 마지막 연장 뒤 1분이 지난 요청부터 다시 1시간으로 늘린다 (요청마다 새로 만들지 않게)
ADMIN_ROLES = ("super_admin", "sys_admin", "recruiter", "dept_member")
ADMIN_WRITE = ("super_admin", "recruiter")   # 임시: 설정·확정·재응시는 이 역할만, 나머지는 조회만 (팀 미정)

router = APIRouter(prefix="/api/auth")


# ---- 가입 입력 틀 (화면 web/lib/rules.ts와 같은 규칙. 서버가 최종 판단) ----
NAME_KO = re.compile(r"^[가-힣]{2,17}$")                          # 한글 이름 2~17자 (띄어쓰기 없음)
NAME_EN = re.compile(r"^(?=.{2,30}$)[A-Za-z]+(?: [A-Za-z]+)*$")  # 임시: 영문 이름 2~30자, 단어 사이 한 칸
EMAIL_DOMAINS = ("naver.com", "gmail.com", "daum.net", "hanmail.net", "kakao.com", "nate.com",
                 "outlook.com", "hotmail.com", "icloud.com", "yahoo.com")   # 임시: 실제 쓰는 메일 서비스만 (목록은 팀 확정 전)
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@(" + "|".join(map(re.escape, EMAIL_DOMAINS)) + r")$", re.IGNORECASE)
PHONE = re.compile(r"^01[016789]-\d{4}-\d{4}$")               # 국내 휴대폰 앞 3자리(010·011·016~019)-4자리-4자리
PASSWORD = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9\s])\S{8,13}$")   # 영문·숫자·특수문자 포함 8~13자
LOGIN_ID = re.compile(r"^[a-z][a-z0-9]{3,19}$")                  # 임시: 관리자 아이디 영문 소문자로 시작, 4~20자


def _check(rule: re.Pattern, value: str, msg: str) -> str:
    if not rule.match(value):
        raise ValueError(msg)
    return value


class _Person(BaseModel):
    password: str
    name: str

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check(PASSWORD, v, "비밀번호는 영문·숫자·특수문자를 모두 넣어 8~13자로 입력해 주세요")

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not (NAME_KO.match(v) or NAME_EN.match(v)):
            raise ValueError("이름은 한글 2~17자 또는 영문으로 입력해 주세요")
        return v


class SignupIn(_Person):
    email: str
    phone: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _check(EMAIL, v, "네이버·구글 등 실제 쓰는 메일 주소를 입력해 주세요")

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _check(PHONE, v, "휴대폰 번호는 010-1234-5678 형식으로 입력해 주세요")


class AdminSignupIn(_Person):
    login_id: str
    role: str = Field(pattern=r"^(recruiter|dept_member)$")   # 가입 신청은 채용 담당·부서원만 (최고관리자는 신청 불가)
    department_id: int

    @field_validator("login_id")
    @classmethod
    def _login_id(cls, v: str) -> str:
        return _check(LOGIN_ID, v, "아이디는 영문 소문자로 시작하는 영문 소문자·숫자 4~20자로 입력해 주세요")


class LoginIn(BaseModel):
    email: str
    password: str


class AdminLoginIn(BaseModel):
    login_id: str
    password: str
    otp: str | None = None


def _issue(resp: Response, typ: str, sub: int, role: str | None = None) -> None:
    token = jwt.encode({"typ": typ, "sub": str(sub), "role": role, "exp": int(time.time()) + TTL_SEC[typ]},
                       os.environ["JWT_SECRET"], algorithm="HS256")
    # 임시: 로컬 http 개발이라 secure 없음. 운영(nginx HTTPS)에서는 secure=True
    resp.set_cookie(COOKIES[typ], token, max_age=TTL_SEC[typ], httponly=True, samesite="lax")


def _password_ok(password: str, hashed: str | None) -> bool:
    return hashed is not None and bcrypt.checkpw(password.encode(), hashed.encode())


@router.post("/signup", status_code=201)
def signup(body: SignupIn, db=Depends(get_db, scope="function")):
    email = body.email.lower()
    ci_hash = "TMP_" + hashlib.sha256(email.encode()).hexdigest()   # 임시: 휴대폰 본인인증(CI) 대신 가짜 값
    try:
        row = db.execute("""INSERT INTO candidate(email, password_hash, name, phone, ci_hash)
                            VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                         (email, bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode(),
                          body.name, body.phone, ci_hash)).fetchone()
    except psycopg.errors.UniqueViolation:
        cid = rejoin(db, email, body.name, body.phone, bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode())
        if cid is None:
            raise HTTPException(409, "이미 가입한 이메일입니다")
        return {"id": cid}
    return {"id": row["id"]}


def rejoin(db, email: str, name: str, phone: str, password_hash: str | None) -> int | None:
    """탈퇴한 계정의 이메일로 다시 가입: 재가입 제한(진행 중이던 공고의 최종 발표일)이 끝났으면 예전 계정을 다시 살린다.
    예전 지원 기록이 이어지므로 이미 지원했던 공고에는 다시 지원할 수 없다. 탈퇴 계정이 아니면 None"""
    w = db.execute("""SELECT id, rejoin_blocked_until, rejoin_blocked_until > now() AS blocked FROM candidate
                      WHERE email = %s AND status = 'withdrawn'""", (email,)).fetchone()
    if w is None:
        return None
    if w["blocked"]:
        raise HTTPException(409, f"탈퇴 때 진행 중이던 공고가 끝나는 {w['rejoin_blocked_until']:%Y-%m-%d} 이후에 다시 가입할 수 있습니다")
    db.execute("""UPDATE candidate SET status = 'active', withdrawn_at = NULL, rejoin_blocked_until = NULL, name = %s, phone = %s,
                      password_hash = %s WHERE id = %s""", (name, phone, password_hash, w["id"]))
    return w["id"]


@router.post("/login")
def login(body: LoginIn, resp: Response, db=Depends(get_db, scope="function")):
    row = db.execute("SELECT id, password_hash FROM candidate WHERE email = %s AND status = 'active'",
                     (body.email.lower(),)).fetchone()
    if row is None or not _password_ok(body.password, row["password_hash"]):
        raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않습니다")
    _issue(resp, "candidate", row["id"])
    return {"id": row["id"]}


@router.post("/admin/login")
def admin_login(body: AdminLoginIn, resp: Response, db=Depends(get_db, scope="function")):
    row = db.execute("SELECT id, password_hash, role, totp_secret_enc, is_active FROM admin_user WHERE login_id = %s",
                     (body.login_id,)).fetchone()
    if row is None or not _password_ok(body.password, row["password_hash"]):
        raise HTTPException(401, "아이디 또는 비밀번호가 맞지 않습니다")
    if not row["is_active"]:                      # 비밀번호가 맞을 때만 알려 준다
        raise HTTPException(403, "승인 대기 중인 계정입니다. 최고관리자 승인 후 로그인할 수 있습니다")
    # 임시: 시험 데이터는 totp_secret_enc에 평문 비밀값이 들어 있음. 암호화 방식은 공통 기반 파트가 정함
    # dept_member는 스키마상 2단계 인증이 선택이라, 비밀값이 없으면 OTP 없이 로그인
    if row["totp_secret_enc"] and not (body.otp and pyotp.TOTP(row["totp_secret_enc"]).verify(body.otp, valid_window=1)):
        raise HTTPException(401, "인증 코드가 맞지 않습니다")
    _issue(resp, "admin", row["id"], row["role"])
    return {"id": row["id"], "role": row["role"]}


@router.get("/departments")
def departments(db=Depends(get_db, scope="function")):
    """관리자 가입 신청 화면의 부서 고르기"""
    return db.execute("SELECT id, name FROM department ORDER BY id").fetchall()


@router.post("/admin/signup", status_code=201)
def admin_signup(body: AdminSignupIn, db=Depends(get_db, scope="function")):
    """관리자 가입 신청 → 승인 대기(is_active = false). 최고관리자가 승인해야 로그인된다 (api/admin/routes.py)"""
    try:
        row = db.execute("""INSERT INTO admin_user(login_id, password_hash, name, role, department_id, is_active)
                            VALUES (%s, %s, %s, %s, %s, false) RETURNING id""",
                         (body.login_id, bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode(), body.name,
                          body.role, body.department_id)).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "이미 쓰고 있는 아이디입니다")
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(422, "부서를 골라 주세요")
    return {"id": row["id"]}


# 개발용 바로 로그인 (DEV_QUICK_LOGIN=1일 때만. 운영 .env에는 넣지 않는다). 계정은 seed/demo_accounts.sql
QUICK = {"cand1": ("candidate", "haneul.kim@naver.com"), "cand2": ("candidate", "sehun.oh@gmail.com"),
         "cand3": ("candidate", "jimin.park@naver.com"), "cand4": ("candidate", "junseo.lee@gmail.com"),
         "admin": ("admin", "admin"), "hr01": ("admin", "hr01")}


@router.get("/dev/enabled")
def dev_enabled():
    """로그인 화면이 바로 로그인 버튼을 보일지 (화면 빌드 방식과 무관하게 .env DEV_QUICK_LOGIN=1이면, 11/10)"""
    return {"enabled": os.environ.get("DEV_QUICK_LOGIN") == "1"}


@router.post("/dev/login/{who}")
def dev_login(who: str, resp: Response, db=Depends(get_db, scope="function")):
    if os.environ.get("DEV_QUICK_LOGIN") != "1" or who not in QUICK:
        raise HTTPException(404)
    typ, key = QUICK[who]
    if typ == "candidate":
        row = db.execute("SELECT id, NULL AS role FROM candidate WHERE email = %s AND status = 'active'", (key,)).fetchone()
    else:
        row = db.execute("SELECT id, role FROM admin_user WHERE login_id = %s AND is_active", (key,)).fetchone()
    if row is None:
        raise HTTPException(404, "시험 계정이 없습니다 (tasks.ps1 seed)")
    _issue(resp, typ, row["id"], row["role"])
    return {"type": typ, "id": row["id"], "role": row["role"]}


As = Literal["candidate", "admin"]


@router.post("/logout")
def logout(resp: Response, as_: As = Query("candidate", alias="as")):
    """as=candidate(채용 사이트)·admin(관리자 화면): 그쪽 로그인만 끝낸다 (다른 쪽은 그대로)"""
    resp.delete_cookie(COOKIES[as_])
    return {"ok": True}


def _decode(token: str | None, typ: str) -> dict:
    if not token:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        c = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "로그인이 필요합니다")
    if c["typ"] != typ:                          # 쿠키 이름과 종류가 다르면 (만들어 붙인 쿠키) 거부
        raise HTTPException(401, "로그인이 필요합니다")
    return c


def _cand_claims(session: str | None = Cookie(default=None)) -> dict:
    return _decode(session, "candidate")


def _admin_claims(admin_session: str | None = Cookie(default=None)) -> dict:
    return _decode(admin_session, "admin")


def _claims_as(request: Request, as_: As | None) -> dict:
    """as가 없으면 지원자 → 관리자 순으로 (옛 화면 호환)"""
    if as_:
        return _decode(request.cookies.get(COOKIES[as_]), as_)
    for typ in ("candidate", "admin"):
        if request.cookies.get(COOKIES[typ]):
            return _decode(request.cookies.get(COOKIES[typ]), typ)
    raise HTTPException(401, "로그인이 필요합니다")


@router.get("/me")
def me(request: Request, as_: As | None = Query(None, alias="as")):
    """exp: 로그인이 끝나는 시각(유닉스 초). 홈페이지 머리글이 남은 시간을 보여 준다. as=candidate·admin으로 어느 쪽 로그인인지"""
    claims = _claims_as(request, as_)
    return {"type": claims["typ"], "id": int(claims["sub"]), "role": claims["role"], "exp": claims["exp"]}


@router.post("/refresh")
def refresh(request: Request, resp: Response, as_: As | None = Query(None, alias="as")):
    """로그인 연장 (머리글의 '연장' 버튼). 남은 시간을 처음 길이로 되돌린다"""
    claims = _claims_as(request, as_)
    _issue(resp, claims["typ"], int(claims["sub"]), claims["role"])
    return {"ok": True}


def slide(token: str | None) -> tuple[str, int] | None:
    """지원자 쿠키 자동 연장: 아직 살아 있고 마지막 발급 뒤 SLIDE_AFTER_SEC가 지났으면 새 쿠키 값. 아니면 None"""
    try:
        c = jwt.decode(token or "", os.environ["JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if c["typ"] != "candidate" or c["exp"] - time.time() > TTL_SEC["candidate"] - SLIDE_AFTER_SEC:
        return None
    new = jwt.encode({**c, "exp": int(time.time()) + TTL_SEC["candidate"]}, os.environ["JWT_SECRET"], algorithm="HS256")
    return new, TTL_SEC["candidate"]


def current_candidate(claims: dict = Depends(_cand_claims), db=Depends(get_db, scope="function")) -> int:
    if claims["typ"] != "candidate":
        raise HTTPException(403, "지원자만 쓸 수 있습니다")
    if not db.execute("SELECT 1 FROM candidate WHERE id = %s AND status = 'active'", (int(claims["sub"]),)).fetchone():
        raise HTTPException(401, "로그인이 필요합니다")          # 탈퇴한 계정의 쿠키
    return int(claims["sub"])


def current_admin(*roles: str):
    """current_admin() = 관리자 누구나, current_admin(*ADMIN_WRITE) = 쓰기 권한 역할만"""
    def dep(claims: dict = Depends(_admin_claims)) -> dict:
        if claims["typ"] != "admin" or (roles and claims["role"] not in roles):
            raise HTTPException(403, "권한이 없습니다")
        return {"id": int(claims["sub"]), "role": claims["role"]}
    return dep


def own_application(app_id: int, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")) -> int:
    """경로의 app_id가 로그인한 지원자의 지원서인지 확인. 남의 것이면 403"""
    row = db.execute("SELECT candidate_id FROM application WHERE id = %s", (app_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "지원서가 없습니다")
    if row["candidate_id"] != candidate_id:
        raise HTTPException(403, "본인 지원서만 볼 수 있습니다")
    return app_id


# ---- 내 정보·회원 탈퇴 (지원자) ----
class ProfileIn(BaseModel):
    name: str
    phone: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not (NAME_KO.match(v) or NAME_EN.match(v)):
            raise ValueError("이름은 한글 2~17자 또는 영문으로 입력해 주세요")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _check(PHONE, v, "휴대폰 번호는 010-1234-5678 형식으로 입력해 주세요")


class PasswordIn(BaseModel):
    current: str
    new: str

    @field_validator("new")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check(PASSWORD, v, "비밀번호는 영문·숫자·특수문자를 모두 넣어 8~13자로 입력해 주세요")


class WithdrawIn(BaseModel):
    password: str | None = None      # 비밀번호 계정
    confirm: str | None = None       # 간편 가입 계정은 '탈퇴'를 입력


@router.get("/me/profile")
def profile(candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    c = db.execute("""SELECT email, name, phone, password_hash IS NOT NULL AS has_password, created_at,
                             (SELECT max(p.final_announce_at) FROM application a JOIN job_posting p ON p.id = a.posting_id
                              WHERE a.candidate_id = %s AND a.status IN ('submitted', 'doc_passed', 'stage2', 'stage2_done')
                                AND p.final_announce_at > now()) AS rejoin_block_if_withdraw
                      FROM candidate WHERE id = %s""", (candidate_id, candidate_id)).fetchone()
    social = [r["provider"] for r in db.execute("SELECT provider FROM candidate_social_account WHERE candidate_id = %s ORDER BY provider",
                                                (candidate_id,)).fetchall()]
    return {**c, "social": social}


@router.put("/me/profile")
def update_profile(body: ProfileIn, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """이름·휴대폰 번호 수정. 이미 낸 지원서의 인적사항은 제출 당시 그대로 둔다 (접수 중이면 지원서 수정에서 다시 저장)"""
    db.execute("UPDATE candidate SET name = %s, phone = %s WHERE id = %s", (body.name, body.phone, candidate_id))
    return {"ok": True}


@router.put("/me/password")
def change_password(body: PasswordIn, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    row = db.execute("SELECT password_hash FROM candidate WHERE id = %s", (candidate_id,)).fetchone()
    if not _password_ok(body.current, row["password_hash"]):
        raise HTTPException(400, "지금 비밀번호가 맞지 않습니다")
    db.execute("UPDATE candidate SET password_hash = %s WHERE id = %s",
               (bcrypt.hashpw(body.new.encode(), bcrypt.gensalt()).decode(), candidate_id))
    return {"ok": True}


@router.post("/me/withdraw")
def withdraw(body: WithdrawIn, resp: Response, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """회원 탈퇴: 로그인 막기 + 진행 중인 지원서는 지원 취소 + 간편 로그인 연결 끊기. 면접 응시 중에는 거부.
    재가입 제한: 진행 중이던 지원이 있으면 그 공고들의 최종 발표일까지 (같은 공고 중복 지원 방지). 없으면 바로 재가입 가능.
    개인정보는 1년 보관 (파기 작업은 공통 기반 파트 정책). 지금은 기록을 남기고 상태만 바꾼다"""
    c = db.execute("SELECT password_hash FROM candidate WHERE id = %s", (candidate_id,)).fetchone()
    ok = _password_ok(body.password or "", c["password_hash"]) if c["password_hash"] else (body.confirm or "").strip() == "탈퇴"
    if not ok:
        raise HTTPException(400, "비밀번호가 맞지 않습니다" if c["password_hash"] else "'탈퇴'를 정확히 입력해 주세요")
    if db.execute("""SELECT 1 FROM interview_session s JOIN application a ON a.id = s.application_id
                     WHERE a.candidate_id = %s AND s.status = 'in_progress'""", (candidate_id,)).fetchone():
        raise HTTPException(409, "면접 응시 중에는 탈퇴할 수 없습니다")
    with db.transaction():
        db.execute("""UPDATE candidate SET status = 'withdrawn', withdrawn_at = now(), password_hash = NULL,
                          rejoin_blocked_until = (SELECT max(p.final_announce_at) FROM application a JOIN job_posting p ON p.id = a.posting_id
                                                  WHERE a.candidate_id = %s AND a.status IN ('submitted', 'doc_passed', 'stage2', 'stage2_done')
                                                    AND p.final_announce_at > now())
                      WHERE id = %s""", (candidate_id, candidate_id))
        from api import stage
        for r in db.execute("""SELECT id FROM application WHERE candidate_id = %s
                               AND status IN ('submitted', 'doc_passed', 'stage2', 'stage2_done')""", (candidate_id,)).fetchall():
            stage.ensure(db, r["id"])                  # 공통 상태를 바꾸기 전에 상세 단계를 고정
        gone = db.execute("""UPDATE application SET status = 'withdrawn'
                             WHERE candidate_id = %s AND status IN ('submitted', 'doc_passed', 'stage2', 'stage2_done') RETURNING id""",
                          (candidate_id,)).fetchall()
        for r in gone:                                 # 상세 단계: 지원 취소 (공통 상태가 이미 withdrawn이라 행이 없으면 바로 맞음)
            stage.move(db, r["id"], "withdrawn", "candidate", candidate_id, "회원 탈퇴")
        db.execute("DELETE FROM candidate_social_account WHERE candidate_id = %s", (candidate_id,))
    resp.delete_cookie(COOKIE)
    return {"withdrawn": True}
