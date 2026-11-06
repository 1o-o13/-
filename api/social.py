"""※ 임시 간편 가입·로그인 (네이버·구글·카카오, OAuth 2.0 인가 코드 방식). 공통 기반 파트가 정식 구현하면 교체한다.

흐름: /start → 제공사 로그인 → /callback → 이미 연결된 계정이면 로그인 / 처음이면 /signup/social에서 휴대폰 번호를 받아 가입
- 앱 키는 .env에만 (NAVER_CLIENT_ID·SECRET, GOOGLE_CLIENT_ID·SECRET, KAKAO_CLIENT_ID·SECRET). 비어 있으면 그 제공사 버튼은 꺼진다
- state 값을 HttpOnly 쿠키에 두고 돌아올 때 대조한다 (CSRF)
- 같은 이메일로 이미 가입한 계정이 있으면 자동으로 합치지 않는다 (남의 계정에 붙는 것을 막음)
"""
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator

from api.auth import NAME_EN, NAME_KO, PHONE, _issue, rejoin
from api.db import get_db

router = APIRouter(prefix="/api/auth/social")
STATE_COOKIE = "social_state"
PENDING_COOKIE = "social_signup"
PENDING_SEC = 15 * 60          # 임시: 간편 가입 마무리까지 15분

PROVIDERS = {
    "naver": {"auth": "https://nid.naver.com/oauth2.0/authorize", "token": "https://nid.naver.com/oauth2.0/token",
              "me": "https://openapi.naver.com/v1/nid/me", "scope": ""},
    "google": {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
               "me": "https://openidconnect.googleapis.com/v1/userinfo", "scope": "openid email profile"},
    "kakao": {"auth": "https://kauth.kakao.com/oauth/authorize", "token": "https://kauth.kakao.com/oauth/token",
              "me": "https://kapi.kakao.com/v2/user/me", "scope": ""},
}


def _keys(p: str) -> tuple[str, str]:
    return os.environ.get(f"{p.upper()}_CLIENT_ID", "").strip(), os.environ.get(f"{p.upper()}_CLIENT_SECRET", "").strip()


def _ready(p: str) -> bool:
    cid, secret = _keys(p)
    return bool(cid) and (bool(secret) or p == "kakao")      # 카카오는 Client Secret을 켜지 않았으면 없어도 됨


def _redirect_uri(p: str) -> str:
    return f"{os.environ.get('PUBLIC_URL', 'http://localhost:3000').rstrip('/')}/api/auth/social/{p}/callback"


