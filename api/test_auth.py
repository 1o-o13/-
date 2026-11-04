"""단계 2 검증: 가입·로그인·로그아웃, 다른 지원자 응시 403, TOTP 틀리면 거부, 관리자 역할별 접근."""
import pyotp
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.auth import ADMIN_COOKIE, ADMIN_WRITE, COOKIE, current_admin, own_application

PW = "Test1234!"
TOTP = "JBSWY3DPEHPK3PXP"   # 시험 전용 비밀값 (seed/test_data.sql)

# 의존성 확인용 시험 전용 앱 (운영 코드에는 이 경로가 없다)
probe = FastAPI()


@probe.get("/app/{app_id}")
def _app(app_id: int = Depends(own_application)):
    return {"app_id": app_id}


@probe.get("/admin-read")
def _read(admin=Depends(current_admin())):
    return admin


@probe.get("/admin-write")
def _write(admin=Depends(current_admin(*ADMIN_WRITE))):
    return admin


def probe_with(client):
    p = TestClient(probe)
    for name in (COOKIE, ADMIN_COOKIE):          # 지원자·관리자 쿠키는 따로 (11/10)
        if client.cookies.get(name):
            p.cookies.set(name, client.cookies.get(name))
    return p


def login(client, email, pw=PW):
    return client.post("/api/auth/login", json={"email": email, "password": pw})


def admin_login(client, login_id, otp=None, pw=PW):
    return client.post("/api/auth/admin/login", json={"login_id": login_id, "password": pw, "otp": otp})


def test_signup_login_logout(client):
    new = {"email": "New.User@naver.com", "password": "Passw0rd!", "name": "새지원자", "phone": "010-1111-2222"}
    assert client.post("/api/auth/signup", json=new).status_code == 201
    assert client.post("/api/auth/signup", json={**new, "email": "new.user@naver.com"}).status_code == 409   # 대소문자만 달라도 중복
    assert client.post("/api/auth/signup", json={**new, "email": "x@gmail.com", "password": "short"}).status_code == 422
    assert login(client, "new.user@naver.com", "wrong-pass").status_code == 401
    r = login(client, "new.user@naver.com", "Passw0rd!")
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/auth/me").json()["type"] == "candidate"
    assert client.get("/api/interview/applications").json() == []     # 새 가입자는 지원서 없음
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_seed_candidate_sees_only_own_application(client):
    assert login(client, "cand01@test.local").status_code == 200
    apps = client.get("/api/interview/applications").json()
    assert len(apps) == 1 and apps[0]["status"] == "stage2"
    assert not any(k in apps[0] for k in ("score", "total_score", "judgement"))


def test_other_candidate_application_403(client):
    login(client, "cand01@test.local")
    app01 = client.get("/api/interview/applications").json()[0]["id"]
    assert probe_with(client).get(f"/app/{app01}").status_code == 200
    login(client, "cand02@test.local")
    p = probe_with(client)
    assert p.get(f"/app/{app01}").status_code == 403
    assert p.get("/app/999999").status_code == 404
    assert p.get("/admin-read").status_code == 401            # 지원자는 관리자 기능 불가 (관리자 로그인이 따로 없음, 11/10)


def test_no_or_bad_cookie_401(client):
    p = TestClient(probe)
    assert p.get("/app/1").status_code == 401
    p.cookies.set(COOKIE, "forged.token.value")
    assert p.get("/app/1").status_code == 401


def test_admin_totp(client):
    otp = pyotp.TOTP(TOTP).now()
    assert admin_login(client, "hr01").status_code == 401                    # OTP 없음
    assert admin_login(client, "hr01", "000000" if otp != "000000" else "111111").status_code == 401   # OTP 틀림
    assert admin_login(client, "hr01", otp, pw="wrong").status_code == 401   # 비밀번호 틀림
    r = admin_login(client, "hr01", otp)
    assert r.status_code == 200 and r.json()["role"] == "recruiter"
    p = probe_with(client)
    assert p.get("/admin-read").status_code == 200
    assert p.get("/admin-write").status_code == 200
    assert p.get("/app/1").status_code == 401                 # 관리자 토큰으로 지원자 기능 불가 (지원자 로그인이 따로 없음, 11/10)


@pytest.mark.parametrize("login_id, can_write", [("admin", True), ("dev01", False)])
def test_admin_roles(client, login_id, can_write):
    otp = pyotp.TOTP(TOTP).now() if login_id != "dev01" else None   # dev01(부서원)은 2단계 인증 없음
    assert admin_login(client, login_id, otp).status_code == 200
    p = probe_with(client)
    assert p.get("/admin-read").status_code == 200
    assert p.get("/admin-write").status_code == (200 if can_write else 403)


