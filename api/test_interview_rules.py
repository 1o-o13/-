"""면접 TRD 3.7~3.9를 엔진에 적용한 것: 꼬리 체인 2회, 모름·깊이 미측정 표시, 꼬리질문 모순 검사 1회 수정 (DB 없이)"""
from api import modules as M
from api.interview import engine
from contracts import Handoff, Question, QuestionContext


def row(n, qtype="main", depth=0, score=85.0, kind="tech", topic="t", relevance=0.9):
    return {"ask_order": n, "kind": kind, "question_type": qtype, "depth": depth, "score": score, "status": "ok",
            "relevance": relevance, "tech_stack": topic}


def head():
    return [row(1, kind="non_tech", score=None, topic=None), row(2, kind="non_tech", score=None, topic=None)]


def test_third_chain_not_started():
    """주제 두 개가 꼬리질문까지 갔으면, 세 번째 주제는 잘 답해도 꼬리 없이 다음 주제"""
    rows = head() + [row(3, topic="a"), row(4, "followup", 1, topic="a"), row(5, topic="b"), row(6, "followup", 1, 50, topic="b"),
                     row(7, topic="c")]
    assert engine.action(rows) == "next_topic"
    assert engine.action(rows[:5]) == "followup"                                  # 두 번째 체인 시작은 허용


def test_marks_unknown_and_unmeasured():
    rows = head() + [row(3, score=20, topic="a"), row(4, "reask", 0, 50, topic="a"),       # 재질문 뒤 50 → 모름
                     row(5, topic="b"), row(6, "followup", 1, 80, topic="b"), row(7, "followup", 2, 60, topic="b"),
                     row(8, score=55, topic="c"), row(9, score=45, topic="d"), row(10, score=90, topic="e")]  # 10번 90점, 꼬리 못 감
    marks = {m["topic"]: m["mark"] for m in engine.topic_marks(rows)}
    assert marks == {"a": "모름", "b": None, "c": None, "d": None, "e": "깊이 미측정"}
    assert engine.topic_marks(rows[:-1] + [row(10, score=60, topic="e")])[-1]["mark"] is None   # 70 미만이면 표시 없음


def test_followup_fixed_once_then_low_confidence(monkeypatch):
    ctx = QuestionContext(application_id=1, job_role="백엔드", resume_text="", docs=[],
                          handoff=Handoff(job_role="백엔드", applied_level="신입", deficit_value="COL", deficit_reason="-"))
    q = Question(kind="tech", question_type="followup", depth=1, tech_stack="t", question_text="꼬리 질문", basis="b", key_points=["방법"],
                 model="stub")
    verdicts = iter([{"verdict": "fail", "by": "nli", "entailment": 0.2, "contradiction": 0.5},
                     {"verdict": "pass", "by": "nli", "entailment": 0.8, "contradiction": 0.0}])
    monkeypatch.setattr(M, "check_followup", lambda *_: next(verdicts))
    out = engine.guard(ctx, q, "방법을 설명했습니다")
    assert out.defense["fixed"] and out.defense["nli"]["verdict"] == "pass" and "low_confidence" not in out.defense
    verdicts = iter([{"verdict": "fail", "by": "nli", "entailment": 0.1, "contradiction": 0.6},
                     {"verdict": "fail", "by": "nli", "entailment": 0.4, "contradiction": 0.35}])
    out = engine.guard(ctx, q, "방법을 설명했습니다")
    assert out.defense["low_confidence"] and out.defense["nli"]["entailment"] == 0.4      # 함의 − 모순이 높은 수정본
