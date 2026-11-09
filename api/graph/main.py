"""메인 그래프 — 지원 건 1개 = thread 1개 (thread_id = 'app-{application_id}', PostgresSaver). 활동다이어그램 1109 6쪽.
순서만 책임지는 코드이고, LLM은 서브그래프(S0 score, S2·S3 = api/graph/interview.py) 안에만 있다.
[사람 판단]·[외부 대기]에서 interrupt로 멈추고 같은 thread_id로 재개한다.

  S0: retrieve → score → verify (api/screen.run) → hr_screen [사람 판단 1] → save_decision ─┬ pass → handoff → wait_invite
                                                                                                     ├ hold → hr_screen (다시 대기)
                                                                                                     └ reject → END
  wait_invite [외부 대기 1: 담당관이 '1차 결과 발표'로 응시 안내 발송] → wait_access [외부 대기 2: 지원자 접속]
  → wait_ct2 [외부 대기 3: 코딩 1·2번 제출 종료] → s1 (코딩 3번 준비) → wait_ct_end [외부 대기 4: 3번 종료]
  → device_check [외부 대기 5: 점검·본인 확인 → S2 시작] → interview [S2·S3 thread가 끝나기를 기다림]
  → final [사람 판단 2: 회사 담당자의 최종 선발] → END

- 코딩이 없는 직군이면 wait_access 다음 바로 device_check
- 그래프가 생기기 전에 만든 지원 건(시드)은 처음 재개할 때 그 단계에서 thread를 만든다 (entry)
- 재개 값에 phase를 넣고 확인한다: 늦게 온 코딩 사건이 면접 단계 thread를 재개하는 사고 방지 (규칙 ②)
- 판정 결과는 모두 AI 추천이며 합격·불합격 확정은 사람이 한다
"""
import logging
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from api import screen
from api.db import connect
from api.graph.checkpoint import gate, saver

GRAPH_VERSION = "main-2026-11-09"
log = logging.getLogger(__name__)
WAITS = ("hr_screen", "wait_invite", "wait_access", "wait_ct2", "wait_ct_end", "device_check", "interview", "final")
Phase = Literal["hr_screen", "wait_invite", "wait_access", "wait_ct2", "wait_ct_end", "device_check", "interview", "final"]


class S(TypedDict, total=False):
    graph_version: str
    application_id: int
    entry: str                  # 시드 지원 건: 이 단계부터
    decision: str | None        # 최근 담당관 결정 pass·reject·hold
    decided_by: int | None
    reason: str | None
    coding: bool                # 코딩 테스트가 있는 직군
    session_id: int | None      # 2차 응시 (S2 thread)
    redecide: bool              # 발송 전 결정을 다시 함


class ResumeIn(BaseModel):      # 재개 값 (규칙 ③ pydantic 검증)
    phase: Phase
    graph_version: str
    decision: Literal["pass", "reject", "hold"] | None = None
    admin_id: int | None = None
    reason: str | None = None
    session_id: int | None = None


def _cfg(app_id: int) -> dict:
    return {"configurable": {"thread_id": f"app-{app_id}"}}


def _wait(s: S, phase: str, **info) -> ResumeIn:
    """외부 사건·사람 판단 대기 (부작용 없음, 규칙 ①). 다른 단계의 재개 값이면 거부"""
    v = ResumeIn(**interrupt({"phase": phase, "graph_version": s["graph_version"], "application_id": s["application_id"], **info}))
    if v.phase != phase or v.graph_version != s["graph_version"]:
        raise ValueError(f"재개 값이 이 단계({phase})와 맞지 않음: {v.phase}")
    return v


# ---------- 노드 ----------

def route_in(s: S) -> S:
    with connect() as db:
        dev = db.execute("""SELECT p.job_category = 'dev' AS coding FROM application a JOIN job_posting p ON p.id = a.posting_id
                            WHERE a.id = %s""", (s["application_id"],)).fetchone()
    return {"coding": dev["coding"]}


def entry(s: S) -> str:
    return s.get("entry") or "s0_score"


def s0_score(s: S) -> S:
    """retrieve(비교 4개) → score(LLM 의견) → verify(코드)  (api/screen.run)"""
    with connect() as db:
        screen.run(db, s["application_id"])
    return {}


