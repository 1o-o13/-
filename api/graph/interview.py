"""화상 면접 그래프 S2 + AI 평가관 S3 (활동다이어그램 1109 4·6쪽, LangGraph 아키텍처 v0.1).

  setup → generate → guard → ask(interrupt) → evaluate → save → decide ─┬→ generate …          (10문항까지)
                                                                          └→ finish → context_batch → load → checks → judge → report → hr_decide(interrupt)

- 응시 1회 = thread 1개 (thread_id = 's2-{session_id}'). 재응시(최대 3차)는 새 응시라 새 thread. 메인 그래프(api/graph/main.py)는
  지원 건 thread에서 이 thread가 끝나기를 기다린다 (지원 건 1개 = 메인 thread 1개)
- 사람의 답은 ask(interrupt)에서만 들어온다. 재개 값은 pydantic으로 검증하고 phase·graph_version을 확인한다 (구현 규칙 ②③④)
- interrupt 노드(ask·hr_decide)에는 부작용을 두지 않는다 (재개하면 처음부터 다시 실행, 규칙 ①). 질문 저장·표시는 guard에서
- 판단은 사람, DB 쓰기·상태 변경은 코드(노드), 글은 LLM(api/modules.py). 진행 결정은 app_6_1/flow.next_action()만
- 오류가 나도 면접은 멈추지 않는다: 판정 실패 → 점수 보류(parse_error) + 다음 주제, STT 실패 → no_stt + 다음 주제
"""
import logging
import time
from typing import Literal, TypedDict

import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from api import modules as M
from api import pregen
from api.db import connect
from api.graph.checkpoint import gate, saver
from api.interview import engine, store, voice

# isort: split
from contracts import Judgement, Question, Turn  # stubs_6_1 경로는 api.modules가 연다

GRAPH_VERSION = "s2-2026-11-09"
log = logging.getLogger(__name__)


class S(TypedDict, total=False):
    graph_version: str
    session_id: int
    application_id: int
    n: int                      # 판정까지 끝난 문항 수
    action: str                 # decide 결과: followup·retry·next_topic·end·stopped
    pending: dict | None        # generate가 만든 다음 질문 (guard 전)
    qid: int | None             # 지금 묻는 문항 id
    answer_id: int | None
    stt_failed: bool
    judgement: dict | None
    evaluation_id: int | None
    paths: list[str]            # 쓴 대체 경로 (관리자 화면·리포트에 표시)


class AnswerIn(BaseModel):      # ask 재개 값
    phase: Literal["interview"]
    graph_version: str
    answer_id: int
    stt_failed: bool = False


class DecisionIn(BaseModel):    # hr_decide 재개 값
    phase: Literal["hr_decide"]
    graph_version: str
    decision: Literal["confirmed"]
    admin_id: int


def _cfg(sid: int) -> dict:
    return {"configurable": {"thread_id": f"s2-{sid}"}}


# ---------- S2 노드 ----------

def setup(s: S) -> S:
    """RDB에서 handoff·약점·난이도·공고를 다시 읽고(store.context), 1~3번 질문을 미리 만든다 (CAN-011 준비 시간)"""
    sid = s["session_id"]
    with connect() as db:
        if not db.execute("SELECT 1 FROM interview_question WHERE session_id = %s", (sid,)).fetchone():
            qs = pregen.first_three(db, s["application_id"], store.context(db, sid))   # 미리 만들고 검증한 1·2·3번 (없으면 지금)
            try:
                with db.transaction():
                    ids = [store.add_question(db, sid, q, i) for i, q in enumerate(qs, 1)]
                voice.prefetch([(i, q.question_text) for i, q in zip(ids, qs)])
            except psycopg.errors.UniqueViolation:
                pass                                 # 겹친 요청이 먼저 만들었음 (그 1~3번을 그대로 씀)
    return {"n": 0, "paths": [], "action": "next_topic"}


