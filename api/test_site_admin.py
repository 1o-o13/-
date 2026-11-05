"""채용 홈 공개 공고, 관리자 지원자 현황·이력서 (화면 테스트 D-01~05, P-02)."""
import pyotp

from api.site import ESSAYS

TOTP = "JBSWY3DPEHPK3PXP"
ESS = {k: f"{k}에 대한 답입니다." for k, _ in ESSAYS}      # 자기소개서 4문항 (팀 이력서 양식, 모두 필수)


def test_public_postings_without_login(client):
    client.cookies.clear()
    rows = client.get("/api/site/postings").json()             # 다른 시험이 만든 공고가 섞일 수 있어 기준 공고로 확인
    seed = next(r for r in rows if r["title"] == "2026 하반기 백엔드 신입")
    assert seed["accepting"] is False                           # 접수는 끝나고 2차 기간 중
    assert not any(k in r for r in rows for k in ("candidate_id", "score"))


def test_admin_applicants_and_resume(client):
    client.cookies.clear()
    client.post("/api/auth/admin/login", json={"login_id": "dev01", "password": "Test1234!"})   # 부서원도 조회는 됨
    pid = client.get("/api/admin/postings").json()[0]["id"]
    rows = client.get("/api/admin/applications", params={"posting_id": pid}).json()
    assert len(rows) == 50                                                                    # D-01
    assert sum(r["gender"] == "남" for r in rows) == 30 and min(r["age"] for r in rows) >= 20 and max(r["age"] for r in rows) <= 39
    assert all(r["doc_status"] == "passed" and r["deficit_value"] in ("OWN", "COL", "INT", "CUS", "GRW") for r in rows)  # D-04
    band = {"골드2": "상", "골드3": "상", "골드4": "중", "골드5": "하", "실버1": "하"}
    assert all(band[r["q3_tier"]] == r["test_level"] for r in rows)                          # D-05 등급 = 수준
    d = client.get(f"/api/admin/applications/{rows[0]['id']}").json()
    personal = d["application"]["resume_snapshot"]["인적사항"]
    assert all(personal.get(k) for k in ("이름", "성별", "생년월일", "나이", "연락처", "이메일", "주소"))   # D-02·P-02 원본 그대로
    assert d["coding"]["weakness_summary"]["algorithms"] and d["document"]["handoff"]["deficit_reason"]
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": "cand01@test.local", "password": "Test1234!"})
    assert client.get("/api/admin/applications", params={"posting_id": pid}).status_code == 401   # 지원자는 못 봄 (관리자 로그인 따로, 11/10)
    client.cookies.clear()
    assert client.post("/api/auth/admin/login", json={"login_id": "hr01", "password": "Test1234!",
                                                       "otp": pyotp.TOTP(TOTP).now()}).status_code == 200