def hr_screen(s: S) -> S:
    """사람 판단 1: 담당관의 1차 결정 pass·reject·hold + 결정자(필수) + 사유"""
    v = _wait(s, "hr_screen")
    if v.admin_id is None:
        raise ValueError("결정자가 없습니다")
    return {"decision": v.decision, "decided_by": v.admin_id, "reason": v.reason}


def save_decision(s: S) -> S:
    """한 트랜잭션: 결정 기록(쌓기만, audit_log) → 최근 결정 pass·reject는 stage_result에, hold는 지움(= 아직 안 정함).
    지원서 상태는 발표 때 코드가 바꾼다"""
    app_id, d = s["application_id"], s.get("decision")
    by, reason = s.get("decided_by"), s.get("reason")
    with connect() as db, db.transaction():
        db.execute("""INSERT INTO audit_log(actor_type, actor_id, action, target_type, target_id, detail)
                      VALUES ('admin', %s, 'screen_decision', 'application', %s, %s)""",
                   (by, app_id, Jsonb({"decision": d, "reason": reason})))
        if d == "hold":
            db.execute("DELETE FROM stage_result WHERE application_id = %s AND stage = 'document'", (app_id,))
        else:
            db.execute("""INSERT INTO stage_result(application_id, stage, result, reason, decided_by) VALUES (%s, 'document', %s, %s, %s)
                          ON CONFLICT (application_id, stage) DO UPDATE SET result = EXCLUDED.result, reason = EXCLUDED.reason,
                              decided_by = EXCLUDED.decided_by, decided_at = now()""",
                       (app_id, "pass" if d == "pass" else "fail", reason, by))
    return {}


def after_decision(s: S) -> str:
    return {"pass": "handoff", "reject": END}.get(s.get("decision") or "hold", "hr_screen")


def handoff(s: S) -> S:
    """합격 후 단계: 면접 확인 필요 목록 + 결핍 가치 → handoff → 2차 질문 미리 생성·검증. 결핍 가치는 LLM으로 원문 근거를
    확인해 수 초 걸리므로 worker에 맡긴다 (담당관이 '합격'을 누를 때 기다리지 않게, 11/10)"""
    from worker.tasks import handoff_and_prepare
    handoff_and_prepare.delay(s["application_id"])
    return {}


def wait_invite(s: S) -> S:
    """외부 대기 1: 담당관이 '1차 결과 발표'로 응시 안내를 직접 발송 (자동 발송 없음). 발송 전이면 담당관이 결정을 다시 할 수 있다
    (결정은 쌓기만 함 → save_decision으로 돌아감)"""
    v = _wait(s, "wait_invite")
    if v.decision:
        if v.admin_id is None:
            raise ValueError("결정자가 없습니다")
        return {"decision": v.decision, "decided_by": v.admin_id, "reason": v.reason, "redecide": True}
    return {"redecide": False}


def after_invite(s: S) -> str:
    return "save_decision" if s.get("redecide") else "wait_access"


def wait_access(s: S) -> S:
    _wait(s, "wait_access")
    return {}


def after_access(s: S) -> str:
    return "wait_ct2" if s.get("coding", True) else "device_check"


def wait_ct2(s: S) -> S:
    _wait(s, "wait_ct2")
    return {}


def s1(s: S) -> S:
    """코딩 3번 준비 (등급 → 리뷰 → 검색 → 출제 → 교차 검증 → 대체). 채점 서버 쪽 코드(api/coding)가 하고, 여기서는 순서만"""
    return {}


def wait_ct_end(s: S) -> S:
    _wait(s, "wait_ct_end")
    return {}


def device_check(s: S) -> S:
    v = _wait(s, "device_check")
    return {"session_id": v.session_id}


def interview(s: S) -> S:
    """S2(화상 면접)·S3(AI 평가관)는 응시마다 thread 's2-{session_id}'에서 돈다 (재응시 최대 3차). 그 결과가 확정되면 재개"""
    v = _wait(s, "interview", session_id=s.get("session_id"))
    return {"session_id": v.session_id or s.get("session_id")}


def final(s: S) -> S:
    """사람 판단 2: 회사 담당자의 최종 선발 (합격·예비·불합격 확정 화면이 재개)"""
    _wait(s, "final")
    return {}


