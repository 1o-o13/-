"""다음 질문 결정. 진행 규칙은 app_6_1/flow.next_action()만 쓰고, 질문 생성은 api/modules.py를 거친다. DB를 모르는 순수 함수."""
from concurrent.futures import ThreadPoolExecutor

from contracts import Judgement, Question, QuestionContext
from flow import next_action

from api import modules as M

CT_BAND = {"골드2": "상", "골드3": "상", "골드4": "중", "골드5": "하", "실버1": "하"}   # 코딩 q3_tier → 난이도 대역
LEVEL = {"new": "신입", "junior": "주니어", "senior": "시니어"}                          # job_posting.career_level → 문서 level
DEPT = {"백엔드": "BE", "프론트엔드": "FE", "AI": "AI", "데이터": "DATA", "임베디드": "EMB"}  # 임시: job_role → 문서 dept (팀 미정)


def prepare(ctx: QuestionContext) -> list[Question]:
    """면접 앞(CAN-011)에 미리 만드는 1~3번: 이력서 확인, 결핍 가치, 첫 기술 질문(코딩 약점)"""
    with ThreadPoolExecutor(3) as ex:          # 실제 모듈은 LLM 3번 → 동시에 (준비 시간 ≈ 가장 느린 하나)
        f = [ex.submit(M.q1_verify, ctx), ex.submit(M.q2_value, ctx), ex.submit(M.tech_main, ctx, [])]
        return [x.result() for x in f]


def _chains(rows: list[dict]) -> list[list[dict]]:
    """기술 문항을 주제 묶음으로: 본 질문 하나 + 그 뒤 꼬리·재질문. rows = 물어본 순서대로 {kind, question_type, depth, ...}"""
    out: list[list[dict]] = []
    for r in rows:
        if r["kind"] != "tech":
            continue
        if r["question_type"] == "main" or not out:
            out.append([])
        out[-1].append(r)
    return out


def action(rows: list[dict], total: int = 10, follow: int = 70, retry: int = 40, max_depth: int = 2) -> str:
    """마지막 문항 다음에 할 일 (next_action). rows 한 줄 = {kind, question_type, depth, score, status, relevance}"""
    r, chains = rows[-1], _chains(rows)
    retried = r["kind"] == "tech" and any(x["question_type"] == "reask" for x in chains[-1])
    used = sum(any(x["question_type"] == "followup" for x in c) for c in chains)   # 꼬리질문까지 간 주제 수 (FR-74)
    return next_action(r["kind"], r["depth"], r["score"], r["status"], retried, len(rows), total, follow, retry, max_depth,
                       question_type=r["question_type"], relevance=r.get("relevance"), chains_used=used)


def topic_marks(rows: list[dict], total: int = 10, follow: int = 70, retry: int = 40, max_depth: int = 2) -> list[dict]:
    """기술 주제별 표시 (관리자 화면). 모름 = 재질문 뒤 70점 미만으로 다음 주제 (3.7) /
    깊이 미측정 = 10문항이 끝나 꼬리질문으로 더 못 간 주제 (3.9, 마지막 주제만 해당)"""
    out = []
    chains = _chains(rows)
    for i, c in enumerate(chains):
        last, mark = c[-1], None
        if last["question_type"] == "reask" and (last["status"] != "ok" or last["score"] is None or last["score"] < follow):
            mark = "모름"
        elif i == len(chains) - 1 and len(rows) >= total and action(rows, total + 1, follow, retry, max_depth) == "followup":
            mark = "깊이 미측정"
        out.append({"topic": c[0]["tech_stack"], "orders": [x["ask_order"] for x in c],
                    "depth": max(x["depth"] for x in c), "mark": mark})
    return out


def guard(ctx: QuestionContext, q: Question, stt: str) -> Question:
    """guard 노드 (FR-77, 활동다이어그램 1109 4쪽): 꼬리질문만 모순 검사. 통과 못 하면 1번 고치고(followup_fix),
    또 못 하면 NLI 점수(함의 − 모순)가 높은 쪽을 '신뢰도 낮음'으로 낸다. 금지어 검사는 질문을 쓸 때 이미 함"""
    if q.question_type != "followup":
        return q
    c1 = M.check_followup(q, stt, ctx)
    if c1["verdict"] == "pass":
        return q.model_copy(update={"defense": {**q.defense, "nli": c1}})
    fixed = M.fix_followup(ctx, q, stt, c1)
    c2 = M.check_followup(fixed, stt, ctx)
    if c2["verdict"] == "pass":
        return fixed.model_copy(update={"defense": {**fixed.defense, "nli": c2, "fixed": True, "first": c1}})
    gap = lambda c: (c.get("entailment") or 0) - (c.get("contradiction") or 0)
    best, c = (fixed, c2) if gap(c2) >= gap(c1) else (q, c1)
    return best.model_copy(update={"defense": {**best.defense, "nli": c, "fixed": True, "low_confidence": True,
                                               "comment": "NLI 수치가 낮아 신뢰도 낮음"}})


def generate(ctx: QuestionContext, asked: list[tuple[Question, Judgement, str | None]], act: str, follow: int = 70) -> Question | None:
    """generate 노드: decide가 정한 종류의 다음 질문 (guard 전). 1~3번은 prepare가 만든 것을 쓰므로 None"""
    q, j, stt = asked[-1]
    if act == "end" or len(asked) < 3:
        return None
    if act == "followup":
        return M.tech_followup(ctx, q, stt or "")
    if act == "retry":
        reason = "off_target" if j.score is not None and j.score >= follow else "low"   # ≥70 & CE < 0.4 → 범위를 좁혀서
        return M.tech_retry(q, ctx, stt or "", reason)
    used = [c for x, _, _ in asked if x.kind == "tech" and x.question_type == "main" for c in x.source_doc_ids]   # 쓴 본 질문 섹션
    return M.tech_main(ctx, used)


def decide(ctx: QuestionContext, asked: list[tuple[Question, Judgement, str | None]],
           total: int = 10, follow: int = 70, retry: int = 40, max_depth: int = 2) -> tuple[str, Question | None]:
    """asked = 물어본 순서대로 (질문, 판정, STT). 반환 (next_action 결과, 다음 질문). 1~3번은 prepare가 만든 것을 쓴다.
    (그래프 밖에서 한 번에: decide → generate → guard. 면접 그래프는 노드로 나눠 부른다)"""
    rows = [{"kind": x.kind, "question_type": x.question_type, "depth": x.depth, "score": y.score, "status": y.status,
             "relevance": y.relevance} for x, y, _ in asked]
    act = action(rows, total, follow, retry, max_depth)
    q = generate(ctx, asked, act, follow)
    return act, (guard(ctx, q, asked[-1][2] or "") if q else None)