def test_apply_to_accepting_posting(client, db_url):
    """지원서 제출(간단 버전): 접수 중인 공고에만, 공고마다 한 번만. 제출하면 서류 심사 중 + 인적사항은 계정에서"""
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        pid = c.execute("""INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, status, published_at,
                               apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
                           SELECT '접수 중 시험 공고', '프론트엔드', 'dev', 'junior', 1, 'published', now(), now() - interval '1 day',
                                  now() + interval '5 day', now() + interval '6 day', now() + interval '7 day', now() + interval '9 day',
                                  now() + interval '10 day', id FROM admin_user WHERE login_id = 'hr01' RETURNING id""").fetchone()[0]
        old = c.execute("SELECT id FROM job_posting WHERE title = '2026 하반기 백엔드 신입'").fetchone()[0]
    client.cookies.clear()
    client.post("/api/auth/signup", json={"email": "apply.test@gmail.com", "password": "Good123!", "name": "지원시험", "phone": "010-5555-6666"})
    client.post("/api/auth/login", json={"email": "apply.test@gmail.com", "password": "Good123!"})
    resume = {"성별": "여", "생년월일": "1999-03-02", "주소": "서울특별시 마포구 서교동", "Github": "",
              "지원직무": "프론트엔드 개발자 지원", "소개": ["사용자가 편한 화면을 만들고 싶습니다.", ""], "자기소개서": ESS,
              "학력사항": [{"기간": "2021.03 - 2025.02", "학교": "새솔대학교", "학과": "소프트웨어학과", "학점": "3.72·4.5", "상태": "졸업"}],
              "보유기술": [{"분야": "프론트엔드", "기술내역": "React, TypeScript", "설명": "상태 관리와 훅"}],
              "프로젝트소개서": [{"이름": "포트폴리오", "작업과정성과": "Next.js로 만든 개인 사이트. 방문자 월 300명", "기간": "2025.01 - 2025.03",
                           "인원": "1명", "개발환경": "Next.js"}],
              "보유자격증": [{"자격증명": "정보처리기사", "발급기관": "한국산업인력공단", "취득일": "2025.06"}],
              "교육활동": [{"과정": "교내 해커톤", "기간": "2024.11", "내용": "참가"}], "외부AI동의": True}
    assert client.post(f"/api/site/postings/{pid}/apply", json={**resume, "소개": ["", ""]}).status_code == 422
    assert client.post(f"/api/site/postings/{pid}/apply", json={**resume, "학력사항": []}).status_code == 422
    r = client.post(f"/api/site/postings/{pid}/apply", json={**resume, "자기소개서": {**ESS, "입사후포부": " "}})   # 자기소개서는 모두 필수
    assert r.status_code == 422 and "입사후포부" in r.text
    for no in (False, None):                                        # 외부 AI 처리 동의는 필수 (거부·미선택이면 제출 불가)
        r = client.post(f"/api/site/postings/{pid}/apply", json={**resume, "외부AI동의": no})
        assert r.status_code == 400 and "동의" in r.text
    r = client.post(f"/api/site/postings/{pid}/apply", json=resume)
    assert r.status_code == 201
    assert client.post(f"/api/site/postings/{pid}/apply", json=resume).status_code == 409          # 한 번만
    assert client.post(f"/api/site/postings/{old}/apply", json=resume).status_code == 409          # 접수 마감 공고
    mine = client.get("/api/interview/applications").json()
    assert [(a["posting_id"], a["status"]) for a in mine] == [(pid, "submitted")]
    with psycopg.connect(db_url, autocommit=True) as c:
        snap = c.execute("SELECT resume_snapshot FROM application WHERE id = %s", (r.json()["application_id"],)).fetchone()[0]
    assert snap["인적사항"]["이름"] == "지원시험" and snap["인적사항"]["연락처"] == "010-5555-6666" and snap["인적사항"]["나이"] >= 26
    assert [x["문항"] for x in snap["자기소개서"]] == [k for k, _ in ESSAYS] and snap["프로젝트소개서"][0]["이름"] == "포트폴리오"
    assert snap["보유자격증"][0]["자격증명"] == "정보처리기사" and snap["소개"] == ["사용자가 편한 화면을 만들고 싶습니다."]
    assert snap["학력"] == "새솔대학교 소프트웨어학과 졸업" and snap["기술"] == ["React", "TypeScript"] and snap["경력"] == "없음"   # 요약 칸
    assert snap["인적사항"]["Github"] is None