def _token(p: str, code: str, state: str) -> str:
    cid, secret = _keys(p)
    data = {"grant_type": "authorization_code", "client_id": cid, "code": code, "redirect_uri": _redirect_uri(p), "state": state}
    if secret:
        data["client_secret"] = secret
    r = httpx.post(PROVIDERS[p]["token"], data=data, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _profile(p: str, access_token: str) -> dict:
    """제공사 사용자 정보 → {id, email, name}"""
    r = httpx.get(PROVIDERS[p]["me"], headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
    r.raise_for_status()
    d = r.json()
    if p == "naver":
        d = d["response"]
        return {"id": d["id"], "email": d.get("email"), "name": d.get("name") or d.get("nickname"), "phone": d.get("mobile")}
    if p == "google":
        return {"id": d["sub"], "email": d.get("email"), "name": d.get("name"), "phone": None}
    acc = d.get("kakao_account", {})
    return {"id": str(d["id"]), "email": acc.get("email"), "name": acc.get("name") or acc.get("profile", {}).get("nickname"),
            "phone": None}


def _provider(p: str) -> str:
    if p not in PROVIDERS:
        raise HTTPException(404)
    return p


@router.get("/providers")
def providers():
    """화면 버튼용: 앱 키가 들어 있는 제공사만 true"""
    return {p: _ready(p) for p in PROVIDERS}


@router.get("/{p}/start")
def start(p: str = Depends(_provider), reprompt: bool = False):
    """reprompt: 이메일 제공을 빼고 동의했던 사용자에게 동의 화면을 다시 띄운다 (네이버 auth_type=reprompt, 카카오·구글 prompt)"""
    if not _ready(p):
        return RedirectResponse("/login?social_error=not_ready", 302)
    state = secrets.token_urlsafe(24)
    q = {"response_type": "code", "client_id": _keys(p)[0], "redirect_uri": _redirect_uri(p), "state": state}
    if PROVIDERS[p]["scope"]:
        q["scope"] = PROVIDERS[p]["scope"]
    if reprompt:
        q.update({"naver": {"auth_type": "reprompt"}, "kakao": {"prompt": "consent"}, "google": {"prompt": "consent"}}[p])
    resp = RedirectResponse(f"{PROVIDERS[p]['auth']}?{urlencode(q)}", 302)
    resp.set_cookie(STATE_COOKIE, f"{p}:{state}", max_age=600, httponly=True, samesite="lax")
    return resp


@router.get("/{p}/callback")
def callback(p: str = Depends(_provider), code: str | None = None, state: str | None = None,
             social_state: str | None = Cookie(default=None), db=Depends(get_db, scope="function")):
    if not code or not state or social_state != f"{p}:{state}":
        return RedirectResponse("/login?social_error=state", 302)       # 취소했거나 위조된 요청
    try:
        prof = _profile(p, _token(p, code, state))
    except Exception:
        return RedirectResponse("/login?social_error=provider", 302)
    row = db.execute("""SELECT c.id FROM candidate_social_account s JOIN candidate c ON c.id = s.candidate_id
                        WHERE s.provider = %s AND s.provider_user_id = %s AND c.status = 'active'""", (p, prof["id"])).fetchone()
    if row:                                                              # 이미 연결된 계정 → 로그인
        resp = RedirectResponse("/", 302)
        _issue(resp, "candidate", row["id"])
    else:
        if not prof["email"]:                                            # 이메일 제공 동의를 뺐음 → 다시 동의받기 안내
            return RedirectResponse(f"/login?social_error=no_email&provider={p}", 302)
        if db.execute("SELECT 1 FROM candidate WHERE email = %s AND status = 'active'",
                                        (prof["email"].lower(),)).fetchone():
            return RedirectResponse("/login?social_error=email_exists", 302)
        if db.execute("SELECT 1 FROM candidate WHERE email = %s AND rejoin_blocked_until > now()",
                                        (prof["email"].lower(),)).fetchone():
            return RedirectResponse("/login?social_error=rejoin_blocked", 302)
        pending = jwt.encode({"typ": "social", "p": p, "pid": prof["id"], "email": prof["email"], "name": prof["name"],
                              "phone": prof["phone"], "exp": int(time.time()) + PENDING_SEC}, os.environ["JWT_SECRET"], algorithm="HS256")
        resp = RedirectResponse("/signup/social", 302)
        resp.set_cookie(PENDING_COOKIE, pending, max_age=PENDING_SEC, httponly=True, samesite="lax")
    resp.delete_cookie(STATE_COOKIE)
    return resp


def _pending(social_signup: str | None = Cookie(default=None)) -> dict:
    try:
        d = jwt.decode(social_signup or "", os.environ["JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "간편 가입 시간이 지났습니다. 다시 시작해 주세요")
    if d.get("typ") != "social":
        raise HTTPException(401, "간편 가입 시간이 지났습니다. 다시 시작해 주세요")
    return d


@router.get("/pending")
def pending(d: dict = Depends(_pending)):
    """가입 마무리 화면: 제공사에서 받은 이름·이메일 (휴대폰 번호는 지원자가 넣는다)"""
    return {"provider": d["p"], "email": d["email"], "name": d["name"], "phone": d["phone"]}


class CompleteIn(BaseModel):
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
        if not PHONE.match(v):
            raise ValueError("휴대폰 번호는 010-1234-5678 형식으로 입력해 주세요")
        return v


@router.post("/complete")
def complete(body: CompleteIn, resp: Response, d: dict = Depends(_pending), db=Depends(get_db, scope="function")):
    """간편 가입 마무리: 지원자 계정(비밀번호 없음) + 소셜 연결을 만들고 로그인"""
    if not d["email"]:
        raise HTTPException(422, "제공사에서 이메일을 받지 못했습니다. 이메일 제공에 동의한 뒤 다시 시작해 주세요")
    ci_hash = "TMP_" + hashlib.sha256(f"{d['p']}:{d['pid']}".encode()).hexdigest()   # 임시: 휴대폰 본인인증(CI) 대신 가짜 값
    try:
        with db.transaction():
            cid = rejoin(db, d["email"].lower(), body.name, body.phone, None)   # 탈퇴했던 계정이면 다시 살린다
            if cid is None:
                cid = db.execute("INSERT INTO candidate(email, name, phone, ci_hash) VALUES (%s, %s, %s, %s) RETURNING id",
                                 (d["email"].lower(), body.name, body.phone, ci_hash)).fetchone()["id"]
            db.execute("INSERT INTO candidate_social_account(candidate_id, provider, provider_user_id) VALUES (%s, %s, %s)",
                       (cid, d["p"], d["pid"]))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "이미 가입한 계정입니다. 로그인해 주세요")
    _issue(resp, "candidate", cid)
    resp.delete_cookie(PENDING_COOKIE)
    return {"id": cid}