def test_pending_admin_and_passwordless_candidate(client, db_url):
    """승인 대기(is_active = false) 관리자는 비밀번호가 맞으면 403 안내, 틀리면 401. 비밀번호 없는 지원자는 로그인 불가"""
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("""INSERT INTO admin_user(login_id, password_hash, name, role, is_active)
                     SELECT 'pending01', password_hash, '대기', 'recruiter', false FROM admin_user WHERE login_id = 'hr01'""")
        c.execute("UPDATE candidate SET password_hash = NULL WHERE email = 'cand50@test.local'")
    r = admin_login(client, "pending01")
    assert r.status_code == 403 and "승인 대기" in r.json()["detail"]
    assert admin_login(client, "pending01", pw="wrong-pass").status_code == 401
    assert login(client, "cand50@test.local").status_code == 401


@pytest.mark.parametrize("field,value", [
    ("name", "김"), ("name", "가" * 18), ("name", "김 하늘"), ("name", "김Haneul"), ("name", "kim1"),
    ("email", "a@test.local"), ("email", "a@example.com"), ("email", "a@gmail.com.evil.com"),
    ("phone", "012345678989"), ("phone", "012-3456-7898"), ("phone", "010-123-4567"), ("phone", "01012345678"),
    ("password", "Test1234"), ("password", "test!!!!"), ("password", "12345678!"), ("password", "Abcdefgh123#$%"),
])
def test_signup_rejects_out_of_format(client, field, value):
    """가입 틀: 이름 한글 2~17자·영문 / 실제 메일 서비스 / 01X-XXXX-XXXX / 영문·숫자·특수문자 8~13자"""
    good = {"email": "fmt.check@gmail.com", "password": "Good123!", "name": "홍길동", "phone": "010-2222-3333"}
    r = client.post("/api/auth/signup", json={**good, field: value})
    assert r.status_code == 422, (field, value)
    assert r.json()["detail"][0]["msg"].startswith("Value error, ")      # 화면이 보여 줄 한국어 안내


def test_signup_accepts_english_name(client):
    r = client.post("/api/auth/signup", json={"email": "john.smith@outlook.com", "password": "Good123!", "name": "John Smith",
                                             "phone": "019-1234-5678"})
    assert r.status_code == 201


def test_admin_signup_approve_reject(client, db_url):
    """관리자 가입 신청 → 승인 대기 → 최고관리자만 승인(채용 담당은 2단계 인증 비밀값 발급)·거절"""
    depts = client.get("/api/auth/departments").json()
    hr_dept = next(d["id"] for d in depts if d["name"] == "인사팀")
    req = {"login_id": "newhr", "password": "Good123!", "name": "새담당", "role": "recruiter", "department_id": hr_dept}
    assert client.post("/api/auth/admin/signup", json={**req, "login_id": "Bad"}).status_code == 422
    assert client.post("/api/auth/admin/signup", json={**req, "role": "super_admin"}).status_code == 422
    assert client.post("/api/auth/admin/signup", json=req).status_code == 201
    assert client.post("/api/auth/admin/signup", json=req).status_code == 409
    assert client.post("/api/auth/admin/signup", json={**req, "login_id": "newdev", "role": "dept_member"}).status_code == 201
    assert admin_login(client, "newhr", pw="Good123!").status_code == 403            # 승인 대기

    admin_login(client, "hr01", pyotp.TOTP(TOTP).now())
    assert client.get("/api/admin/users/pending").status_code == 403                 # 채용 담당은 승인 못 함
    admin_login(client, "admin", pyotp.TOTP(TOTP).now())
    pending = {u["login_id"]: u["id"] for u in client.get("/api/admin/users/pending").json()}
    secret = client.post(f"/api/admin/users/{pending['newhr']}/approve").json()["totp_secret"]
    assert secret and client.post(f"/api/admin/users/{pending['newhr']}/approve").status_code == 409
    assert client.post(f"/api/admin/users/{pending['newdev']}/reject").json() == {"rejected": True}
    assert "newdev" not in [u["login_id"] for u in client.get("/api/admin/users/pending").json()]
    assert admin_login(client, "newhr", "000000", pw="Good123!").status_code == 401   # 승인 뒤에는 2단계 인증 필수
    assert admin_login(client, "newhr", pyotp.TOTP(secret).now(), pw="Good123!").status_code == 200


