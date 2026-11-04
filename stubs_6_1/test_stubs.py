"""가짜 모듈 시험: 영찬 RAG TRD v0.6 진행 규칙(70/40 분기, tier 3·2·1, 재질문 1회)대로 10문항이 흘러가는지, 결과가 DB 규칙을 통과하는지.
실행: pytest -q stubs_6_1/   (pgserver 필요, GPU·Ollama 불필요)
"""
import json
import os
import sys
import tempfile

import psycopg
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "app_6_1"))
from contracts import CompanyDoc, Handoff, QuestionContext, Turn, WeaknessSummary  # noqa: E402
from fake_modules import (evaluate_interview, judge_answer, q1_verify, q2_value, tech_followup, tech_main,  # noqa: E402
                          tech_retry)
from flow import next_action, topic_score  # noqa: E402

# 물어보는 순서대로 낼 답변 수준 (all = 체크리스트 모두 → 85점, half → 55점, none → 20점)
WANT = ["all", "all", "all", "all", "half", "none", "half", "half", "all", "none"]


def answer_for(q, want):
    return {"all": ". ".join(q.key_points) + "까지 설명했습니다.", "half": q.key_points[0] + "만 말했습니다.",
            "none": "잘 모르겠습니다.", "silent": ""}[want]


@pytest.mark.parametrize("kind, depth, score, status, retried, asked, expect", [
    ("non_tech", 0, None, "ok", False, 1, "next_topic"),
    ("tech", 0, 85, "ok", False, 3, "followup"),
    ("tech", 1, 70, "ok", False, 4, "followup"),      # 70은 꼬리 (이상)
    ("tech", 2, 95, "ok", False, 5, "next_topic"),    # 깊이 2가 최대
    ("tech", 0, 69, "ok", False, 3, "next_topic"),    # 40~70 → 다른 주제
    ("tech", 0, 40, "ok", False, 3, "next_topic"),    # 40은 다른 주제 (미만이 재질문)
    ("tech", 0, 39, "ok", False, 3, "retry"),
    ("tech", 0, 10, "ok", True, 4, "next_topic"),     # 주제당 재질문 1회
    ("tech", 0, 0, "silent", False, 3, "next_topic"), # 무응답 → 다음 주제
    ("tech", 0, None, "parse_error", False, 3, "next_topic"),
    ("tech", 0, 85, "ok", False, 10, "end"),
])
def test_next_action(kind, depth, score, status, retried, asked, expect):
    assert next_action(kind, depth, score, status, retried, asked) == expect


@pytest.mark.parametrize("qtype, depth, score, retried, relevance, chains, expect", [
    ("main", 0, 85, False, 0.9, 1, "followup"),       # 두 번째 꼬리 체인까지는 시작
    ("main", 0, 85, False, 0.9, 2, "next_topic"),     # 꼬리 체인은 면접 전체 최대 2개 (FR-74)
    ("followup", 1, 85, False, 0.9, 2, "followup"),   # 이미 시작한 체인은 깊이 2까지 이어감
    ("main", 0, 85, False, 0.3, 0, "retry"),          # 70 이상이어도 관련성 0.4 미만 → 재질문 (FR-81)
    ("main", 0, 85, True, 0.3, 0, "next_topic"),      # 재질문은 주제당 1회
    ("main", 0, 85, False, None, 0, "followup"),      # 관련성 측정 안 함 → 점수만으로
    ("followup", 1, 30, False, 0.9, 1, "next_topic"), # 꼬리 70 미만 → 다른 주제 (재질문은 본 질문에서만)
    ("followup", 1, 85, False, 0.2, 1, "retry"),      # 꼬리에서도 관련성 낮으면 같은 깊이 재질문
    ("reask", 0, 85, True, 0.9, 0, "followup"),       # 재질문 70 이상 → 꼬리 1
    ("reask", 0, 50, True, 0.9, 0, "next_topic"),     # 재질문 70 미만 → 다른 주제 ('모름')
])
def test_next_action_team_rules(qtype, depth, score, retried, relevance, chains, expect):
    """면접 TRD 3.7: 꼬리 체인 2회, 관련성 분기, 재질문은 본 질문에서만"""
    assert next_action("tech", depth, score, "ok", retried, 5, question_type=qtype, relevance=relevance, chains_used=chains) == expect


def test_topic_score():
    assert topic_score(0, [55]) == 22.0 and topic_score(2, [85, 85, 55]) == 90.0


@pytest.fixture(scope="module")
def db():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="stop")
    c = psycopg.connect(srv.get_uri(), autocommit=True)
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    for f in ("../db/common_schema.sql", "../db/interview_schema.sql", "seed_6_1.sql"):
        c.execute(open(os.path.join(HERE, f), encoding="utf-8").read())
    yield c
    c.close()
    srv.cleanup()


