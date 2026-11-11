"""1차 서류 결정·발표·알림, 지원서 임시저장, 최종 결정 취소"""
import psycopg
import pyotp

PW, TOTP = "Test1234!", "JBSWY3DPEHPK3PXP"


def as_admin(client):
    client.cookies.clear()
    assert client.post("/api/auth/admin/login", json={"login_id": "hr01", "password": PW, "otp": pyotp.TOTP(TOTP).now()}).status_code == 200


def as_cand(client, email):
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 200


def test_document_decide_announce_notify(client, db_url):
    from scripts import seed_doc_review
    assert seed_doc_review.main(db_url) == 30
    with psycopg.connect(db_url) as c:
        pid = c.execute("SELECT id FROM job_posting WHERE title = %s", (seed_doc_review.TITLE,)).fetchone()[0]
    as_cand(client, "cand51@test.local")
    assert client.get("/api/me/notifications").json() == []                  # 발표 전에는 알림 없음
    assert client.get(f"/api/me/results/{pid}/document").status_code == 404

    as_admin(client)
    b = client.get(f"/api/admin/postings/{pid}/document").json()
    rows = b["rows"]
    assert len(rows) == 30 and b["announcement"] is None
    assert sorted(r["seq"] for r in rows) == list(range(1, 31))                   # 지원 번호는 공고마다 1부터 (전체 id 51~80이 아님)
    assert all("fit_score" not in r and r["ai"] == {"screened": False} for r in rows)
    assert b["criteria"] and all(c["kind"] == "우대" for c in b["criteria"])        # 평가 기준: 공고 설명에서 채움, 모두 우대
    assert client.put(f"/api/admin/postings/{pid}/document/criteria",
                      json={"items": ["Python 또는 Java로 REST API 개발", "SQL·인덱스", "Redis·Celery", "Docker", "성능 측정 경험"]}).status_code == 200
    first = rows[0]["id"]
    url = f"/api/admin/applications/{first}/document"
    assert client.post(url, json={"decision": "pass"}).status_code == 409           # AI 1차 검토(S0) 전에는 결정 대기 단계가 아님
    assert client.post(f"/api/admin/postings/{pid}/document/screen").json() == {"queued": 30}
    assert client.put(f"/api/admin/postings/{pid}/document/criteria", json={"items": ["X"]}).status_code == 409   # 검토 뒤에는 기준을 못 바꿈
    rows = client.get(f"/api/admin/postings/{pid}/document").json()["rows"]
    assert all(r["ai"]["screened"] and r["ai"]["verify"] for r in rows)
    order = {"추천": 0, None: 1, "비추천": 2}
    keys = [order[r["ai"]["conclusion"]] for r in rows]
    assert keys == sorted(keys)                                                     # AI 추천 순 정렬 (1차 점수 없음)
    assert {r["ai"]["conclusion"] for r in rows} <= {"추천", "비추천", None}           # 보류 없음 (11/12)
    assert 0 < sum(r["ai"]["conclusion"] == "추천" for r in rows) <= 9                 # 추천은 지원자 30명의 30%까지 (11/12)
    no = next(r["id"] for r in rows if r["ai"]["conclusion"] == "비추천")
    assert client.post(f"/api/admin/applications/{no}/document", json={"decision": "pass"}).status_code == 409   # 합격은 추천 안에서만
    assert all(r["ai"]["detail"]["labels"] for r in rows)                        # 항목별 라벨은 '상세'에 (하드 필터 없음, 11/12)
    assert all(r["stage_label"] == "서류 접수" for r in rows)                      # 상세 단계 (자동 탈락 없음)
    first = rows[0]["id"]
    url = f"/api/admin/applications/{first}/document"
    assert client.post(url, json={"decision": "pass"}).status_code == 200            # 합격으로 고름
    assert client.post(url, json={"decision": "hold"}).status_code == 200            # 다시 누르면 해제
    got = next(r for r in client.get(f"/api/admin/postings/{pid}/document").json()["rows"] if r["id"] == first)
    assert got["decision"] is None and [h["decision"] for h in got["history"]] == ["pass", "hold"]   # 기록은 쌓기만
    r = client.post(f"/api/admin/postings/{pid}/document/announce")
    assert r.status_code == 409 and "고른 지원자가 없습니다" in r.json()["detail"]
    rec = [x for x in rows if x["ai"]["conclusion"] == "추천"]
    pick = {x["id"]: "pass" if x in rec[:-1] else None for x in rows}               # 추천 중 마지막 한 명은 고르지 않음
    ids = [i for i, v in pick.items() if v]
    ann = f"/api/admin/postings/{pid}/document/announce"
    off = rec[-1]["id"]                                                              # 추천이지만 체크를 뺀 사람
    assert client.post(f"/api/admin/applications/{off}/document", json={"decision": "pass"}).status_code == 200   # 전에 골랐다가 체크를 뺀 사람
    assert client.post(ann, json={"pass_ids": []}).status_code == 409                 # 체크한 사람 없음
    r = client.post(ann, json={"pass_ids": ids}).json()                              # 체크박스 + '결정 확인' 한 번: 나머지는 모두 불합격
    hist = next(x for x in client.get(f"/api/admin/postings/{pid}/document").json()["rows"] if x["id"] == off)
    assert hist["decision"] == "reject" and [h["decision"] for h in hist["history"]] == ["pass", "hold", "reject"]   # 확정 때 불합격 기록
    passed = sum(v == "pass" for v in pick.values())
    assert passed and r == {"announced": 30, "passed": passed, "notifications": 60}        # 메일 + 문자
    assert client.post(url, json={"decision": "pass"}).status_code == 409       # 발표 뒤에는 고르기를 못 바꿈
    assert client.post(f"/api/admin/postings/{pid}/document/announce").status_code == 409
    with psycopg.connect(db_url) as c:
        st = dict(c.execute("""SELECT a.id, vs.stage FROM application a JOIN v_application_stage vs ON vs.application_id = a.id
                               WHERE a.posting_id = %s""", (pid,)).fetchall())
    assert all(st[i] == ("scheduled" if v == "pass" else "screen_rejected") for i, v in pick.items())   # 상세 단계 11종
    after = client.get(f"/api/admin/postings/{pid}/document").json()["rows"]
    assert all(len(x["notified"]) == 2 for x in after)
    from api.graph import main as main_graph
    top_id = next(i for i, v in pick.items() if v == "pass")
    revoke = f"/api/admin/applications/{top_id}/document/revoke"
    assert main_graph.waiting(top_id) == "wait_access"                         # 메인 그래프: 응시 안내 발송 뒤 지원자 접속 대기
    with psycopg.connect(db_url) as c:
        h = c.execute("""SELECT handoff FROM document_evaluation WHERE application_id = %s ORDER BY version_no DESC LIMIT 1""",
                      (top_id,)).fetchone()[0]
    assert "check_list" in h and h["deficit_value"]                            # 합격자만 handoff (면접 확인 필요 목록 + 결핍 가치)
    with psycopg.connect(db_url) as c:
        slots = [r[0] for r in c.execute("SELECT slot FROM prepared_question WHERE application_id = %s AND status = 'ready' ORDER BY slot",
                                          (top_id,)).fetchall()]
    assert slots[:2] == [1, 2] and any(x >= 4 for x in slots)                   # 1차 합격 즉시 2차 질문을 미리 만들고 검증
    assert h["deficit_evidence"]["후보"] and h["deficit_value"] in h["deficit_evidence"]["후보"]   # 결핍 가치: z 낮은 두 가치 중 원문 근거 확인
    rows = [{**x, "email": x["email"]} for x in rows]

    with psycopg.connect(db_url) as c:
        st = dict(c.execute("""SELECT c.email, a.status FROM application a JOIN candidate c ON c.id = a.candidate_id
                               WHERE a.posting_id = %s""", (pid,)).fetchall())
    top = next(x for x in rows if pick[x["id"]] == "pass")["email"]
    low = next(x for x in rows if not pick[x["id"]])["email"]
    assert st[top] == "stage2" and st[low] == "doc_failed"
    as_cand(client, top)
    n = client.get("/api/me/notifications").json()
    assert [(x["posting_id"], x["label"]) for x in n] == [(pid, "1차 서류 전형 결과 발표")]
    res = client.get(f"/api/me/results/{pid}/document").json()
    assert res["passed"] is True and res["stage2_start"] and res["stage2_end"]
    as_cand(client, low)
    assert client.get(f"/api/me/results/{pid}/document").json()["passed"] is False
    # 발표 뒤 합격 취소: 부정행위 발견 때만, 사유 필수, 결정자·시각 기록 (11/10)
    as_admin(client)
    assert client.post(revoke, json={"reason": ""}).status_code == 422
    assert client.post(revoke, json={"reason": "지원서 사진과 면접 응시자가 다름"}).json() == {"revoked": True}
    with psycopg.connect(db_url) as c:
        st, status = c.execute("""SELECT vs.stage, a.status FROM application a JOIN v_application_stage vs ON vs.application_id = a.id
                                  WHERE a.id = %s""", (top_id,)).fetchone()
        log = c.execute("""SELECT actor_type, actor_id, reason FROM application_stage_log WHERE application_id = %s
                           ORDER BY id DESC LIMIT 1""", (top_id,)).fetchone()
    assert (st, status) == ("screen_rejected", "doc_failed") and log[0] == "admin" and log[1] and "다름" in log[2]
    assert client.post(revoke, json={"reason": "다시 취소해 봄"}).status_code == 409