def generate(s: S) -> S:
    """다음 질문 종류(decide)에 맞춰 질문을 만든다. 미리 만든 1~3번이면 그대로"""
    sid, n = s["session_id"], s["n"]
    with connect() as db:
        have = db.execute("SELECT id FROM interview_question WHERE session_id = %s AND ask_order = %s", (sid, n + 1)).fetchone()
        if have:
            return {"pending": None, "qid": have["id"]}
        hist, st = store.history(db, sid), store.setting(db, sid)
        q = None
        if s["action"] == "next_topic":              # 다음 주제 본 질문: 1차 합격 때 미리 만들고 검증한 질문부터
            used = [c for h in hist if h["q"].kind == "tech" and h["q"].question_type == "main" for c in h["q"].source_doc_ids]
            q = pregen.next_main(db, s["application_id"], used)
        if q is None:
            q = engine.generate(store.context(db, sid), [(h["q"], h["j"], h["stt"]) for h in hist], s["action"], st["follow_score"])
    if q is None:                                    # 근거가 바닥남: 기본 질문 (면접은 멈추지 않음)
        last = hist[-1]["q"]
        q = last.model_copy(update={"question_type": "main", "depth": 0, "question_text": "다른 주제로 넘어가겠습니다. 최근 맡았던 기능에서 "
                                    "가장 까다로웠던 기술 문제와 해결 과정을 말씀해 주세요.", "basis": "근거 문서 없음 · 대체 질문",
                                    "source_doc_ids": [], "defense": {"경로": ["대체 질문 (근거 없음)"]}})
    return {"pending": q.model_dump(), "qid": None}


def guard(s: S) -> S:
    """꼬리질문 모순 검사·수정 → 질문 저장 → 표시(asked_at)·음성. 1번은 '시작' 때 표시하므로 여기서 표시하지 않는다"""
    sid, n = s["session_id"], s["n"]
    with connect() as db:
        if s.get("pending"):
            q = Question(**s["pending"])
            hist = store.history(db, sid)
            if q.question_type == "followup":
                q = engine.guard(store.context(db, sid), q, hist[-1]["stt"] or "")
            qid = store.add_question(db, sid, q, n + 1, None if q.question_type == "main" else hist[-1]["qid"])
            voice.make(qid, q.question_text)         # 음성을 먼저 만들고 보여 준다 → 뜨자마자 읽힘
        else:
            qid = s["qid"]
        if n >= 1:
            db.execute("UPDATE interview_question SET asked_at = coalesce(asked_at, now()) WHERE id = %s", (qid,))
    return {"qid": qid, "pending": None}


def ask(s: S) -> S:
    """외부 사건 대기: 지원자 답변(음성 → STT)이 worker를 거쳐 들어온다. 부작용 없음"""
    v = AnswerIn(**interrupt({"phase": "interview", "graph_version": s["graph_version"], "session_id": s["session_id"],
                              "ask_order": s["n"] + 1, "qid": s["qid"]}))
    if v.graph_version != s["graph_version"]:
        raise ValueError(f"그래프 판이 다름 ({v.graph_version} ≠ {s['graph_version']})")
    return {"answer_id": v.answer_id, "stt_failed": v.stt_failed}


def evaluate(s: S) -> S:
    """판정 (LLM). 실패해도 예외를 내지 않고 점수 보류로 → 면접은 계속"""
    sid = s["session_id"]
    with connect() as db:
        r = db.execute("""SELECT a.stt_text, q.* FROM interview_answer a JOIN interview_question q ON q.id = a.question_id
                          WHERE a.id = %s""", (s["answer_id"],)).fetchone()
        q, stt, ctx = store.to_question(r), r["stt_text"], store.context(db, sid)
    t0 = time.monotonic()
    try:
        j = M.judge_answer(q, stt, ctx)
    except Exception as e:
        log.exception("판정 실패 sid=%s: %s", sid, e)
        j = None
    path = []
    if j is None:
        j = Judgement(status="parse_error", quotes=[], rationale="평가 실패 — 점수 보류 (LLM 오류), 담당자 확인 필요",
                      lang_structure=0, lang_terms=0, lang_intent=0, model_tier="eval", model="rule", latency_ms=0)
        path.append(f"{r['ask_order']}번 판정 실패 → 점수 보류")
    if s.get("stt_failed"):
        j = j.model_copy(update={"status": "no_stt", "score": 0 if q.kind == "tech" else None,
                                 "rationale": "STT 실패 — 답변을 글로 바꾸지 못함 (담당자 확인 필요)"})
        path.append(f"{r['ask_order']}번 STT 실패 → 다음 주제")
    j = j.model_copy(update={"latency_ms": int((time.monotonic() - t0) * 1000)})
    if j.status not in ("ok", "parse_error") and q.kind == "tech":
        j = j.model_copy(update={"score": 0})        # 응답 상태가 ok가 아니면 기술 질문은 0점 (IV-21). 평가 실패는 보류(NULL)
    return {"judgement": j.model_dump(), "paths": s.get("paths", []) + path}


