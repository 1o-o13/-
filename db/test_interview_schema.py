"""화상면접 데이터 모델 검증: 실제 PostgreSQL에 테이블을 만들고, 면접 1건을 끝까지 넣어 보고, 규칙 위반이 막히는지 본다.
실행: pytest -q test_interview_schema.py   (pgserver가 로컬 PostgreSQL을 띄움)
"""
import json
import os
import tempfile

import psycopg
import pytest

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interview_schema.sql")


@pytest.fixture(scope="module")
def db():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="stop")
    conn = psycopg.connect(srv.get_uri(), autocommit=True)
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    conn.execute(open(SCHEMA, encoding="utf-8").read())
    yield conn
    conn.close()
    srv.cleanup()


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def rejected(conn, sql, *args):
    """규칙 위반이면 DB가 거부해야 한다."""
    try:
        with conn.transaction():
            conn.execute(sql, args)
    except psycopg.errors.IntegrityError as e:  # CHECK·UNIQUE·FK 위반
        return f"{type(e).__name__} ({e.diag.constraint_name})"
    return None


@pytest.fixture(scope="module")
def seed(db):
    """면접 1건을 처음부터 끝까지 넣는다."""
    c = db
    posting = one(c, "INSERT INTO job_posting(title) VALUES ('백엔드 신입') RETURNING id")[0]
    app = one(c, "INSERT INTO application(posting_id, applicant_name) VALUES (%s,'지원자A') RETURNING id", posting)[0]
    admin = one(c, "INSERT INTO admin_user(name) VALUES ('담당자') RETURNING id")[0]
    coding = one(c, "INSERT INTO coding_session(application_id) VALUES (%s) RETURNING id", app)[0]
    c.execute("""INSERT INTO interview_setting(posting_id, llm_provider, llm_eval_model, llm_fast_model)
                 VALUES (%s,'ollama','qwen3:4b','qwen3:1.7b')""", (posting,))
    sess = one(c, """INSERT INTO interview_session(application_id, exam_code, coding_session_id,
                     status, precheck, consent_at, identity_status, llm_provider, llm_eval_model, llm_fast_model, llm_local_model, started_at)
                     SELECT %s,'IV-2026-0001',%s,'in_progress',%s, now(),'match', llm_provider, llm_eval_model, llm_fast_model, llm_local_model, now()
                     FROM interview_setting WHERE posting_id=%s RETURNING id""",
              app, coding, json.dumps({"chrome": True, "upload_mbps": 12.5, "single_face": True}), posting)[0]
    c.execute("INSERT INTO identity_check(session_id, phase, distance, band) VALUES (%s,'start',0.31,'match')", (sess,))
    # 10문항 (영찬 RAG TRD v0.6): (종류, 유형, 깊이, 주제, 앞 질문 번호, 상태, 점수, 판정 모델, 근거 tier)
    flow = [("non_tech", "main", 0, None, None, "ok", None, "eval", None),      # 1번 이력서 본인 확인 → 의견만
            ("non_tech", "main", 0, None, None, "ok", None, "eval", None),      # 2번 결핍 가치 → 의견만
            ("tech", "main", 0, "DRN", None, "ok", 85, "eval", 3),             # 3번 (코딩 약점 주제) 85 → 꼬리
            ("tech", "followup", 1, "DRN", 3, "ok", 80, "eval", 2),            # 4번 꼬리 1 (tier 2)
            ("tech", "followup", 2, "DRN", 4, "ok", 55, "eval", 1),            # 5번 꼬리 2 (tier 1, 최대 깊이)
            ("tech", "main", 0, "MED", None, "ok", 20, "eval", 3),             # 6번 20 → 재질문
            ("tech", "reask", 0, "MED", 6, "ok", 55, "eval", 3),               # 7번 재질문 (같은 근거)
            ("tech", "main", 0, "TKT", None, "silent", 0, "eval", 3),          # 8번 무응답 → 0점, 다음 주제
            ("tech", "main", 0, "PAY", None, "ok", 85, "eval", 3),             # 9번 85 → 꼬리
            ("tech", "followup", 1, "PAY", 9, "ok", 60, "fast", 2)]            # 10번 꼬리 1 (30초 대체 모델) → 종료
    ids = {}
    for order, (kind, qtype, depth, stack, parent_order, status, score, tier, min_tier) in enumerate(flow, start=1):
        qid = one(c, """INSERT INTO interview_question(session_id, kind, question_type, depth, tech_stack, parent_question_id,
                        ask_order, question_text, basis, min_tier, generated_by_model, asked_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'qwen3:4b', now()) RETURNING id""",
                  sess, kind, qtype, depth, stack, ids.get(parent_order), order, f"{order}번 질문",
                  "이력서·1차 인계" if kind == "non_tech" else "새벽소프트 문서", min_tier)[0]
        ids[order] = qid
        nr = status == "silent"
        ans = one(c, """INSERT INTO interview_answer(question_id, stt_text, answer_sec, finished_in_time, silence_ratio, no_response,
                        audio_object_key, audio_deleted_at, stt_done_at) VALUES (%s,%s,95.5,true,0.12,%s,NULL,now(),now()) RETURNING id""",
                  qid, None if nr else "STT 텍스트", nr)[0]
        c.execute("""INSERT INTO answer_judgement(answer_id, status, score, lang_structure, lang_terms, lang_intent, rationale,
                     model_tier, provider, model, latency_ms) VALUES (%s,%s,%s,7,6,8,'근거',%s,'ollama',%s,12000)""",
                  (ans, status, score, tier, "qwen3:1.7b" if tier == "fast" else "qwen3:4b"))
    q = ids
    fu = ids[4]
    # 이벤트: 탭 이탈 1회 경고
    c.execute("""INSERT INTO proctor_event(session_id, event_type, occurred_at, duration_ms, occurrence_no, action)
                 VALUES (%s,'tab_leave', now(), 4000, 1,'warned')""", (sess,))
    c.execute("INSERT INTO identity_check(session_id, phase, distance, band) VALUES (%s,'recheck',0.62,'unclear')", (sess,))
    # 최종 평가 1차 → 검사 실패 → 재평가 통과
    ev1 = one(c, """INSERT INTO interview_evaluation(session_id, version_no, topic_scores, content_score, language_score, nonverbal_score,
                    rationale, provider, model, status) VALUES (%s,1,%s,41.5,21,8,'근거','ollama','qwen3:4b','failed') RETURNING id""",
              sess, json.dumps({"DRN": 88.0, "MED": 15.0, "TKT": 0.0, "PAY": 59.0}))[0]
    for n in range(1, 6):
        c.execute("INSERT INTO evaluation_check(evaluation_id, check_no, passed, checker) VALUES (%s,%s,%s,%s)",
                  (ev1, n, n != 2, "code" if n < 5 else "qwen3:1.7b"))
    ev2 = one(c, """INSERT INTO interview_evaluation(session_id, version_no, topic_scores, content_score, language_score, nonverbal_score,
                    rationale, provider, model, status, confirmed_by, confirmed_at)
                    VALUES (%s,2,%s,41.5,21,8,'근거','ollama','qwen3:4b','passed',%s, now()) RETURNING id""",
              sess, json.dumps({"DRN": 88.0, "MED": 15.0, "TKT": 0.0, "PAY": 59.0}), admin)[0]
    c.execute("""INSERT INTO suspicion_case(stage, application_id, interview_session_id, reason, evidence)
                 VALUES ('interview',%s,%s,'identity_unclear',%s)""", (app, sess, json.dumps({"identity_check": "recheck 0.62"})))
    c.execute("""INSERT INTO interview_incident(session_id, error_code, cause, chat_started_at, chat_ended_at, extra_time_sec, outcome)
                 VALUES (%s,'LLM_TIMEOUT_60S','system', now(), now() + interval '90 seconds', 90,'resumed')""", (sess,))
    c.execute("UPDATE interview_session SET status='completed', ended_at=now(), end_reason='finished', extra_time_sec=90 WHERE id=%s", (sess,))
    return dict(posting=posting, app=app, admin=admin, sess=sess, q=q, fu=fu, ids=ids, ev1=ev1, ev2=ev2)


