"""직무별 질문 은행 → 지원 건마다 미리 만든 질문 (11/10 요청).

- question_bank: 회사가 직무별로 뽑아 둔 기술 본 질문. 근거는 tier 3 공개 청크(프로젝트·해결된 장애 회고). scripts/build_question_bank.py가 만든다
- 1차 합격 즉시(메인 그래프 handoff 뒤): 1·2번 + 기술 본 질문 후보(4~10번)를 만들어 검증 → prepared_question
- 코딩이 끝나는 즉시: 3번(코딩 약점 본 질문)을 만들어 검증 (1차 때는 약점 정보가 없음)
- 2차 면접: 미리 만들고 검증을 통과한(ready) 질문을 출제한다. 꼬리·재질문은 답변을 봐야 해서 면접 중에 만든다
- 검증(필수): 길이 · 지시문 베끼기 · 근거 금지어 · 개인정보 · 문서 번호 노출 · 근거 청크(tier 3, internal 아님) · 다른 질문과 중복.
  떨어지면 1번 다시 만들고, 또 떨어지면 은행의 기본 질문(이미 검증됨)을 쓴다. 기본 질문도 없으면 failed로 남기고 면접 때 새로 만든다
"""
import logging
import re

from psycopg.types.json import Jsonb

from api import llm_gate as G
from api import modules as M
from api import retrieve
from api.interview import engine
from api.interview.store import mask_resume

# isort: split
from contracts import CompanyDoc, Handoff, Question, QuestionContext, WeaknessSummary  # stubs_6_1 경로는 api.modules가 연다

log = logging.getLogger(__name__)
MAIN_SLOTS = range(4, 11)          # 기술 본 질문 후보 7개 (꼬리·재질문이 없으면 3~10번이 모두 본 질문)
ECHO = ("만드세요", "문항:", "하세요.", "[가린 이력서]", "지원자에게 읽어 줄", "구어체", "회사 문서")
DOC_ID = re.compile(r"\b(?:PRJ|INC|ISS|RES|TST|UNT|TAL|JD|RUB|GLS)-[A-Z0-9-]+|#s\d+")


# ---------- 검증 ----------

def verify(q: Question, docs: dict[str, CompanyDoc], others: list[str]) -> dict:
    """질문 하나 검증. {항목: 통과 여부 또는 사유}, 'ok' = 모두 통과"""
    text = q.question_text.strip()
    forbid = [w for c in q.source_doc_ids for w in (docs[c].forbid if c in docs else [])]
    checks = {
        "길이": 10 <= len(text) <= 220,
        "지시문 베끼기 없음": not any(w in text for w in ECHO),
        "금지어 없음": not [w for w in forbid if w and w in text],
        "개인정보 없음": not [h for h in G.leak_scan(text) if h.startswith("PII")],
        "문서 번호 노출 없음": not DOC_ID.search(text),
        "중복 아님": text not in others,
    }
    if q.kind == "tech":
        checks["근거 청크 tier 3"] = bool(q.source_doc_ids) and all(c in docs and docs[c].tier == 3 for c in q.source_doc_ids)
    checks["ok"] = all(checks.values())
    return checks


# ---------- 문맥 ----------

def _docs(db, dept: str, level: str, ct_band: str | None = None) -> list[CompanyDoc]:
    """근거 후보: 2차·internal 제외·개요 제외. tier 3은 부서·직급(대역을 알면 대역까지), tier 1·2는 주제만"""
    rows = db.execute("""SELECT doc, sec, doc_type, tier, topic, status, related, forbid, body FROM company_doc_chunk
                         WHERE '2차' = ANY(stages) AND disclosure <> 'internal' AND sec <> 'ov'
                           AND (tier IN (1, 2) OR (tier = 3 AND %s = ANY(dept) AND %s = ANY(level)
                                                   AND (%s::text IS NULL OR ct_band IS NOT DISTINCT FROM %s)))
                         ORDER BY tier DESC, doc, sec""", (dept, level, ct_band, ct_band)).fetchall()
    return [CompanyDoc(chunk_id=f"{r['doc']}#{r['sec']}", doc_type=r["doc_type"], tier=r["tier"], topic=r["topic"], status=r["status"],
                       related=r["related"], forbid=r["forbid"], body=r["body"]) for r in rows]


