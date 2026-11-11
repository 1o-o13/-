"""채용 요청·공고 관리 (ADM-020~024): 부서 요청 → 공고 작성 → 부서 확인(수정 요청·승인) → 게시 → 채용 홈 → 마감, 바로 만든 공고, 삭제"""
from datetime import datetime, timedelta, timezone

import psycopg
import pyotp

PW, TOTP = "Test1234!", "JBSWY3DPEHPK3PXP"


def login(client, who):
    client.cookies.clear()
    body = {"login_id": who, "password": PW} | ({"otp": pyotp.TOTP(TOTP).now()} if who != "dev01" else {})
    assert client.post("/api/auth/admin/login", json=body).status_code == 200


T0 = datetime.now(timezone.utc).replace(microsecond=0)


def body(**kw):
    t = T0
    d = lambda n: (t + timedelta(days=n)).isoformat()   # noqa: E731
    return {"title": "2027 상반기 프론트엔드 신입", "job_role": "프론트엔드", "job_category": "dev", "career_level": "new", "headcount": 3,
            "description": "우대: React·TypeScript, 웹 성능 측정, 접근성. 협업 도구(Git) 사용 경험.",
            "apply_start": d(-1), "apply_end": d(5), "doc_announce_at": d(7), "stage2_start": d(8), "stage2_end": d(12),
            "final_announce_at": d(14), "languages": ["python"], "coding_minutes": 60} | kw


def test_request_to_published_posting(client, db_url):
    made = []
    try:
        login(client, "dev01")                                                       # 부서원: 채용 요청
        r = client.post("/api/admin/hiring-requests", json={"title": "프론트엔드 신입 3명", "job_role": "프론트엔드", "headcount": 3,
                                                           "career_level": "new", "reason": "신규 웹 서비스"})
        assert r.status_code == 201
        rid = r.json()["id"]
        assert client.post("/api/admin/postings", json=body(hiring_request_id=rid)).status_code == 403   # 부서원은 공고를 못 만듦

        login(client, "hr01")
        assert any(x["id"] == rid and x["status"] == "submitted" for x in client.get("/api/admin/hiring-requests").json())
        bad = body(hiring_request_id=rid, doc_announce_at=body()["apply_start"])
        r = client.post("/api/admin/postings", json=bad)
        assert r.status_code == 422 and "일정 순서" in r.json()["detail"]                  # DB 규칙: 일정 순서
        r = client.post("/api/admin/postings", json=body(hiring_request_id=rid))
        assert r.status_code == 201
        pid = r.json()["id"]
        made.append(pid)
        assert client.post("/api/admin/postings", json=body(hiring_request_id=rid)).status_code == 409   # 요청 1건 → 공고 1건
        d = client.get(f"/api/admin/postings/{pid}").json()
        assert d["posting"]["status"] == "draft" and d["coding"] == {"languages": ["python"], "time_limit_min": 60}
        assert d["assignees"] == [{"id": d["posting"]["created_by"], "name": "채용담당 김인사", "role": "main"}]
        assert client.get(f"/api/admin/postings/{pid}/interview-setting").json()["total_questions"] == 10   # 면접 설정도 함께
        assert client.post(f"/api/admin/postings/{pid}/publish").status_code == 409            # 부서 확인 전에는 게시 못 함
        assert client.post(f"/api/admin/postings/{pid}/submit-review").json() == {"status": "dept_review"}
        assert client.post(f"/api/admin/postings/{pid}/review", json={"decision": "approved"}).status_code == 403   # 요청 부서만

        login(client, "dev01")
        assert client.post(f"/api/admin/postings/{pid}/review", json={"decision": "changes_requested"}).status_code == 422
        assert client.post(f"/api/admin/postings/{pid}/review", json={"decision": "changes_requested", "comment": "인원 4명으로"}).status_code == 200

        login(client, "hr01")
        assert client.get(f"/api/admin/postings/{pid}").json()["posting"]["status"] == "draft"   # 수정 요청 → 작성 중
        assert client.put(f"/api/admin/postings/{pid}", json=body(headcount=4)).json()["changed"] == ["headcount"]
        client.post(f"/api/admin/postings/{pid}/submit-review")
        login(client, "dev01")
        client.post(f"/api/admin/postings/{pid}/review", json={"decision": "approved"})
        login(client, "hr01")
        assert client.post(f"/api/admin/postings/{pid}/publish").json() == {"status": "published"}
        d = client.get(f"/api/admin/postings/{pid}").json()
        assert [h["change"]["action"] for h in d["history"]] == ["작성", "부서 확인 요청", "수정", "부서 확인 요청", "게시"]
        assert d["history"][2]["change"]["fields"]["headcount"] == ["3", "4"]
        assert [x["decision"] for x in d["reviews"]] == ["changes_requested", "approved"]
        home = {x["id"]: x for x in client.get("/api/site/postings").json()}
        assert home[pid]["phase"] == "accepting" and home[pid]["headcount"] == 4            # 채용 홈에 보이고 접수 중
        assert client.delete(f"/api/admin/postings/{pid}").status_code == 409               # 게시한 공고는 못 지움
        assert client.post(f"/api/admin/postings/{pid}/close").json() == {"status": "closed"}
        assert client.put(f"/api/admin/postings/{pid}", json=body(headcount=5)).status_code == 409   # 마감 뒤에는 못 고침

        r = client.post("/api/admin/postings", json=body(title="데이터 엔지니어 경력", job_role="데이터", job_category="non_dev",
                                                         career_level="junior"))
        direct = r.json()["id"]                                                      # 부서 요청 없이 바로 → 확인 없이 게시
        made.append(direct)
        assert client.get(f"/api/admin/postings/{direct}").json()["coding"] is None    # 비개발 직군은 코딩 테스트 없음
        assert client.post(f"/api/admin/postings/{direct}/submit-review").status_code == 409
        assert client.post(f"/api/admin/postings/{direct}/publish").json() == {"status": "published"}
        r = client.post("/api/admin/postings", json=body(title="지울 공고", job_role="AI"))
        assert client.delete(f"/api/admin/postings/{r.json()['id']}").json() == {"deleted": r.json()["id"]}
        assert client.post("/api/admin/postings", json=body(job_role="마케팅")).status_code == 422   # 회사 문서·질문 은행 있는 직무만
        assert {x["id"] for x in client.get("/api/admin/postings/all").json()} >= {pid, direct}
    finally:
        with psycopg.connect(db_url, autocommit=True) as c:                          # 다른 시험에 안 남게
            for pid in made:
                for t in ("interview_setting", "coding_setting", "document_criteria"):
                    c.execute(f"DELETE FROM {t} WHERE posting_id = %s", (pid,))
                c.execute("DELETE FROM job_posting WHERE id = %s", (pid,))
            c.execute("DELETE FROM hiring_request WHERE title = '프론트엔드 신입 3명'")