def test_full_interview_with_fakes_fits_db(db):
    one = lambda sql, *a: db.execute(sql, a).fetchone()
    handoff = {"job_role": "백엔드", "applied_level": "신입", "deficit_value": "COL", "deficit_reason": "협업 서술 근거 없음"}
    db.execute("""INSERT INTO interview_session(application_id, exam_code, coding_session_id, coding_weakness, ct_band, handoff,
                  status, consent_at, llm_provider, llm_eval_model, llm_fast_model, llm_local_model, started_at)
                  SELECT a.id, 'IV-STUB', r.session_id, r.weakness_summary, '중', %s, 'in_progress', now(),
                         s.llm_provider, s.llm_eval_model, s.llm_fast_model, s.llm_local_model, now()
                  FROM application a, interview_setting s, coding_result r""", (json.dumps(handoff, ensure_ascii=False),))
    sess, weak = one("SELECT id, coding_weakness FROM interview_session WHERE exam_code='IV-STUB'")
    total, follow, retry_s = one("SELECT total_questions, follow_score, retry_score FROM interview_setting")
    docs = [CompanyDoc(chunk_id=f"{d}#{s}", doc_type=t, tier=tr, topic=tp, status=st, related=rl, forbid=fb, body=b)
            for d, s, t, tr, tp, st, rl, fb, b in db.execute(
                "SELECT doc, sec, doc_type, tier, topic, status, related, forbid, body FROM company_doc_chunk ORDER BY tier DESC, doc")]
    ctx = QuestionContext(application_id=1, job_role="백엔드", resume_text="[이름] 인턴 6개월", handoff=Handoff(**handoff),
                          weakness=WeaknessSummary(**weak), ct_band="중", docs=docs)

    def save(q, order, parent):
        qid = one("""INSERT INTO interview_question(session_id, kind, question_type, depth, tech_stack, parent_question_id, ask_order,
                     question_text, basis, source_doc_ids, min_tier, key_points, generated_by_model)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  sess, q.kind, q.question_type, q.depth, q.tech_stack, parent, order, q.question_text, q.basis,
                  json.dumps(q.source_doc_ids) if q.source_doc_ids else None, q.min_tier,
                  json.dumps(q.key_points, ensure_ascii=False), q.model)[0]
        text = answer_for(q, WANT[order - 1])
        j = judge_answer(q, text)
        aid = one("""INSERT INTO interview_answer(question_id, stt_text, answer_sec, finished_in_time, silence_ratio,
                     no_response, audio_deleted_at, stt_done_at) VALUES (%s,%s,90,true,0.1,%s,now(),now()) RETURNING id""",
                  qid, text or None, not text)[0]
        db.execute("""INSERT INTO answer_judgement(answer_id, status, score, rubric, opinion, lang_structure, lang_terms, lang_intent,
                      quotes, rationale, model_tier, provider, model, latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'stub',%s,%s)""",
                   (aid, j.status, j.score, json.dumps(j.rubric, ensure_ascii=False),
                    json.dumps(j.opinion, ensure_ascii=False) if j.opinion else None, j.lang_structure, j.lang_terms,
                    j.lang_intent, json.dumps(j.quotes, ensure_ascii=False), j.rationale, j.model_tier, j.model, j.latency_ms))
        return qid, text, j

    queue, turns, order, used, retried = [q1_verify(ctx), q2_value(ctx)], [], 0, [], False
    current, parent = queue.pop(0), None
    while current:
        order += 1
        qid, text, j = save(current, order, parent)
        turns.append(Turn(ask_order=order, question=current, stt_text=text or None, judgement=j,
                          answer_sec=90, finished_in_time=True, silence_ratio=0.1))
        act = next_action(current.kind, current.depth, j.score, j.status, retried, order, total, follow, retry_s)
        if act == "end":
            break
        if act == "followup":
            current, parent = tech_followup(ctx, current, text), qid
        elif act == "retry":
            current, parent, retried = tech_retry(current), qid, True
        elif queue:
            current, parent = queue.pop(0), None
        else:
            current, parent, retried = tech_main(ctx, used), None, False
            if current:
                used.extend(current.source_doc_ids)

    ev = evaluate_interview(turns)
    eid = one("""INSERT INTO interview_evaluation(session_id, version_no, topic_scores, content_score, language_score,
                 nonverbal_score, rationale, provider, model, status) VALUES (%s,%s,%s,%s,%s,%s,%s,'stub',%s,%s) RETURNING id""",
              sess, ev.version_no, json.dumps(ev.topic_scores), ev.content_score, ev.language_score, ev.nonverbal_score,
              ev.rationale, ev.model, ev.status)[0]
    for c in ev.checks:
        db.execute("INSERT INTO evaluation_check(evaluation_id, check_no, passed, detail, checker) VALUES (%s,%s,%s,%s,%s)",
                   (eid, c.check_no, c.passed, c.detail, c.checker))

    asked = db.execute("""SELECT q.ask_order, q.tech_stack, q.question_type, q.depth, q.min_tier, j.score
                          FROM interview_question q JOIN interview_answer a ON a.question_id=q.id
                          JOIN answer_judgement j ON j.answer_id=a.id WHERE q.session_id=%s ORDER BY q.ask_order""", (sess,)).fetchall()
    print("\n  물어본 순서:", [(o, t, k, d, m, float(s) if s is not None else None) for o, t, k, d, m, s in asked])
    print("  주제 점수:", ev.topic_scores)
    assert [(r[1], r[2], r[3]) for r in asked] == [
        (None, "main", 0), (None, "main", 0),                                       # 1 본인 확인, 2 결핍 가치 (의견만)
        ("DRN", "main", 0), ("DRN", "followup", 1), ("DRN", "followup", 2),          # 3 = 코딩 약점(BFS) 주제, 85 → 꼬리 1·2
        ("MED", "main", 0), ("MED", "reask", 0),                                     # 20점 → 재질문 → 55 → 다음 주제
        ("PAY", "main", 0), ("TKT", "main", 0), ("TKT", "followup", 1)]              # 55 → 다음 주제, 85 → 꼬리(tier 2), 10문항 끝
    assert [r[4] for r in asked][3:5] == [2, 1] and asked[9][4] == 2                 # 꼬리 1 tier 2, 꼬리 2 tier 1
    assert asked[0][5] is None and asked[1][5] is None                               # 비기술은 점수 없음
    assert ev.status == "passed" and ev.topic_scores["DRN 1"] == topic_score(2, [85, 85, 55])
