"""전체 흐름 검증: 담당자·관리자(채용 요청 → 공고 → 서류 → 최종 합격)와 지원자(회원가입 → 지원 → 코딩 → 면접 종료)를
실제 PostgreSQL에서 처음부터 끝까지 돌리고, 규칙 위반을 DB가 막는지 본다.
실행: pytest -q -s test_full_flow.py   (common_schema.sql → interview_schema.sql 순서로 생성)
"""
import json
import os
import tempfile

import psycopg
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = []   # (흐름, 단계, 쓰인 테이블)


def step(flow, name, tables):
    LOG.append((flow, name, tables))


@pytest.fixture(scope="module")
def db():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="stop")
    c = psycopg.connect(srv.get_uri(), autocommit=True)
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    for f in ("common_schema.sql", "interview_schema.sql"):
        c.execute(open(os.path.join(HERE, f), encoding="utf-8").read())
    yield c
    c.close()
    srv.cleanup()


def one(c, sql, *a):
    return c.execute(sql, a).fetchone()


def rejected(c, sql, *a):
    try:
        with c.transaction():
            c.execute(sql, a)
    except (psycopg.errors.IntegrityError, psycopg.errors.RaiseException) as e:
        return f"{type(e).__name__} ({e.diag.constraint_name or e.diag.message_primary})"
    return None