def build():
    g = StateGraph(S)
    nodes = {"route_in": route_in, "s0_score": s0_score, "hr_screen": hr_screen, "save_decision": save_decision, "handoff": handoff,
             "wait_invite": wait_invite, "wait_access": wait_access, "wait_ct2": wait_ct2, "s1": s1, "wait_ct_end": wait_ct_end,
             "device_check": device_check, "interview": interview, "final": final}
    for k, fn in nodes.items():
        g.add_node(k, fn)
    g.add_edge(START, "route_in")
    g.add_conditional_edges("route_in", entry, ["s0_score", *WAITS])
    g.add_edge("s0_score", "hr_screen")
    g.add_edge("hr_screen", "save_decision")
    g.add_conditional_edges("save_decision", after_decision, ["handoff", "hr_screen", END])
    g.add_edge("handoff", "wait_invite")
    g.add_conditional_edges("wait_invite", after_invite, ["save_decision", "wait_access"])
    g.add_conditional_edges("wait_access", after_access, ["wait_ct2", "device_check"])
    g.add_edge("wait_ct2", "s1")
    g.add_edge("s1", "wait_ct_end")
    g.add_edge("wait_ct_end", "device_check")
    g.add_edge("device_check", "interview")
    g.add_edge("interview", "final")
    g.add_edge("final", END)
    return g.compile(checkpointer=saver())


_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build()
    return _graph


def waiting(app_id: int) -> str | None:
    """지금 멈춰 있는 단계 (thread가 없거나 끝났으면 None)"""
    for t in graph().get_state(_cfg(app_id)).tasks:
        for i in t.interrupts:
            return i.value.get("phase")
    return None


def start_s0(app_id: int) -> str | None:
    """1차 평가 시작 (접수 마감 뒤 일괄): S0 → hr_screen에서 멈춤. 이미 시작했으면 그대로"""
    with gate, connect() as db:
        db.execute("SELECT pg_advisory_lock(1, %s)", (app_id,))
        try:
            if not graph().get_state(_cfg(app_id)).values:
                graph().invoke({"graph_version": GRAPH_VERSION, "application_id": app_id}, _cfg(app_id))
        finally:
            db.execute("SELECT pg_advisory_unlock(1, %s)", (app_id,))
    return waiting(app_id)


def advance(app_id: int, phase: str, **payload) -> bool:
    """그 단계에서 기다리는 thread를 재개. thread가 없으면(그래프 전 시드 지원 건) 그 단계에서 만든 뒤 재개.
    다른 단계에서 기다리고 있으면 무시하고 False (늦게 온 사건). 그래프 오류로 화면 요청을 실패시키지 않는다"""
    try:
        with gate, connect() as db:
            db.execute("SELECT pg_advisory_lock(1, %s)", (app_id,))
            try:
                if not graph().get_state(_cfg(app_id)).values:
                    graph().invoke({"graph_version": GRAPH_VERSION, "application_id": app_id, "entry": phase}, _cfg(app_id))
                for _ in WAITS:                      # 앞 단계 대기(그래프 밖에서 이미 지남, 예: 시드의 코딩 완료)는 '지남'으로 넘김. 사람 판단은 못 넘김
                    now = waiting(app_id)
                    if now == phase or now not in WAITS or now == "hr_screen" or WAITS.index(now) > WAITS.index(phase):
                        break
                    log.info("app-%s: %s 대기를 지남으로 넘김 (%s 사건)", app_id, now, phase)
                    graph().invoke(Command(resume={"phase": now, "graph_version": GRAPH_VERSION}), _cfg(app_id))
                if waiting(app_id) != phase:
                    log.info("app-%s: %s 사건 무시 (지금 단계 %s)", app_id, phase, waiting(app_id))
                    return False
                graph().invoke(Command(resume={"phase": phase, "graph_version": GRAPH_VERSION, **payload}), _cfg(app_id))
                return True
            finally:
                db.execute("SELECT pg_advisory_unlock(1, %s)", (app_id,))
    except Exception:                                # noqa: BLE001  순서 기록 실패로 지원자·담당자 요청을 막지 않는다
        log.exception("app-%s: %s 재개 실패", app_id, phase)
        return False