def save(s: S) -> S:
    """(응시, 문항) 덮어쓰기로 RDB 기록: 같은 답변의 이전 판정은 is_current = false"""
    with connect() as db, db.transaction():
        db.execute("UPDATE answer_judgement SET is_current = false WHERE answer_id = %s AND is_current", (s["answer_id"],))
        store.save_judgement(db, s["answer_id"], Judgement(**s["judgement"]))
    return {"judgement": None}


def decide(s: S) -> S:
    sid = s["session_id"]
    with connect() as db:
        if db.execute("SELECT status FROM interview_session WHERE id = %s", (sid,)).fetchone()["status"] != "in_progress":
            return {"action": "stopped"}             # 포기(탭 이탈 등)·관리자 중지: 그래프만 끝냄
        hist, st = store.history(db, sid), store.setting(db, sid)
    rows = [{"kind": h["q"].kind, "question_type": h["q"].question_type, "depth": h["q"].depth, "score": h["j"].score,
             "status": h["j"].status, "relevance": h["j"].relevance} for h in hist]
    act = engine.action(rows, st["total_questions"], st["follow_score"], st["retry_score"], st["followup_max_depth"])
    return {"action": act, "n": len(hist)}


def after_decide(s: S) -> str:
    return {"end": "finish", "stopped": END}.get(s["action"], "generate")


def finish(s: S) -> S:
    sid = s["session_id"]
    with connect() as db, db.transaction():
        db.execute("""UPDATE interview_session SET status = 'completed', ended_at = now(), end_reason = 'finished'
                      WHERE id = %s AND status = 'in_progress'""", (sid,))
        db.execute("UPDATE application SET status = 'stage2_done' WHERE id = %s AND status = 'stage2'", (s["application_id"],))
    return {}


def context_batch(s: S) -> S:
    """맥락 평가 (Qwen3-Embedding-8B, 면접 뒤 일괄·참고값). 이 PC에는 모델을 받지 않아(GPU 6GB) 건너뛰고 기록만.
    채점에 안 쓰고, 실패해도 면접 결과에 영향 없음 (임시)"""
    return {"paths": s.get("paths", []) + ["context_batch 건너뜀 (qwen3-embedding:8b 없음)"]}


# ---------- S3 AI 평가관 (새 검색 없음, RDB 근거만) ----------

def _turns(sid: int) -> list[Turn]:
    with connect() as db:
        return [Turn(ask_order=h["ask_order"], question=h["q"], stt_text=h["stt"], judgement=h["j"], answer_sec=h["answer_sec"],
                     finished_in_time=h["finished_in_time"], silence_ratio=h["silence_ratio"]) for h in store.history(db, sid)]