def test_edit_application_until_deadline(client, db_url):
    """접수 마감 전·서류 심사 중이면 지원서를 고칠 수 있고, 마감 뒤에는 거부"""
    import psycopg
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": "apply.test@gmail.com", "password": "Good123!"})   # 위 시험에서 지원한 계정
    with psycopg.connect(db_url, autocommit=True) as c:
        pid = c.execute("SELECT id FROM job_posting WHERE title = '접수 중 시험 공고'").fetchone()[0]
    got = client.get(f"/api/site/postings/{pid}/my-application").json()
    assert got["editable"] is True and got["resume"]["보유기술"][0]["기술내역"] == "React, TypeScript"
    new = {**got["resume"], "보유기술": [{"분야": "프론트엔드", "기술내역": "React, TypeScript, Next.js", "설명": ""}], "소개": ["고친 소개입니다."], "외부AI동의": True}
    assert client.put(f"/api/site/postings/{pid}/apply", json=new).status_code == 200
    again = client.get(f"/api/site/postings/{pid}/my-application").json()["resume"]
    assert again["보유기술"][0]["기술내역"].endswith("Next.js") and again["소개"] == ["고친 소개입니다."]
    assert client.get("/api/interview/applications").json()[0]["editable"] is True
    with psycopg.connect(db_url, autocommit=True) as c:      # 마감이 지나면
        c.execute("UPDATE job_posting SET apply_start = now() - interval '3 day', apply_end = now() - interval '1 minute' WHERE id = %s", (pid,))
    assert client.put(f"/api/site/postings/{pid}/apply", json=new).status_code == 409
    assert client.get(f"/api/site/postings/{pid}/my-application").json()["editable"] is False


def test_one_active_application_at_a_time(client, db_url):
    """진행 중인 지원(2차 면접 등)이 있으면 다른 공고에 지원할 수 없다. 떨어지면 바로 다른 공고에 지원할 수 있다"""
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        pid = c.execute("""INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, status, published_at,
                               apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
                           SELECT '두 번째 접수 중 공고', '백엔드', 'dev', 'junior', 1, 'published', now(), now() - interval '1 day',
                                  now() + interval '5 day', now() + interval '6 day', now() + interval '7 day', now() + interval '9 day',
                                  now() + interval '10 day', id FROM admin_user WHERE login_id = 'hr01' RETURNING id""").fetchone()[0]
    resume = {"지원직무": "백엔드 개발자 지원", "소개": ["열심히 하겠습니다."], "학력사항": [{"학교": "가람대학교"}], "자기소개서": ESS, "외부AI동의": True}
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": "cand21@test.local", "password": "Test1234!"})   # 2차 면접 대상(stage2)
    r = client.post(f"/api/site/postings/{pid}/apply", json=resume)
    assert r.status_code == 409 and "진행 중인 지원" in r.json()["detail"]
    with psycopg.connect(db_url, autocommit=True) as c:                       # 그 지원이 떨어지면(최종 불합격)
        c.execute("""UPDATE application SET status = 'final_failed'
                     WHERE candidate_id = (SELECT id FROM candidate WHERE email = 'cand21@test.local')""")
    assert client.post(f"/api/site/postings/{pid}/apply", json=resume).status_code == 201      # 바로 다른 공고 지원 가능


def test_resume_details_for_50_candidates(client, db_url):
    """seed/resume_detail: 50명 모두 팀 이력서 양식(자기소개서 4문항·학력사항·보유기술·프로젝트 소개서)으로 바뀌고, 인적사항·수준은 그대로.
    LLM에 넣는 이력서 글(mask_resume)에는 이름·학교·연락처가 없다"""
    import psycopg
    from psycopg.rows import dict_row

    from api.interview.store import mask_resume
    from scripts import load_resume_detail
    assert load_resume_detail.main(db_url) == 50
    with psycopg.connect(db_url, row_factory=dict_row) as c:
        rows = c.execute("""SELECT a.resume_snapshot AS r FROM application a JOIN candidate d ON d.id = a.candidate_id
                            JOIN job_posting p ON p.id = a.posting_id WHERE d.ci_hash LIKE 'CI_TEST_%%'
                              AND p.title = '2026 하반기 백엔드 신입'""").fetchall()
    assert len(rows) == 50
    for x in rows:
        r = x["r"]
        assert [e["문항"] for e in r["자기소개서"]] == [k for k, _ in ESSAYS] and all(e["답"] for e in r["자기소개서"])
        assert r["프로젝트소개서"] and r["보유기술"] and len(r["학력사항"]) == 2 and r["지원직무"] and r["소개"]
        assert r["인적사항"]["이름"] and r["시험용 수준"] in ("상", "중", "하")       # 원래 값은 그대로
        text = mask_resume(r)
        schools = [e["학교"] for e in r["학력사항"]] + [r["학력사항"][0]["학교"][:-2]]   # 대학·고교, 줄임말(한빛대)
        assert r["인적사항"]["이름"] not in text and r["인적사항"]["연락처"] not in text and not any(s in text for s in schools)
        assert "자기소개서" in text and "성격의 장/단점" in text