def context(db, app_id: int, weakness: dict | None = None, ct_band: str | None = None) -> QuestionContext:
    """면접 응시가 생기기 전(1차 합격 직후)의 질문 문맥. 모델은 공고 면접 설정, 국외 전송은 지원서 제출 때 필수 동의"""
    r = db.execute("""SELECT a.id, a.resume_snapshot, p.job_role, p.career_level, st.llm_provider, st.llm_eval_model, st.llm_fast_model,
                             st.llm_local_model, (SELECT d.handoff FROM document_evaluation d WHERE d.application_id = a.id
                                                  AND d.handoff IS NOT NULL ORDER BY d.version_no DESC LIMIT 1) AS handoff
                      FROM application a JOIN job_posting p ON p.id = a.posting_id JOIN interview_setting st ON st.posting_id = p.id
                      WHERE a.id = %s""", (app_id,)).fetchone()
    h = r["handoff"] or {"job_role": r["job_role"], "applied_level": engine.LEVEL[r["career_level"]], "deficit_value": "GRW",
                         "deficit_reason": "결핍 가치 없음 — 기본값(임시)"}
    ctx = QuestionContext(application_id=app_id, job_role=r["job_role"], resume_text=mask_resume(r["resume_snapshot"]),
                          handoff=Handoff(**{k: h[k] for k in ("job_role", "applied_level", "deficit_value", "deficit_reason")},
                                          check_list=h.get("check_list", [])),
                          weakness=WeaknessSummary(**weakness) if weakness else None, ct_band=ct_band,
                          docs=_docs(db, engine.DEPT.get(r["job_role"], "BE"), engine.LEVEL[r["career_level"]], ct_band),
                          overseas_consent=True,
                          llm={"provider": r["llm_provider"], "eval": r["llm_eval_model"], "fast": r["llm_fast_model"], "local": r["llm_local_model"]})
    ctx.project = M.pick_project(ctx)
    return ctx


# ---------- 만들기 ----------

def _save(db, app_id: int, slot: int, q: Question, check: dict, bank_id: int | None = None) -> None:
    db.execute("""INSERT INTO prepared_question(application_id, slot, kind, tech_stack, question_text, basis, source_doc_ids, min_tier,
                      key_points, model, bank_id, status, verify)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                  ON CONFLICT (application_id, slot) DO UPDATE SET kind = EXCLUDED.kind, tech_stack = EXCLUDED.tech_stack,
                      question_text = EXCLUDED.question_text, basis = EXCLUDED.basis, source_doc_ids = EXCLUDED.source_doc_ids,
                      min_tier = EXCLUDED.min_tier, key_points = EXCLUDED.key_points, model = EXCLUDED.model, bank_id = EXCLUDED.bank_id,
                      status = EXCLUDED.status, verify = EXCLUDED.verify, created_at = now()""",
               (app_id, slot, q.kind, q.tech_stack, q.question_text, q.basis, Jsonb(q.source_doc_ids), q.min_tier, Jsonb(q.key_points),
                q.model, bank_id, "ready" if check["ok"] else "failed", Jsonb(check)))


def _checked(make, docs: dict, others: list[str], fallback: Question | None = None) -> tuple[Question | None, dict]:
    """만들고 검증 → 떨어지면 1번 더 → 또 떨어지면 fallback(은행 기본 질문)"""
    q, check = None, {"ok": False}
    for attempt in (1, 2):
        q = make()
        if q is None:
            break
        check = verify(q, docs, others)
        if check["ok"]:
            return q, {**check, "시도": attempt}
    if fallback is not None:
        check = verify(fallback, docs, others)
        return fallback, {**check, "시도": "은행 기본 질문"}
    return q, check


def _bank(db, job_role: str) -> list[dict]:
    return db.execute("""SELECT id, topic, chunk_id, question_text, key_points FROM question_bank
                         WHERE job_role = %s AND verified ORDER BY id""", (job_role,)).fetchall()


def _from_bank(ctx: QuestionContext, b: dict, doc: CompanyDoc) -> Question:
    """은행 질문 → 이 지원자 이력서에 맞게 다듬기 (실제 모듈: LLM, 가짜: 은행 질문 그대로)"""
    base = Question(kind="tech", tech_stack=b["topic"], question_text=b["question_text"], basis=f"질문 은행 #{b['id']} × {doc.chunk_id}",
                    source_doc_ids=[doc.chunk_id], min_tier=3, key_points=b["key_points"], model="bank",
                    defense={"검색": {"query": "이력서 경험 (질문 은행)"}})
    if M.MODE == "stub":
        return base
    from api import real_modules as R
    q, _ = R._write(ctx, base, "pregen_main", "tech_main",
                    {"weakness": f"회사 질문 은행의 기본 질문: {b['question_text']}\n이 질문의 뜻은 유지하고 지원자 이력서와 이어지게 다듬으세요.",
                     "evidence": doc.body[:1500], "resume": R._resume(ctx, 1200)}, doc.forbid or [])
    return q