# ---------------- 정상 흐름 ----------------
def test_full_interview_inserted(db, seed):
    n = {t: one(db, f"SELECT count(*) FROM {t}")[0] for t in
         ["interview_question", "interview_answer", "answer_judgement", "interview_evaluation", "evaluation_check",
          "identity_check", "proctor_event", "suspicion_case", "interview_incident"]}
    assert n == {"interview_question": 10, "interview_answer": 10, "answer_judgement": 10, "interview_evaluation": 2,
                 "evaluation_check": 5, "identity_check": 2, "proctor_event": 1, "suspicion_case": 1, "interview_incident": 1}
    assert float(one(db, "SELECT total_score FROM interview_evaluation WHERE id=%s", seed["ev2"])[0]) == 70.5


def test_adm033_review_query(db, seed):
    """ADM-033: 실제로 물어본 순서대로 질문·STT·현재 판정 (11/2 규칙: 10문항)."""
    rows = db.execute("""SELECT q.ask_order, q.tech_stack, q.kind, q.question_type, q.depth, j.score, j.model_tier, q.min_tier
                         FROM interview_question q JOIN interview_answer a ON a.question_id=q.id
                         JOIN answer_judgement j ON j.answer_id=a.id AND j.is_current
                         WHERE q.session_id=%s ORDER BY q.ask_order""", (seed["sess"],)).fetchall()
    assert [r[0] for r in rows] == list(range(1, 11))
    assert [r[2] for r in rows] == ["non_tech"] * 2 + ["tech"] * 8                 # 1·2번 비기술, 3~10번 기술
    assert all(r[5] is None for r in rows if r[2] == "non_tech")                   # 비기술은 점수 없음
    assert [r[7] for r in rows if r[3] == "followup" and r[4] == 2] == [1]          # 꼬리 2는 tier 1 근거
    assert all(r[3] == "main" for r in rows if r[2] == "non_tech")                 # 인성에는 꼬리·되묻기 없음
    assert max(r[4] for r in rows) == 2                                            # 꼬리질문 최대 깊이 2
    assert [r[3] for r in rows].count("reask") == 1                                # 미흡 → 되묻기 1번
    assert any(r[3] == "followup" and r[6] == "fast" for r in rows)                # 30초 대체 모델 판정 기록