def test_draft_save_load_and_drop_on_submit(client, db_url):
    with psycopg.connect(db_url, autocommit=True) as c:
        pid = c.execute("""INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, status, published_at,
                               apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
                           SELECT '임시저장 시험 공고', '백엔드', 'dev', 'new', 1, 'published', now(), now() - interval '1 day',
                                  now() + interval '5 day', now() + interval '6 day', now() + interval '7 day', now() + interval '9 day',
                                  now() + interval '10 day', id FROM admin_user WHERE login_id = 'hr01' RETURNING id""").fetchone()[0]
    client.cookies.clear()
    client.post("/api/auth/signup", json={"email": "draft.test@gmail.com", "password": "Good123!", "name": "임시저장", "phone": "010-7777-8888"})
    client.post("/api/auth/login", json={"email": "draft.test@gmail.com", "password": "Good123!"})
    assert client.get(f"/api/site/postings/{pid}/draft").status_code == 404
    form = {"f": {"role": "백엔드", "intro": ""}, "tables": {}, "essays": {"지원동기": "쓰는 중"}}
    assert client.put(f"/api/site/postings/{pid}/draft", json=form).status_code == 200      # 필수 칸이 비어도 저장
    form["essays"]["지원동기"] = "조금 더 씀"
    assert client.put(f"/api/site/postings/{pid}/draft", json=form).status_code == 200      # 공고마다 한 건 (덮어씀)
    assert client.get(f"/api/site/postings/{pid}/draft").json()["form"] == form
    from api.site import ESSAYS
    body = {"지원직무": "백엔드", "소개": ["안녕하세요"], "학력사항": [{"학교": "가람대학교"}],
            "자기소개서": {k: "답" for k, _ in ESSAYS}, "생년월일": "1800-01-01", "외부AI동의": True}
    r = client.post(f"/api/site/postings/{pid}/apply", json=body)
    assert r.status_code == 422 and "생년월일" in r.text                                    # 화면 선택 범위 밖 날짜
    assert client.post(f"/api/site/postings/{pid}/apply", json={**body, "생년월일": "2000-02-29"}).status_code == 201
    assert client.get(f"/api/site/postings/{pid}/draft").status_code == 404               # 제출하면 임시저장은 지움
    assert client.put(f"/api/site/postings/{pid}/draft", json=form).status_code == 409


def test_cancel_final_decision(client, db_url):
    """최종 결정은 같은 버튼을 다시 누르면 취소 → 2차 완료로 되돌림"""
    with psycopg.connect(db_url, autocommit=True) as c:
        app_id, before = c.execute("""SELECT a.id, a.status FROM application a JOIN candidate c ON c.id = a.candidate_id
                                      WHERE c.email = 'cand05@test.local'""").fetchone()
        c.execute("UPDATE application SET status = 'final_failed' WHERE id = %s", (app_id,))
        c.execute("""INSERT INTO stage_result(application_id, stage, result, decided_by)
                     SELECT %s, 'final', 'fail', id FROM admin_user WHERE login_id = 'hr01'""", (app_id,))
    as_admin(client)
    assert client.delete(f"/api/admin/applications/{app_id}/final").json() == {"status": "stage2_done"}
    assert client.delete(f"/api/admin/applications/{app_id}/final").status_code == 409
    with psycopg.connect(db_url, autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM stage_result WHERE application_id = %s AND stage = 'final'", (app_id,)).fetchone()[0] == 0
        c.execute("UPDATE application SET status = %s WHERE id = %s", (before, app_id))   # 다른 시험이 쓰는 지원자라 되돌림