def prepare(db, app_id: int, mains: bool = True) -> dict:
    """1차 합격 즉시: 1·2번 + 기술 본 질문 후보(4~10번). 이미 만든 칸은 그대로 (결정을 바꿔 다시 합격해도 한 번만).
    mains=False면 1·2번만 (면접 직전에 처음 만드는 옛·시드 지원 건: 본 질문은 뒤에서 따로)"""
    have = {r["slot"] for r in db.execute("SELECT slot FROM prepared_question WHERE application_id = %s", (app_id,)).fetchall()}
    if {1, 2, *(MAIN_SLOTS if mains else ())} <= have:
        return {"made": 0}
    ctx = context(db, app_id)
    docs = {d.chunk_id: d for d in ctx.docs}
    others: list[str] = [r["question_text"] for r in db.execute("SELECT question_text FROM prepared_question WHERE application_id = %s",
                                                                 (app_id,)).fetchall()]
    made = 0
    for slot, fn in ((1, M.q1_verify), (2, M.q2_value)):
        if slot not in have:
            q, check = _checked(lambda f=fn: f(ctx), docs, others)
            _save(db, app_id, slot, q, check)
            others.append(q.question_text)
            made += 1
    bank = [b for b in _bank(db, ctx.job_role) if b["chunk_id"] in docs] if mains else []
    if bank:                                          # 은행 질문을 이력서 경험으로 Hybrid 검색해 순서를 정한다
        order = retrieve.rank(retrieve.experience_query(ctx.resume_text), [docs[b["chunk_id"]] for b in bank])
        by = {b["chunk_id"]: b for b in bank}
        bank = [by[h.doc.chunk_id] for h in order]
    for slot, b in zip([s for s in MAIN_SLOTS if s not in have], bank):
        doc = docs[b["chunk_id"]]
        plain = Question(kind="tech", tech_stack=b["topic"], question_text=b["question_text"], basis=f"질문 은행 #{b['id']} × {doc.chunk_id}",
                         source_doc_ids=[doc.chunk_id], min_tier=3, key_points=b["key_points"], model="bank")
        q, check = _checked(lambda b=b, doc=doc: _from_bank(ctx, b, doc), docs, others, fallback=plain)
        _save(db, app_id, slot, q, check, b["id"])
        others.append(q.question_text)
        made += 1
    return {"made": made}


def prepare_q3(db, app_id: int) -> dict:
    """코딩이 끝나는 즉시: 3번(코딩 약점 본 질문)을 만들고 검증. 대역(ct_band)도 이때 알게 된다"""
    c = db.execute("""SELECT cr.weakness_summary, cr.q3_tier FROM coding_session cs JOIN coding_result cr ON cr.session_id = cs.id
                      WHERE cs.application_id = %s AND cs.status = 'completed' ORDER BY cs.attempt_no DESC LIMIT 1""", (app_id,)).fetchone()
    ctx = context(db, app_id, c["weakness_summary"] if c else None, engine.CT_BAND.get(c["q3_tier"]) if c else None)
    docs = {d.chunk_id: d for d in ctx.docs}
    others = [r["question_text"] for r in db.execute("SELECT question_text FROM prepared_question WHERE application_id = %s AND slot <> 3",
                                                      (app_id,)).fetchall()]
    q, check = _checked(lambda: M.tech_main(ctx, []), docs, others)
    if q is None:
        return {"made": 0}
    _save(db, app_id, 3, q, check)
    return {"made": 1, "ok": check["ok"]}


# ---------- 면접에서 쓰기 ----------

def _to_q(r: dict) -> Question:
    return Question(kind=r["kind"], tech_stack=r["tech_stack"], question_text=r["question_text"], basis=r["basis"] or "-",
                    source_doc_ids=r["source_doc_ids"] or [], min_tier=r["min_tier"], key_points=r["key_points"], model=r["model"],
                    defense={"사전 생성": {"칸": r["slot"], "검증": "통과", "bank_id": r["bank_id"]}})


def first_three(db, app_id: int, ctx: QuestionContext) -> list[Question]:
    """면접 setup: 미리 만든 1·2·3번(검증 통과)을 쓰고, 없거나 떨어진 칸만 지금 만든다 (시드 지원 건·옛 지원 건)"""
    if not db.execute("SELECT 1 FROM prepared_question WHERE application_id = %s AND slot IN (1, 2)", (app_id,)).fetchone():
        prepare(db, app_id, mains=False)             # 1차 때 미리 만들지 못한 지원 건: 1·2번만 지금, 본 질문 후보는 뒤에서 (준비 시간 60초 안)
        from worker.tasks import prepare_questions
        prepare_questions.delay(app_id)
    if not db.execute("SELECT 1 FROM prepared_question WHERE application_id = %s AND slot = 3", (app_id,)).fetchone():
        prepare_q3(db, app_id)
    ready = {r["slot"]: _to_q(r) for r in db.execute("""SELECT * FROM prepared_question WHERE application_id = %s AND slot <= 3
                                                         AND status = 'ready'""", (app_id,)).fetchall()}
    live = {1: lambda: M.q1_verify(ctx), 2: lambda: M.q2_value(ctx), 3: lambda: M.tech_main(ctx, [])}
    return [ready.get(i) or live[i]() for i in (1, 2, 3)]


def next_main(db, app_id: int, used: list[str]) -> Question | None:
    """면접 중 다음 주제 본 질문: 미리 만든 4~10번 중 아직 안 쓴 근거의 첫 칸. 없으면 None (그래프가 지금 만든다)"""
    for r in db.execute("""SELECT * FROM prepared_question WHERE application_id = %s AND slot >= 4 AND status = 'ready'
                           ORDER BY slot""", (app_id,)).fetchall():
        if not set(r["source_doc_ids"] or []) & set(used):
            return _to_q(r)
    return None