@pytest.fixture(scope="module")
def flow(db):
    c, A = db, "담당자·관리자"
    # ---------- 담당자·관리자: 계정 ----------
    dept = one(c, "INSERT INTO department(name) VALUES ('플랫폼개발팀') RETURNING id")[0]
    sup = one(c, "INSERT INTO admin_user(login_id,password_hash,name,role,totp_secret_enc) VALUES ('root','h','최고관리자','super_admin','enc') RETURNING id")[0]
    rec = one(c, "INSERT INTO admin_user(login_id,password_hash,name,role,totp_secret_enc) VALUES ('hr1','h','채용담당','recruiter','enc') RETURNING id")[0]
    sub = one(c, "INSERT INTO admin_user(login_id,password_hash,name,role,totp_secret_enc) VALUES ('hr2','h','부담당','recruiter','enc') RETURNING id")[0]
    dm = one(c, "INSERT INTO admin_user(login_id,password_hash,name,role,department_id) VALUES ('dev1','h','현업','dept_member',%s) RETURNING id", dept)[0]
    c.execute("INSERT INTO login_history(user_type,user_id,success) VALUES ('admin',%s,true)", (rec,))
    step(A, "관리자 로그인·2단계 인증 (ADM-001·011)", "admin_user, department, login_history")
    # ---------- 채용 요청 → 공고 ----------
    hr = one(c, """INSERT INTO hiring_request(department_id,requested_by,title,job_role,headcount,career_level,reason)
                   VALUES (%s,%s,'백엔드 신입 채용','백엔드',2,'new','신규 서비스') RETURNING id""", dept, dm)[0]
    step(A, "부서 채용 요청 작성 (ADM-020)", "hiring_request")
    post = one(c, """INSERT INTO job_posting(hiring_request_id,title,job_role,job_category,career_level,headcount,status,
                     apply_start,apply_end,doc_announce_at,stage2_start,stage2_end,final_announce_at,created_by)
                     VALUES (%s,'2026 하반기 백엔드 신입','백엔드','dev','new',2,'draft',
                     now()-interval '1 day', now()+interval '5 day', now()+interval '7 day', now()+interval '8 day',
                     now()+interval '12 day', now()+interval '15 day', %s) RETURNING id""", hr, rec)[0]
    c.execute("UPDATE hiring_request SET status='converted', handled_by=%s WHERE id=%s", (rec, hr))
    c.cursor().executemany("INSERT INTO posting_assignee(posting_id,admin_user_id,role) VALUES (%s,%s,%s)", [(post, rec, "main"), (post, sub, "sub")])
    step(A, "요청 접수·공고 전환, 정·부 담당자 지정 (ADM-021·022)", "job_posting, posting_assignee, hiring_request")
    c.cursor().executemany("INSERT INTO document_criteria(posting_id,item,weight) VALUES (%s,%s,%s)",
                  [(post, "직무 경험", 50), (post, "기술 역량", 30), (post, "지원 동기", 20)])
    c.execute("INSERT INTO coding_setting(posting_id,languages) VALUES (%s, ARRAY['python','java'])", (post,))
    c.execute("""INSERT INTO interview_setting(posting_id,llm_provider,llm_eval_model,llm_fast_model)
                 VALUES (%s,'ollama','qwen3:4b','qwen3:1.7b')""", (post,))
    step(A, "서류 기준·코딩·AI 면접 설정 (ADM-022·025)", "document_criteria, coding_setting, interview_setting")
    c.execute("UPDATE job_posting SET status='dept_review' WHERE id=%s", (post,))
    c.execute("INSERT INTO posting_review(posting_id,reviewer_id,decision) VALUES (%s,%s,'approved')", (post, dm))
    c.execute("UPDATE job_posting SET status='published', published_at=now() WHERE id=%s", (post,))
    c.execute("INSERT INTO posting_history(posting_id,changed_by,change) VALUES (%s,%s,'{\"status\":\"published\"}')", (post, rec))
    step(A, "게시 전 부서 확인 → 게시 (ADM-023·024)", "posting_review, job_posting, posting_history")

    # ---------- 지원자: 회원가입 → 지원 ----------
    P = "지원자"
    docs = [one(c, "INSERT INTO consent_document(kind,version,body,effective_at) VALUES (%s,1,'본문',now()) RETURNING id", k)[0]
            for k in ("terms", "privacy", "ai_usage")]
    cand = one(c, """INSERT INTO candidate(email,password_hash,name,phone,ci_hash) VALUES ('a@ex.com','h','지원자A','010-0000-0000','CI_A') RETURNING id""")[0]
    c.execute("INSERT INTO candidate_social_account(candidate_id,provider,provider_user_id) VALUES (%s,'kakao','k123')", (cand,))
    c.cursor().executemany("INSERT INTO candidate_consent(candidate_id,consent_document_id) VALUES (%s,%s)", [(cand, d) for d in docs])
    c.execute("INSERT INTO notification_pref(candidate_id) VALUES (%s)", (cand,))
    step(P, "회원가입: 휴대폰 본인인증(CI)·소셜 연결·약관·개인정보·AI 활용 동의 (CAN-003)", "candidate, candidate_social_account, candidate_consent, consent_document, notification_pref")
    c.execute("INSERT INTO login_history(user_type,user_id,success) VALUES ('candidate',%s,true)", (cand,))
    step(P, "로그인 (CAN-004)", "login_history")
    res = one(c, """INSERT INTO resume(candidate_id,content,photo_object_key) VALUES (%s,'{"경력":"인턴 6개월"}','resume/a.jpg') RETURNING id""", cand)[0]
    c.execute("UPDATE resume SET content='{\"경력\":\"인턴 6개월\",\"자기소개\":\"…\"}', updated_at=now() WHERE id=%s", (res,))
    step(P, "공고 조회 → 지원서 작성·자동 저장 (CAN-001·002·005)", "job_posting(조회), resume")
    app = one(c, """INSERT INTO application(posting_id,candidate_id,resume_snapshot,photo_object_key)
                    SELECT %s,%s,content,photo_object_key FROM resume WHERE id=%s RETURNING id""", post, cand, res)[0]
    step(P, "지원서 제출 (CAN-006)", "application")

    # ---------- 서류 평가 → 1차 발표 ----------
    c.execute("""INSERT INTO document_evaluation(application_id,version_no,fit_score,criteria_scores,deduction,rationale,provider,model,status)
                 VALUES (%s,1,82,'{"직무 경험":40,"기술 역량":24,"지원 동기":18}',0,'근거','ollama','qwen3:4b','passed')""", (app,))
    c.execute("INSERT INTO ai_usage_log(feature,provider,model,input_tokens,output_tokens,application_id) VALUES ('document_eval','ollama','qwen3:4b',3200,600,%s)", (app,))
    step(A, "AI 서류 평가·검증 (F-AI-02)", "document_evaluation, ai_usage_log")
    c.execute("INSERT INTO document_review(application_id,reviewer_id,opinion) VALUES (%s,%s,'경험 적합')", (app, rec))
    c.execute("INSERT INTO stage_result(application_id,stage,result,decided_by) VALUES (%s,'document','pass',%s)", (app, rec))
    c.execute("UPDATE application SET status='doc_passed' WHERE id=%s", (app,))
    step(A, "서류 검토·1차 합격 확정 (ADM-030·031)", "document_review, stage_result, application")
    ann1 = one(c, "INSERT INTO announcement(posting_id,stage,status,checked_by,published_by,published_at) VALUES (%s,'document','published',%s,%s,now()) RETURNING id", post, sub, rec)[0]
    c.execute("INSERT INTO notification(candidate_id,channel,template,announcement_id,status,sent_at) VALUES (%s,'email','doc_result_ready',%s,'sent',now())", (cand, ann1))
    step(A, "1차 발표 검수·게시, 안내 메일 (ADM-042)", "announcement, notification")
    step(P, "결과 확인 (CAN-007)", "stage_result, announcement(조회)")

    # ---------- 2차: 코딩 테스트 ----------
    c.execute("UPDATE application SET status='stage2' WHERE id=%s", (app,))
    cs = one(c, "INSERT INTO coding_session(application_id) VALUES (%s) RETURNING id", app)[0]
    # 6.2 코딩 TRD 9장 스키마: 문제 풀 → 배정 → 제출 → 리뷰 → 결과 (1·2번 골드 4 고정, 3번 등급은 코드 규칙)
    weakness = {"algorithms": ["BFS", "DP"], "failed_groups": [5], "weakness_tags": ["시간 복잡도", "경계값"]}
    for slot, tier, p in [(1, "골드4", 90), (2, "골드4", 85), (3, "골드3", 70)]:
        pid = one(c, """INSERT INTO coding_problem(slot,tier,type,mode,origin,statement,solution_python,solution_java,generator,validator,
                        seed,time_limits) VALUES (%s,%s,'그래프','stdio','collected','문제','print(1)','class Main{}','gen','val',1,
                        '{"python":2000,"java":1000}') RETURNING id""", slot, tier)[0]
        c.execute("INSERT INTO coding_case(problem_id,case_no,size,input,expected) VALUES (%s,1,1,'1','1')", (pid,))
        att = one(c, "INSERT INTO coding_attempt(session_id,slot,problem_id,language) VALUES (%s,%s,%s,'python') RETURNING id", cs, slot, pid)[0]
        c.execute("""INSERT INTO coding_submission(attempt_id,language,code,case_results,group_scores,partial_score)
                     VALUES (%s,'python','print(1)','[]','{}',%s)""", (att, p))
        c.execute("""INSERT INTO coding_review(attempt_id,rubric,summary,quality_level,model)
                     VALUES (%s,'{}',%s,'중','qwen3:4b')""", (att, json.dumps(weakness, ensure_ascii=False)))
    coding_score = round(45 + 40 * 70 / 100, 2)          # 3번 환산 점수 = 시작 점수(골드3 45) + 40 × p/100 (CT-24)
    c.execute("""INSERT INTO coding_result(session_id,p1,p2,q3_base_tier,q3_tier,q3_partial,q3_converted,score_table_version,weakness_summary)
                 VALUES (%s,90,85,'골드3','골드3',70,%s,'v1',%s)""", (cs, coding_score, json.dumps(weakness, ensure_ascii=False)))
    c.execute("UPDATE coding_session SET status='completed', ended_at=now() WHERE id=%s", (cs,))
    step(P, "2차 안내 → 사전 점검 → 코딩 테스트 3문제 (CAN-008·009·010)", "coding_session, coding_problem, coding_case, coding_attempt, coding_submission, coding_review, coding_result")

    # ---------- 2차: AI 화상면접 (화상면접 파트 테이블) ----------
    sess = one(c, """INSERT INTO interview_session(application_id,exam_code,coding_session_id,coding_weakness,status,consent_at,identity_status,
                     llm_provider,llm_eval_model,llm_fast_model,llm_local_model,started_at)
                     SELECT %s,'IV-0001',%s,(SELECT weakness_summary FROM coding_result WHERE session_id=%s),'in_progress',now(),'match',
                     llm_provider,llm_eval_model,llm_fast_model,llm_local_model,now()
                     FROM interview_setting WHERE posting_id=%s RETURNING id""", app, cs, cs, post)[0]
    c.execute("INSERT INTO identity_check(session_id,phase,distance,band) VALUES (%s,'start',0.33,'match')", (sess,))
    c.execute("""INSERT INTO company_doc_chunk(doc,sec,doc_title,sec_title,doc_type,tier,disclosure,topic,body,embedding)
                 VALUES ('PRJ-DRN-3','s1','스카이패스','경로','project',3,'public','DRN','BFS 경로 계산',%s::vector)""",
              ("[" + ",".join(["0.01"] * 1024) + "]",))
    order = 0
    for slot in range(1, 11):                 # 10문항: 1·2번 비기술(의견만)·3번부터 기술 (모두 55점 → 꼬리 없이 다음 주제)
        order += 1
        kind = "non_tech" if slot <= 2 else "tech"
        qid = one(c, """INSERT INTO interview_question(session_id,kind,tech_stack,ask_order,question_text,generated_by_model,asked_at)
                        VALUES (%s,%s,%s,%s,'질문','qwen3:4b',now()) RETURNING id""",
                  sess, kind, None if slot <= 2 else f"주제{slot}", order)[0]
        aid = one(c, """INSERT INTO interview_answer(question_id,stt_text,answer_sec,finished_in_time,silence_ratio,audio_deleted_at,stt_done_at)
                        VALUES (%s,'STT 텍스트',90,true,0.1,now(),now()) RETURNING id""", qid)[0]
        c.execute("""INSERT INTO answer_judgement(answer_id,score,rationale,model_tier,provider,model)
                     VALUES (%s,%s,'근거','eval','ollama','qwen3:4b')""", (aid, None if slot <= 2 else 55))
    c.execute("""INSERT INTO proctor_event(session_id,event_type,occurred_at,duration_ms,occurrence_no,action)
                 VALUES (%s,'tab_leave',now(),3000,1,'warned')""", (sess,))
    c.execute("UPDATE interview_session SET status='completed', ended_at=now(), end_reason='finished' WHERE id=%s", (sess,))
    step(P, "안내사항 → AI 화상면접 → 응시 완료 (CAN-011·012·013)",
         "interview_session, identity_check, interview_question, interview_answer, answer_judgement, proctor_event")
    ev = one(c, """INSERT INTO interview_evaluation(session_id,version_no,topic_scores,content_score,language_score,nonverbal_score,
                   rationale,provider,model,status,confirmed_by,confirmed_at)
                   VALUES (%s,1,'{}',42,22,9,'근거','ollama','qwen3:4b','passed',%s,now()) RETURNING id""", sess, rec)[0]
    for n in range(1, 6):
        c.execute("INSERT INTO evaluation_check(evaluation_id,check_no,passed,checker) VALUES (%s,%s,true,'code')", (ev, n))
    c.execute("UPDATE application SET status='stage2_done' WHERE id=%s", (app,))
    step(A, "AI 면접 최종 평가·검증 5검사·담당자 확인 (ADM-033)", "interview_evaluation, evaluation_check")
    step(P, "면접 종료 — 지원자 흐름 끝 (결과는 발표 후 CAN-007에서)", "—")

    # ---------- 2차 종합 → 최종 ----------
    interview_total = float(one(c, "SELECT total_score FROM interview_evaluation WHERE id=%s", ev)[0])
    c.execute("INSERT INTO stage2_score(application_id,interview_score,coding_score,ai_rank,ai_recommendation) VALUES (%s,%s,%s,1,'pass')",
              (app, interview_total, coding_score))
    step(A, "2차 종합 점수·AI 추천 (면접 60 + 코딩 40, F-SYS-08)", "stage2_score")
    c.execute("INSERT INTO dept_opinion(application_id,author_id,opinion) VALUES (%s,%s,'함께 일하고 싶음')", (app, dm))
    step(A, "요청 부서 결과 검토·의견 (ADM-041)", "dept_opinion")
    c.execute("INSERT INTO stage_result(application_id,stage,result,decided_by) VALUES (%s,'final','pass',%s)", (app, rec))
    c.execute("UPDATE application SET status='final_passed' WHERE id=%s", (app,))
    c.execute("INSERT INTO audit_log(actor_type,actor_id,action,target_type,target_id) VALUES ('admin',%s,'decide_final','application',%s)", (rec, app))
    step(A, "2차 합격 결정 (ADM-040)", "stage_result, application, audit_log")
    ann2 = one(c, "INSERT INTO announcement(posting_id,stage,status,checked_by,published_by,published_at) VALUES (%s,'final','published',%s,%s,now()) RETURNING id", post, sub, rec)[0]
    c.execute("INSERT INTO notification(candidate_id,channel,template,announcement_id,status,sent_at) VALUES (%s,'sms','final_result_ready',%s,'sent',now())", (cand, ann2))
    c.execute("INSERT INTO audit_log(actor_type,actor_id,action,target_type,target_id,detail) VALUES ('admin',%s,'export_passed_list','job_posting',%s,'{\"count\":1,\"format\":\"pdf\"}')", (rec, post))
    c.execute("UPDATE job_posting SET status='finished' WHERE id=%s", (post,))
    step(A, "최종 발표 → 합격자 명단 PDF 내보내기 (ADM-042·043) — 담당자 흐름 끝", "announcement, notification, audit_log, job_posting")
    return dict(dept=dept, rec=rec, sub=sub, dm=dm, post=post, cand=cand, app=app, sess=sess, coding=coding_score,
                interview=interview_total, docs=docs)