def test_stage2_rank_recommend_and_final_decision(client, db_url):
    """2차 종합 점수 순위·AI 추천(과락 제외, 모집 인원 2배까지 합격 추천, 예비 없음)과 담당자 최종 결정"""
    import psycopg
    from psycopg.rows import dict_row

    from api.admin.routes import rank_stage2
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
        # 다른 시험이 만든 2차 점수와 섞이지 않게 시험용 공고(모집 2명)를 따로 만들고 지원자 6명 + 2차 미완료 1명을 넣는다
        pid = c.execute("""INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, status, published_at,
                               apply_start, apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
                           SELECT '순위 시험 공고', '백엔드', 'dev', 'new', 2, 'published', now() - interval '1 day', now() - interval '1 day',
                                  now() + interval '1 day', now() + interval '2 day', now() + interval '3 day', now() + interval '5 day',
                                  now() + interval '7 day', id FROM admin_user WHERE login_id = 'hr01' RETURNING id""").fetchone()["id"]
        apps = [c.execute("""INSERT INTO application(posting_id, candidate_id, resume_snapshot, status)
                             SELECT %s, id, '{}'::jsonb, 'stage2' FROM candidate WHERE email = %s RETURNING id""",
                          (pid, f"cand{n}@test.local")).fetchone()["id"] for n in range(30, 37)]   # 접수 기간 안에 넣는다 (DB 트리거)
        c.cursor().executemany("""INSERT INTO stage_result(application_id, stage, result, decided_by)
                         SELECT %s, 'document', 'pass', id FROM admin_user WHERE login_id = 'hr01'""", [(a,) for a in apps])
        waiting, apps = apps[-1], apps[:-1]
        # 총점: 90(과락: 면접 45) · 88 · 80 · 70 · 60 · 50  → 모집 2명: 88·80 합격 추천, 70·60 예비, 50 없음, 과락은 추천 없음
        for a, (iv, cd) in zip(apps, [(45, 100), (88, 88), (80, 80), (70, 70), (60, 60), (50, 50)]):
            c.execute("UPDATE application SET status = 'stage2_done' WHERE id = %s", (a,))
            c.execute("INSERT INTO stage2_score(application_id, interview_score, coding_score) VALUES (%s, %s, %s)", (a, iv, cd))
        rank_stage2(c, pid)
        got = c.execute("SELECT application_id, ai_rank, ai_recommendation, fail_cut FROM stage2_score WHERE application_id = ANY(%s)",
                        (apps,)).fetchall()
    by = {g["application_id"]: g for g in got}
    assert [by[a]["ai_recommendation"] for a in apps] == ["none", "pass", "pass", "pass", "pass", "none"]
    assert by[apps[0]]["fail_cut"] and by[apps[1]]["ai_rank"] < by[apps[2]]["ai_rank"]
    client.cookies.clear()
    assert client.post("/api/auth/admin/login", json={"login_id": "hr01", "password": "Test1234!", "otp": pyotp.TOTP(TOTP).now()}).status_code == 200
    board = client.get(f"/api/admin/postings/{pid}/final").json()
    ranked = [r["id"] for r in board["rows"] if r["ai_rank"] is not None]
    assert ranked.index(apps[1]) < ranked.index(apps[2]) < ranked.index(apps[3])
    assert client.post(f"/api/admin/applications/{apps[1]}/final", json={"decision": "final_passed"}).json()["status"] == "final_passed"
    assert client.post(f"/api/admin/applications/{apps[1]}/final", json={"decision": "final_failed"}).json()["status"] == "final_failed"   # 발표 전까지 바꿀 수 있음
    assert client.post(f"/api/admin/applications/{apps[3]}/final", json={"decision": "reserve"}).status_code == 422             # 예비 합격 없음
    r = client.post(f"/api/admin/applications/{apps[0]}/final", json={"decision": "final_passed"})                         # 과락 → DB 규칙이 막음
    assert r.status_code == 409 and "과락" in r.json()["detail"]
    assert client.post(f"/api/admin/applications/{apps[0]}/final", json={"decision": "final_failed"}).status_code == 200   # 불합격은 됨
    with psycopg.connect(db_url, row_factory=dict_row) as c:
        fr = c.execute("SELECT result, reserve_rank, decided_by FROM stage_result WHERE application_id = %s AND stage = 'final'", (apps[1],)).fetchone()
    assert fr["result"] == "fail" and fr["reserve_rank"] is None and fr["decided_by"]                                     # 결정자 기록
    assert any(r["id"] == waiting and r["ai_rank"] is None for r in board["rows"])                                   # 2차 미완료는 순위 밖
    assert client.post(f"/api/admin/applications/{waiting}/final", json={"decision": "final_passed"}).status_code == 409   # 2차 점수 없으면 결정 불가
    ann = f"/api/admin/postings/{pid}/final/announce"                                                               # 체크박스 + '결과 확정' 한 번 (11/11)
    r = client.post(ann, json={"pass_ids": [apps[0], apps[2]]})
    assert r.status_code == 409 and "과락" in r.json()["detail"]                                                     # 먼저 모두 검사 → 아무것도 안 바뀜
    assert client.post(ann, json={"pass_ids": [waiting]}).status_code == 409                                         # 2차 점수 없는 사람은 대상 아님
    r = client.post(ann, json={"pass_ids": [apps[2]]}).json()
    assert r == {"announced": len(ranked), "passed": 1, "notifications": 2 * len(ranked)}                          # 나머지는 모두 불합격, 메일+문자
    st = {x["id"]: (x["status"], x["announced"]) for x in client.get(f"/api/admin/postings/{pid}/final").json()["rows"]}
    assert st[apps[2]] == ("final_passed", True) and st[apps[1]] == ("final_failed", True) and st[waiting][1] is False
    assert client.post(f"/api/admin/applications/{apps[2]}/final", json={"decision": "final_failed"}).status_code == 409   # 알린 뒤에는 못 바꿈
    assert client.post(ann, json={"pass_ids": []}).status_code == 409                                                # 더 확정할 사람 없음
    client.cookies.clear()
    client.post("/api/auth/admin/login", json={"login_id": "dev01", "password": "Test1234!"})                              # 부서원은 결정 못 함
    assert client.post(f"/api/admin/applications/{apps[2]}/final", json={"decision": "final_passed"}).status_code == 403
    with psycopg.connect(db_url, autocommit=True) as c:                                                                   # 다른 시험에 안 남게
        c.execute("DELETE FROM notification WHERE announcement_id IN (SELECT id FROM announcement WHERE posting_id = %s)", (pid,))
        c.execute("DELETE FROM announcement WHERE posting_id = %s", (pid,))
        c.execute("DELETE FROM application WHERE posting_id = %s", (pid,))   # stage_result·stage2_score는 CASCADE
        c.execute("DELETE FROM interview_setting WHERE posting_id = %s", (pid,))
        c.execute("DELETE FROM job_posting WHERE id = %s", (pid,))