def test_adm035_and_036_lists(db, seed):
    assert one(db, "SELECT count(*) FROM suspicion_case WHERE status <> 'decided'")[0] == 1
    failed = one(db, """SELECT array_agg(check_no) FROM evaluation_check WHERE evaluation_id=%s AND NOT passed""", seed["ev1"])[0]
    assert failed == [2]


def test_no_media_columns(db):
    """영상·얼굴 사진을 담는 컬럼이 없어야 한다(설계 원칙)."""
    cols = [r[0] for r in db.execute("""SELECT column_name FROM information_schema.columns
                                        WHERE table_schema='public' AND table_name LIKE ANY(ARRAY['interview%','identity%','proctor%'])""")]
    assert not [c for c in cols if any(k in c for k in ("video", "photo", "image", "face_img", "recording"))]


def test_audio_purge_query(db, seed):
    """STT가 끝났는데 음성이 남은 답변 = 0건 (삭제 누락 감시)."""
    assert one(db, "SELECT count(*) FROM interview_answer WHERE stt_done_at IS NOT NULL AND audio_object_key IS NOT NULL")[0] == 0


# ---------------- 규칙 위반은 DB가 막는다 ----------------
def test_rules_enforced(db, seed):
    s, q = seed["sess"], seed["q"]
    cases = {
        "점수 100 초과": ("INSERT INTO answer_judgement(answer_id, score, rationale, model_tier, provider, model) "
                      "SELECT id,101,'x','eval','a','m' FROM interview_answer LIMIT 1",),
        "상태값 오타": ("INSERT INTO answer_judgement(answer_id, status, rationale, model_tier, provider, model) "
                    "SELECT id,'skip','x','eval','a','m' FROM interview_answer LIMIT 1",),
        "같은 응시에 같은 번호 2개": ("INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack, parent_question_id, question_text, generated_by_model) "
                              "VALUES (%s,3,'tech','main',0,'Go',NULL,'x','m')", s),
        "3번 이후에 인성 질문": ("INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack, parent_question_id, question_text, generated_by_model) "
                           "VALUES (%s,11,'non_tech','main',0,NULL,NULL,'x','m')", s),
        "인성 질문에 꼬리질문": ("INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack, parent_question_id, question_text, generated_by_model) "
                           "VALUES (%s,2,'non_tech','followup',1,NULL,%s,'x','m')", s, q[1]),
        "기술 질문인데 기술 없음": ("INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack, parent_question_id, question_text, generated_by_model) "
                             "VALUES (%s,15,'tech','main',0,NULL,NULL,'x','m')", s),
        "꼬리질문 깊이 3": ("INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack, parent_question_id, question_text, generated_by_model) "
                       "VALUES (%s,12,'tech','followup',3,'DRN',%s,'x','m')", s, q[5]),
        "앞 질문 없는 꼬리질문": ("INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack, parent_question_id, question_text, generated_by_model) "
                           "VALUES (%s,13,'tech','followup',1,'Go',NULL,'x','m')", s),
        "같은 질문에 되묻기 2번": ("INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack, parent_question_id, question_text, generated_by_model) "
                            "VALUES (%s,14,'tech','reask',0,'MED',%s,'x','m')", s, q[6]),
        "한 질문에 답변 2개(재녹화)": ("INSERT INTO interview_answer(question_id, stt_text, finished_in_time) VALUES (%s,'다시',true)", q[2]),
        "STT 끝났는데 음성 남김": ("WITH nq AS (INSERT INTO interview_question(session_id, ask_order, kind, tech_stack, question_text, generated_by_model) "
                            "VALUES (%s,16,'tech','Go','답변 전 질문','m') RETURNING id) "
                            "INSERT INTO interview_answer(question_id, stt_text, finished_in_time, audio_object_key, stt_done_at) "
                            "SELECT id,'x',true,'s3://a.webm',now() FROM nq", s),
        "같은 지원서 같은 차수 응시 2번": ("INSERT INTO interview_session(application_id, attempt_no, exam_code, llm_provider, llm_eval_model, llm_fast_model, llm_local_model) "
                              "VALUES (%s,1,'IV-X','ollama','a','b','c')", seed["app"]),
        "내용 점수 60 초과": ("INSERT INTO interview_evaluation(session_id, version_no, topic_scores, content_score, language_score, nonverbal_score, "
                        "rationale, provider, model) VALUES (%s,2,'{}',61,0,0,'x','a','m')", s),
        "재평가 2회(버전 3)": ("INSERT INTO interview_evaluation(session_id, version_no, topic_scores, content_score, language_score, nonverbal_score, "
                          "rationale, provider, model) VALUES (%s,3,'{}',1,1,1,'x','a','m')", s),
        "검증 통과 전 담당자 확정": ("UPDATE interview_evaluation SET confirmed_by=%s, confirmed_at=now() WHERE id=%s", seed["admin"], seed["ev1"]),
        "사람 결정 없이 의심 건 확정": ("UPDATE suspicion_case SET status='decided', decision='disqualified'",),
        "응시자 결함인데 추가 시간": ("INSERT INTO interview_incident(session_id, error_code, cause, chat_started_at, extra_time_sec) "
                              "VALUES (%s,'MIC_OFF','candidate',now(),60)", s),
        "배점 합 100 아님": ("UPDATE interview_setting SET weight_content=70",),
        "꼬리질문 깊이 설정 3": ("UPDATE interview_setting SET followup_max_depth=3",),
        "재질문 기준 ≥ 꼬리 기준": ("UPDATE interview_setting SET retry_score=80",),
        "얼굴 대조 거리 없이 match": ("INSERT INTO identity_check(session_id, phase, band) VALUES (%s,'recheck','match')", s),
        "다른 응시의 질문에 꼬리질문": ("INSERT INTO interview_session(application_id, attempt_no, exam_code, llm_provider, llm_eval_model, llm_fast_model, llm_local_model) "
                               "VALUES (%s,2,'IV-2','ollama','a','b','c')", seed["app"]),
    }
    # 마지막 케이스는 준비 단계(정상 삽입) 후 실제 위반을 확인
    results = {}
    for name, args in cases.items():
        if name == "다른 응시의 질문에 꼬리질문":
            s2 = one(db, args[0] + " RETURNING id", *args[1:])[0]
            results[name] = rejected(db, """INSERT INTO interview_question(session_id, ask_order, kind, question_type, depth, tech_stack,
                                           parent_question_id, question_text, generated_by_model)
                                           VALUES (%s,3,'tech','followup',1,'Python',%s,'x','m')""", s2, q[3])
            results["1·2번에 기술 질문"] = rejected(db, """INSERT INTO interview_question(session_id, ask_order, kind, tech_stack,
                                           question_text, generated_by_model) VALUES (%s,1,'tech','Go','x','m')""", s2)
            continue
        results[name] = rejected(db, *args)
    for k, v in results.items():
        print(f"  막힘 | {k} → {v}")
    missed = [k for k, v in results.items() if v is None]
    assert not missed, f"막지 못한 규칙: {missed}"


def test_gaze_away_is_proctoring_only(db, seed):
    """시선 이탈은 감독 이벤트·의심 건으로만 남는다 (점수 컬럼 없음, 결정은 사람)."""
    s = seed["sess"]
    db.execute("""INSERT INTO proctor_event(session_id, event_type, occurred_at, duration_ms, occurrence_no, action)
                  VALUES (%s,'gaze_away',now(),5200,1,'suspected')""", (s,))
    db.execute("INSERT INTO suspicion_case(stage, application_id, interview_session_id, reason) VALUES ('interview',%s,%s,'gaze_away')",
               (seed["app"], s))
    assert rejected(db, "INSERT INTO proctor_event(session_id, event_type, occurred_at, action) VALUES (%s,'gaze',now(),'warned')", s)
    cols = [r[0] for r in db.execute("""SELECT column_name FROM information_schema.columns
                                       WHERE table_name IN ('interview_evaluation','answer_judgement') AND column_name LIKE '%%gaze%%'""").fetchall()]
    assert cols == []