def test_end_to_end(db, flow):
    r = one(db, """SELECT a.status, s.total_score, s.fail_cut, f.result
                   FROM application a JOIN stage2_score s ON s.application_id=a.id
                   JOIN stage_result f ON f.application_id=a.id AND f.stage='final' WHERE a.id=%s""", flow["app"])
    assert r[0] == "final_passed" and r[3] == "pass" and r[2] is False
    expected = round(flow["interview"] * 0.6 + flow["coding"] * 0.4, 2)
    assert float(r[1]) == expected
    print(f"\n  면접 {flow['interview']} · 코딩 {flow['coding']} → 2차 종합 {float(r[1])} (과락 아님) → 최종 합격")
    for f, s, t in LOG:
        print(f"  [{f}] {s} → {t}")


def test_rules(db, flow):
    c = db
    cases = {
        "같은 CI로 두 번째 가입(1인 1계정)": ("INSERT INTO candidate(email,name,phone,ci_hash) VALUES ('b@ex.com','B','010','CI_A')",),
        "같은 공고에 두 번 지원(1인 1지원)": ("INSERT INTO application(posting_id,candidate_id,resume_snapshot) VALUES (%s,%s,'{}')", flow["post"], flow["cand"]),
        "2단계 인증 없는 채용담당자": ("INSERT INTO admin_user(login_id,password_hash,name,role) VALUES ('x','h','x','recruiter')",),
        "공고 일정 순서 뒤바뀜": ("""INSERT INTO job_posting(title,job_role,job_category,career_level,headcount,apply_start,apply_end,doc_announce_at,
                               stage2_start,stage2_end,final_announce_at,created_by) VALUES ('x','x','dev','new',1,now(),now()-interval '1 day',
                               now(),now(),now(),now(),%s)""", flow["rec"]),
        "정 담당자 2명": ("INSERT INTO posting_assignee(posting_id,admin_user_id,role) VALUES (%s,%s,'main')", flow["post"], flow["sup"] if "sup" in flow else flow["dm"]),
        "결정자 없이 결과 확정": ("INSERT INTO stage_result(application_id,stage,result) VALUES (%s,'document','pass')", flow["app"]),
        "검수 없이 발표 게시": ("INSERT INTO announcement(posting_id,stage,status,published_by,published_at) VALUES (%s,'document','published',%s,now())", flow["post"], flow["rec"]),
        "서류 감점 -10 초과": ("""INSERT INTO document_evaluation(application_id,version_no,fit_score,criteria_scores,deduction,rationale,provider,model)
                             VALUES (%s,2,50,'{}',-15,'x','a','m')""", flow["app"]),
        "답변 없는 문의를 답변 완료로": ("INSERT INTO inquiry(candidate_id,title,body,status) VALUES (%s,'t','b','answered')", flow["cand"]),
    }
    # 최종 규칙(트리거): 별도 지원자 2명을 만들어 확인
    def new_app(ci, doc_pass=True):
        cid = one(c, "INSERT INTO candidate(email,name,phone,ci_hash) VALUES (%s,'X','010',%s) RETURNING id", f"{ci}@ex.com", ci)[0]
        aid = one(c, "INSERT INTO application(posting_id,candidate_id,resume_snapshot) VALUES (%s,%s,'{}') RETURNING id", flow["post"], cid)[0]
        if doc_pass:
            c.execute("INSERT INTO stage_result(application_id,stage,result,decided_by) VALUES (%s,'document','pass',%s)", (aid, flow["rec"]))
        return aid
    c.execute("UPDATE job_posting SET status='published' WHERE id=%s", (flow["post"],))
    low = new_app("CI_LOW")
    c.execute("INSERT INTO stage2_score(application_id,interview_score,coding_score) VALUES (%s,45,80)", (low,))
    cases["면접 과락(50 미만)인데 최종 합격"] = ("INSERT INTO stage_result(application_id,stage,result,decided_by) VALUES (%s,'final','pass',%s)", low, flow["rec"])
    cases["과락인데 AI 합격 추천"] = ("UPDATE stage2_score SET ai_recommendation='pass' WHERE application_id=%s", low)
    sus = new_app("CI_SUS")
    c.execute("INSERT INTO stage2_score(application_id,interview_score,coding_score) VALUES (%s,80,80)", (sus,))
    c.execute("INSERT INTO suspicion_case(stage,application_id,reason) VALUES ('coding',%s,'paste')", (sus,))
    cases["미결 부정행위 의심 건이 있는데 최종 합격"] = ("INSERT INTO stage_result(application_id,stage,result,decided_by) VALUES (%s,'final','pass',%s)", sus, flow["rec"])
    nodoc = new_app("CI_NODOC", doc_pass=False)
    c.execute("INSERT INTO stage2_score(application_id,interview_score,coding_score) VALUES (%s,90,90)", (nodoc,))
    cases["서류 합격 없이 최종 합격"] = ("INSERT INTO stage_result(application_id,stage,result,decided_by) VALUES (%s,'final','pass',%s)", nodoc, flow["rec"])
    res_app = new_app("CI_RES")
    c.execute("INSERT INTO stage2_score(application_id,interview_score,coding_score) VALUES (%s,80,80)", (res_app,))
    cases["예비 순위 없이 예비 합격"] = ("INSERT INTO stage_result(application_id,stage,result,decided_by) VALUES (%s,'final','reserve',%s)", res_app, flow["rec"])
    new_cid = one(c, "INSERT INTO candidate(email,name,phone,ci_hash) VALUES ('n@ex.com','N','010','CI_NEW') RETURNING id")[0]

    res = {k: rejected(c, *v) for k, v in cases.items()}
    c.execute("UPDATE job_posting SET status='closed' WHERE id=%s", (flow["post"],))
    res["마감된 공고에 지원"] = rejected(c, "INSERT INTO application(posting_id,candidate_id,resume_snapshot) VALUES (%s,%s,'{}')", flow["post"], new_cid)
    expect = {"같은 CI": "ci_hash", "두 번 지원": "application_posting_id_candidate_id_key", "2단계": "admin_user_check",
              "일정 순서": "job_posting_check", "정 담당자": "uq_posting_main", "결정자": "decided_by", "검수 없이": "announcement_check",
              "감점": "deduction", "문의": "inquiry_check", "면접 과락": "fail_cut", "AI 합격 추천": "stage2_score_check",
              "부정행위": "suspicion", "서류 합격 없이": "without_document_pass", "예비 순위": "stage_result_check", "마감된": "outside_window"}
    wrong = [(k, res[k]) for k in res for e, want in expect.items() if e in k and (res[k] is None or want not in res[k])]
    for k, v in res.items():
        print(f"  막힘 | {k} → {v}")
    assert not wrong, wrong


def test_table_count(db, flow):
    n = one(db, "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")[0]
    print(f"\n  테이블 수: {n}")
    assert n == 62                            # 공통 40 + 화상면접 13 + llm_call(11/9) + question_bank·prepared_question·answer_signal + 상세 단계 표 3·보기 1(11/10, 보기도 셈) + answer_accommodation(11/12 승인)


def test_faq_embedding_1024(db, flow):
    """무료판 임베딩(bge-m3 / KURE-v1) 1024차원만 받는다."""
    v = "[" + ",".join(["0.01"] * 1024) + "]"
    db.execute("INSERT INTO faq(question,answer,embedding) VALUES ('발표일','공고에 안내',%s::vector)", (v,))
    with pytest.raises(psycopg.errors.DataException, match="expected 1024 dimensions"):
        with db.transaction():
            db.execute("INSERT INTO faq(question,answer,embedding) VALUES ('x','y',%s::vector)", ("[" + ",".join(["0.01"] * 1536) + "]",))
    print("\n  faq.embedding = vector(1024): 1024 들어감, 1536 막힘")
