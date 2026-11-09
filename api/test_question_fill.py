"""새 회사 문서(seed/corpus_6_1)로 지원자 50명 × 답변 유형 4가지 가짜 면접을 돌려, 기술 질문으로 10문항이 다 채워지는지 본다.
실행: pytest -q -s api/test_question_fill.py   (-s면 수준별 예시 3명의 질문 목록을 출력)
"""
import psycopg
import pytest
from psycopg.rows import dict_row

from api import modules as M
from api.interview import engine
from contracts import Handoff, Judgement, QuestionContext, WeaknessSummary

PATTERNS = {   # 물어본 순서대로 낼 답변 (all = 체크리스트 모두 → 85점, half → 55점, none → 20점)
    "all": ["all"] * 10,
    "half": ["half"] * 10,      # 최악: 기술 답변마다 다음 주제 → 주제 8개 필요
    "none": ["none"] * 10,
    "mixed": ["all", "all", "all", "all", "half", "none", "half", "half", "all", "none"],
}


def answer_for(q, want):
    return {"all": ". ".join(q.key_points) + "까지 설명했습니다.", "half": q.key_points[0] + "만 말했습니다.",
            "none": "잘 모르겠습니다."}[want]


@pytest.fixture(scope="module")
def cases(db_url):
    with psycopg.connect(db_url, row_factory=dict_row) as db:
        rows = db.execute("""SELECT c.email, a.id, a.resume_snapshot->>'시험용 수준' AS lv, p.job_role, p.career_level,
                                    d.handoff, r.weakness_summary, r.q3_tier
                             FROM application a JOIN candidate c ON c.id = a.candidate_id JOIN job_posting p ON p.id = a.posting_id
                             JOIN document_evaluation d ON d.application_id = a.id
                             JOIN coding_session s ON s.application_id = a.id JOIN coding_result r ON r.session_id = s.id
                             ORDER BY c.email""").fetchall()
        docs = {b: M.load_docs(db, b, engine.DEPT[rows[0]["job_role"]], engine.LEVEL[rows[0]["career_level"]])
                for b in ("상", "중", "하")}
        forbid = {w for (w,) in db.execute("SELECT DISTINCT unnest(forbid) FROM company_doc_chunk").fetchall()}
    out = []
    for r in rows:
        band = engine.CT_BAND[r["q3_tier"]]
        ctx = QuestionContext(application_id=r["id"], job_role=r["job_role"], resume_text="(가림)", handoff=Handoff(**r["handoff"]),
                              weakness=WeaknessSummary(**r["weakness_summary"]), ct_band=band, docs=docs[band])
        ctx.project = M.pick_project(ctx)
        out.append((r["email"], r["lv"], ctx))
    return out, forbid


def run(ctx, pattern):
    prepared, asked = engine.prepare(ctx), []
    q = prepared[0]
    while q is not None:
        stt = answer_for(q, PATTERNS[pattern][len(asked)])
        j: Judgement = M.judge_answer(q, stt)
        asked.append((q, j, stt))
        act, q = engine.decide(ctx, asked)
        if act != "end" and q is None:
            q = prepared[len(asked)]
    return asked


@pytest.mark.parametrize("pattern", PATTERNS)
def test_every_candidate_gets_10_questions(cases, pattern):
    rows, forbid = cases
    by_id = {}
    for email, lv, ctx in rows:
        by_id = {d.chunk_id: d for d in ctx.docs}
        asked = run(ctx, pattern)
        qs = [q for q, _, _ in asked]
        assert len(qs) == 10, f"{email}: {len(qs)}문항"
        assert [q.kind for q in qs] == ["non_tech"] * 2 + ["tech"] * 8
        mains = [q for q in qs if q.kind == "tech" and q.question_type == "main"]
        ids = [q.source_doc_ids[0] for q in mains]
        assert len(ids) == len(set(ids))                                         # 본 질문은 매번 새 섹션
        own = {d.chunk_id for d in ctx.docs if d.tier == 3 and d.topic == ctx.project}
        for n, q in enumerate(mains):                                            # 고른 프로젝트 섹션을 다 쓰기 전에는 다른 프로젝트로 안 감
            assert q.tech_stack == ctx.project or own <= set(ids[:n]), f"{email}: 프로젝트 섹션이 남았는데 {q.tech_stack}"
        for q in qs:
            assert not any(w in q.question_text for w in forbid), f"{email}: forbid 노출 {q.question_text}"
            if q.question_type == "followup":
                assert q.source_doc_ids and by_id[q.source_doc_ids[0]].tier == 3 - q.depth   # 꼬리 1 → tier 2, 꼬리 2 → tier 1
            if q.kind == "tech" and q.question_type == "main":
                assert by_id[q.source_doc_ids[0]].tier == 3
        q3 = qs[2]
        assert "코딩 약점" in q3.basis
        # 자기 난이도 대역에 약점 알고리즘 섹션이 있으면 3번은 반드시 그 섹션 (FR-73).
        # 대역 안에 없는 10명(cand13·16·21·24·32·33·35·40·45·50)은 데모에서 모두 1차 탈락이라 2차에 오지 않는다 (seed/demo_accounts.sql)
        if any(d.tier == 3 and any(a in d.body for a in ctx.weakness.algorithms) for d in ctx.docs):
            assert any(a in by_id[q3.source_doc_ids[0]].body for a in ctx.weakness.algorithms), f"{email}: 3번이 약점과 무관"


def test_print_examples(cases):
    """수준별 예시: 상 → 대부분 충족(all), 중 → 절반(half), 하 → 거의 없음(none)"""
    rows, _ = cases
    want = {"상": "all", "중": "half", "하": "none"}
    for email, lv, ctx in [r for r in rows if r[0] in ("cand01@test.local", "cand04@test.local", "cand07@test.local")]:
        print(f"\n■ {email} · 시험용 수준 {lv} · 난이도 대역 {ctx.ct_band} · 코딩 약점 {ctx.weakness.algorithms}")
        for i, (q, j, _) in enumerate(run(ctx, want[lv]), 1):
            kind = "비기술" if q.kind == "non_tech" else {"main": "본 질문", "followup": f"꼬리 {q.depth}", "reask": "재질문"}[q.question_type]
            src = ", ".join(q.source_doc_ids) or "-"
            score = "의견" if j.score is None else f"{j.score:.0f}점"
            print(f"  {i:>2}. [{kind:<4}] {q.tech_stack or '':<3} {src:<18} {score:>5} | {q.question_text}")