def test_dev_quick_login_only_when_enabled(client, db_url, monkeypatch):
    """바로 로그인은 DEV_QUICK_LOGIN=1일 때만, 정해 둔 계정만"""
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("UPDATE candidate SET email = 'haneul.kim@naver.com' WHERE email = 'cand01@test.local'")
    try:
        monkeypatch.delenv("DEV_QUICK_LOGIN", raising=False)
        assert client.post("/api/auth/dev/login/cand1").status_code == 404
        monkeypatch.setenv("DEV_QUICK_LOGIN", "1")
        assert client.post("/api/auth/dev/login/nobody").status_code == 404
        assert client.post("/api/auth/dev/login/cand1").json()["type"] == "candidate"
        assert client.get("/api/auth/me").json()["type"] == "candidate"
        assert client.post("/api/auth/dev/login/admin").json()["role"] == "super_admin"
    finally:
        with psycopg.connect(db_url, autocommit=True) as c:
            c.execute("UPDATE candidate SET email = 'cand01@test.local' WHERE email = 'haneul.kim@naver.com'")


def test_social_signup_and_login(client, db_url, monkeypatch):
    """간편 가입: 키 없으면 꺼짐 → 키 있으면 제공사로 이동(state 쿠키) → 돌아오면 처음엔 가입 마무리, 다음엔 바로 로그인"""
    from urllib.parse import parse_qs, urlparse

    from api import social
    client.cookies.clear()
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    assert client.get("/api/auth/social/providers").json()["naver"] is False
    r = client.get("/api/auth/social/naver/start", follow_redirects=False)
    assert r.headers["location"] == "/login?social_error=not_ready"

    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    monkeypatch.setattr(social, "_token", lambda p, code, state: "access")
    monkeypatch.setattr(social, "_profile", lambda p, tok: {"id": "naver-123", "email": "Social.User@naver.com", "name": "간편가입",
                                                             "phone": "010-3333-4444"})
    r = client.get("/api/auth/social/naver/start", follow_redirects=False)
    url = urlparse(r.headers["location"])
    assert url.netloc == "nid.naver.com" and parse_qs(url.query)["client_id"] == ["cid"]
    state = parse_qs(url.query)["state"][0]
    assert client.get("/api/auth/social/naver/callback", params={"code": "c", "state": "forged"},
                      follow_redirects=False).headers["location"] == "/login?social_error=state"    # state가 다르면 거부
    r = client.get("/api/auth/social/naver/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "/signup/social"
    assert client.get("/api/auth/social/pending").json() == {"provider": "naver", "email": "Social.User@naver.com", "name": "간편가입",
                                                             "phone": "010-3333-4444"}
    assert client.post("/api/auth/social/complete", json={"name": "간편가입", "phone": "0101"}).status_code == 422
    assert client.post("/api/auth/social/complete", json={"name": "간편가입", "phone": "010-3333-4444"}).status_code == 200
    assert client.get("/api/auth/me").json()["type"] == "candidate"

    client.cookies.clear()                                                           # 두 번째부터는 바로 로그인
    state = parse_qs(urlparse(client.get("/api/auth/social/naver/start", follow_redirects=False).headers["location"]).query)["state"][0]
    r = client.get("/api/auth/social/naver/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "/" and client.get("/api/auth/me").json()["type"] == "candidate"

    client.cookies.clear()                                                           # 같은 이메일의 다른 계정에는 붙지 않는다
    monkeypatch.setattr(social, "_profile", lambda p, tok: {"id": "naver-999", "email": "cand02@test.local", "name": "x", "phone": None})
    state = parse_qs(urlparse(client.get("/api/auth/social/naver/start", follow_redirects=False).headers["location"]).query)["state"][0]
    r = client.get("/api/auth/social/naver/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "/login?social_error=email_exists"

    client.cookies.clear()                                                           # 이메일 제공을 빼고 동의 → 다시 동의받기
    monkeypatch.setattr(social, "_profile", lambda p, tok: {"id": "naver-777", "email": None, "name": "x", "phone": None})
    state = parse_qs(urlparse(client.get("/api/auth/social/naver/start", follow_redirects=False).headers["location"]).query)["state"][0]
    r = client.get("/api/auth/social/naver/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "/login?social_error=no_email&provider=naver"
    q = parse_qs(urlparse(client.get("/api/auth/social/naver/start?reprompt=1", follow_redirects=False).headers["location"]).query)
    assert q["auth_type"] == ["reprompt"]


def test_naver_api_shapes(monkeypatch):
    """네이버 응답 모양: 토큰 발급(실패도 200 + error), 프로필 /v1/nid/me 의 response 안 id·email·name·mobile"""
    import httpx

    from api import social
    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    sent = {}

    def post(url, data, timeout):
        sent.update(url=url, data=data)
        return httpx.Response(200, json={"error": "invalid_request", "error_description": "no valid data"} if data["code"] == "bad"
                              else {"access_token": "AT", "token_type": "bearer"}, request=httpx.Request("POST", url))

    def get(url, headers, timeout):
        assert url == "https://openapi.naver.com/v1/nid/me" and headers["Authorization"] == "Bearer AT"
        return httpx.Response(200, json={"resultcode": "00", "message": "success", "response": {
            "id": "32742776", "email": "openapi@naver.com", "name": "오픈 API", "mobile": "010-0000-0000", "nickname": "OpenAPI"}},
            request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", get)
    assert social._profile("naver", social._token("naver", "ok", "st")) == {"id": "32742776", "email": "openapi@naver.com",
                                                                           "name": "오픈 API", "phone": "010-0000-0000"}
    assert sent["url"] == "https://nid.naver.com/oauth2.0/token" and sent["data"]["client_secret"] == "secret"
    assert sent["data"]["grant_type"] == "authorization_code" and sent["data"]["state"] == "st"
    with pytest.raises(KeyError):                                                    # 실패 응답 → callback이 provider 오류로 안내
        social._token("naver", "bad", "st")


def test_profile_password_withdraw(client, db_url):
    """내 정보 수정·비밀번호 변경·회원 탈퇴 (탈퇴하면 로그인·남은 쿠키 모두 막히고 지원서는 지원 취소)"""
    import psycopg
    client.cookies.clear()
    acc = {"email": "me.page@naver.com", "password": "First123!", "name": "내정보", "phone": "010-7777-8888"}
    client.post("/api/auth/signup", json=acc)
    login(client, acc["email"], acc["password"])
    p = client.get("/api/auth/me/profile").json()
    assert (p["email"], p["name"], p["has_password"], p["social"]) == ("me.page@naver.com", "내정보", True, [])
    assert client.put("/api/auth/me/profile", json={"name": "김", "phone": "010-7777-8888"}).status_code == 422
    assert client.put("/api/auth/me/profile", json={"name": "바뀐이름", "phone": "010-1212-3434"}).status_code == 200
    assert client.get("/api/auth/me/profile").json()["phone"] == "010-1212-3434"
    assert client.put("/api/auth/me/password", json={"current": "wrong", "new": "Second123!"}).status_code == 400
    assert client.put("/api/auth/me/password", json={"current": "First123!", "new": "short"}).status_code == 422
    assert client.put("/api/auth/me/password", json={"current": "First123!", "new": "Second123!"}).status_code == 200
    token = client.cookies.get(COOKIE)
    assert client.post("/api/auth/me/withdraw", json={"password": "First123!"}).status_code == 400   # 바뀐 비밀번호로만
    assert client.post("/api/auth/me/withdraw", json={"password": "Second123!"}).json() == {"withdrawn": True}
    assert login(client, acc["email"], "Second123!").status_code == 401                              # 로그인 막힘
    client.cookies.set(COOKIE, token)
    assert client.get("/api/interview/applications").status_code == 401                              # 남은 쿠키도 막힘
    # 진행 중인 지원이 없었으니 바로 같은 이메일로 다시 가입 → 예전 계정이 다시 살아난다
    r = client.post("/api/auth/signup", json={**acc, "password": "Third123!", "name": "다시가입"})
    assert r.status_code == 201
    assert login(client, acc["email"], "Third123!").status_code == 200
    assert client.get("/api/auth/me/profile").json()["name"] == "다시가입"


def test_withdraw_cancels_applications_but_not_during_interview(client, db_url):
    import psycopg
    client.cookies.clear()
    with psycopg.connect(db_url, autocommit=True) as c:      # 다시 가입할 때 이메일 틀(실제 메일 서비스)에 맞도록
        c.execute("UPDATE candidate SET email = 'cand19.re@naver.com' WHERE email = 'cand19@test.local'")
    login(client, "cand19.re@naver.com")
    with psycopg.connect(db_url, autocommit=True) as c:
        app_id = c.execute("SELECT a.id FROM application a JOIN candidate c ON c.id = a.candidate_id WHERE c.email = 'cand19.re@naver.com'").fetchone()[0]
        c.execute("""INSERT INTO interview_session(application_id, exam_code, status, llm_provider, llm_eval_model, llm_fast_model, llm_local_model)
                     VALUES (%s, 'IV-WD-1', 'in_progress', 'ollama', 'qwen3:4b', 'qwen3:1.7b', 'qwen3:4b')""", (app_id,))
    assert client.post("/api/auth/me/withdraw", json={"password": PW}).status_code == 409          # 면접 중
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("UPDATE interview_session SET status = 'abandoned', end_reason = 'tab_leave', ended_at = now() WHERE exam_code = 'IV-WD-1'")
    final = client.get("/api/auth/me/profile").json()["rejoin_block_if_withdraw"]
    assert final is not None                                                   # 진행 중인 공고의 최종 발표일까지 막힐 예정
    assert client.post("/api/auth/me/withdraw", json={"password": PW}).status_code == 200
    with psycopg.connect(db_url, autocommit=True) as c:
        assert c.execute("SELECT status FROM application WHERE id = %s", (app_id,)).fetchone()[0] == "withdrawn"
        until = c.execute("SELECT rejoin_blocked_until, (SELECT final_announce_at FROM job_posting WHERE title = '2026 하반기 백엔드 신입')"
                          " FROM candidate WHERE email = 'cand19.re@naver.com'").fetchone()
    assert until[0] == until[1]                                                # 그 공고 최종 발표일까지
    r = client.post("/api/auth/signup", json={"email": "cand19.re@naver.com", "password": "Good123!", "name": "재가입", "phone": "010-1111-9999"})
    assert r.status_code == 409 and "이후에 다시 가입할 수 있습니다" in r.json()["detail"]
    with psycopg.connect(db_url, autocommit=True) as c:                        # 공고가 끝나면 다시 가입 가능
        c.execute("UPDATE candidate SET rejoin_blocked_until = now() - interval '1 minute' WHERE email = 'cand19.re@naver.com'")
    assert client.post("/api/auth/signup", json={"email": "cand19.re@naver.com", "password": "Good123!", "name": "재가입",
                                                 "phone": "010-1111-9999"}).status_code == 201


def test_candidate_login_one_hour_and_slides(client, monkeypatch):
    """지원자 로그인은 1시간, 쓰는 동안 자동 연장. 관리자는 4시간"""
    import time as _t

    import jwt as _jwt

    from api import auth
    client.cookies.clear()
    r = login(client, "cand20@test.local")
    exp = _jwt.decode(client.cookies.get(COOKIE), options={"verify_signature": False})["exp"]
    assert 3590 <= exp - _t.time() <= 3600 and "max-age=3600" in r.headers["set-cookie"].lower()
    assert abs(client.get("/api/auth/me").json()["exp"] - exp) <= 1
    real = _t.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + 600)                      # 10분 뒤 요청 → 다시 1시간
    client.get("/api/interview/applications")
    assert _jwt.decode(client.cookies.get(COOKIE), options={"verify_signature": False})["exp"] > exp + 500
    monkeypatch.setattr(auth.time, "time", real)
    client.cookies.clear()
    admin_login(client, "hr01", pyotp.TOTP(TOTP).now())
    aexp = _jwt.decode(client.cookies.get(ADMIN_COOKIE), options={"verify_signature": False})["exp"]
    assert 4 * 3600 - 10 <= aexp - _t.time() <= 4 * 3600


def test_candidate_and_admin_logged_in_together(client):
    """한 브라우저에서 지원자·관리자 동시 로그인 (쿠키가 따로, 11/10). 로그아웃도 한쪽만"""
    client.cookies.clear()
    assert login(client, "cand22@test.local").status_code == 200
    assert admin_login(client, "hr01", pyotp.TOTP(TOTP).now()).status_code == 200
    assert client.get("/api/auth/me?as=candidate").json()["type"] == "candidate"
    assert client.get("/api/auth/me?as=admin").json()["role"] == "recruiter"
    assert client.get("/api/interview/applications").status_code == 200                  # 지원자 API
    assert client.get("/api/admin/postings").status_code == 200                          # 관리자 API
    client.post("/api/auth/logout?as=admin")
    assert client.get("/api/auth/me?as=admin").status_code == 401
    assert client.get("/api/auth/me?as=candidate").status_code == 200                     # 지원자 로그인은 그대로
    client.cookies.set(ADMIN_COOKIE, client.cookies.get(COOKIE))                          # 지원자 토큰을 관리자 쿠키에 넣어도
    assert client.get("/api/admin/postings").status_code == 401                          # 관리자로 통하지 않음