def report(s: S) -> S:
    """load → checks → judge → report: 최종 평가 v1, 5검사에 실패하면 1번 재평가(v2), 또 실패하면 담당자 알림 (IV-40).
    점수는 다시 매기지 않는다 (판정 점수로 계산)"""
    sid, turns = s["session_id"], _turns(s["session_id"])
    eid = None
    with connect() as db:
        if db.execute("SELECT 1 FROM interview_evaluation WHERE session_id = %s", (sid,)).fetchone():
            return {}                                # 다시 실행돼도 한 번만
        for version in (1, 2):
            ev = M.evaluate_interview(turns, version)
            rationale = ev.rationale + (f" · 대체 경로: {'; '.join(s.get('paths') or [])}" if s.get("paths") else "")
            with db.transaction():
                eid = db.execute("""INSERT INTO interview_evaluation(session_id, version_no, topic_scores, content_score, language_score,
                                        nonverbal_score, rationale, project_topic, fit_opinion, growth_opinion, provider, model, status)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                                 (sid, version, Jsonb(ev.topic_scores), ev.content_score, ev.language_score, ev.nonverbal_score,
                                  rationale[:2000], ev.project_topic, ev.fit_opinion, ev.growth_opinion, M.provider_of(ev.model), ev.model,
                                  ev.status)).fetchone()["id"]
                db.cursor().executemany("""INSERT INTO evaluation_check(evaluation_id, check_no, passed, detail, checker)
                                           VALUES (%s, %s, %s, %s, %s)""",
                                        [(eid, c.check_no, c.passed, c.detail, c.checker) for c in ev.checks])
            if ev.status == "passed":
                return {"evaluation_id": eid}
        failed = ", ".join(f"검사 {c.check_no} {c.detail}" for c in ev.checks if not c.passed)
        db.execute("""INSERT INTO ai_error_alert(stage, application_id, interview_evaluation_id, problem_part)
                      VALUES ('interview', %s, %s, %s)""", (s["application_id"], eid, failed))
    return {"evaluation_id": eid}


def hr_decide(s: S) -> S:
    """사람 판단 2: 담당자가 검증 통과 버전을 확정 (확정 API가 재개). AI 결과는 판정이 아니라 근거가 붙은 의견. 부작용 없음"""
    v = DecisionIn(**interrupt({"phase": "hr_decide", "graph_version": s["graph_version"], "session_id": s["session_id"],
                                "evaluation_id": s.get("evaluation_id")}))
    if v.graph_version != s["graph_version"]:
        raise ValueError("그래프 판이 다름")
    return {}


def build():
    g = StateGraph(S)
    for name, fn in (("setup", setup), ("generate", generate), ("guard", guard), ("ask", ask), ("evaluate", evaluate), ("save", save),
                     ("decide", decide), ("finish", finish), ("context_batch", context_batch), ("report", report),
                     ("hr_decide", hr_decide)):
        g.add_node(name, fn)
    g.add_edge(START, "setup")
    g.add_edge("setup", "generate")
    g.add_edge("generate", "guard")
    g.add_edge("guard", "ask")
    g.add_edge("ask", "evaluate")
    g.add_edge("evaluate", "save")
    g.add_edge("save", "decide")
    g.add_conditional_edges("decide", after_decide, ["generate", "finish", END])
    g.add_edge("finish", "context_batch")
    g.add_edge("context_batch", "report")
    g.add_edge("report", "hr_decide")
    g.add_edge("hr_decide", END)
    return g.compile(checkpointer=saver())


_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build()
    return _graph


def _waiting(sid: int) -> dict | None:
    """지금 멈춰 있는 interrupt의 값 (없으면 None)"""
    st = graph().get_state(_cfg(sid))
    for t in st.tasks:
        for i in t.interrupts:
            return i.value
    return None


def start(sid: int, app_id: int) -> None:
    """준비(CAN-011): 처음이면 그래프를 시작해 1~3번을 만들고 1번에서 멈춘다. 이미 시작했으면 아무것도 안 함 (두 번 누름·새로고침)"""
    with gate, connect() as db:
        db.execute("SELECT pg_advisory_lock(2, %s)", (sid,))
        try:
            if not graph().get_state(_cfg(sid)).values:
                graph().invoke({"graph_version": GRAPH_VERSION, "session_id": sid, "application_id": app_id}, _cfg(sid))
        finally:
            db.execute("SELECT pg_advisory_unlock(2, %s)", (sid,))


def resume_answer(sid: int, answer_id: int, stt_failed: bool = False) -> bool:
    """worker: STT가 끝난 답변으로 ask를 재개 → 판정 → 다음 질문(또는 종료·평가). 기다리는 문항이 아니면 무시 (늦게 온 사건)"""
    w = _waiting(sid)
    if not w or w.get("phase") != "interview":
        log.warning("s2-%s: 답변 %s 무시 (기다리는 단계 %s)", sid, answer_id, w and w.get("phase"))
        return False
    with gate:
        graph().invoke(Command(resume={"phase": "interview", "graph_version": w["graph_version"], "answer_id": answer_id,
                                       "stt_failed": stt_failed}), _cfg(sid))
    return True


def resume_decision(sid: int, admin_id: int) -> bool:
    """확정 API: hr_decide를 재개해 그래프를 끝낸다 (그래프 밖에서 만든 옛 응시는 없음 → 무시)"""
    w = _waiting(sid)
    if not w or w.get("phase") != "hr_decide":
        return False
    with gate:
        graph().invoke(Command(resume={"phase": "hr_decide", "graph_version": w["graph_version"], "decision": "confirmed",
                                       "admin_id": admin_id}), _cfg(sid))
    return True
