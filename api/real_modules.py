"""실제 질문 생성·판정 모듈 (MODULE_MODE=real). 가짜 모듈(stubs_6_1/fake_modules.py)과 이름·입출력이 같다.
활동다이어그램 1109 4쪽(S2)·5쪽(LLM 호출 경로) 기준.

- 모든 LLM 호출은 api/llm_gate.call() 한 곳: 프롬프트 파일(api/prompts) · 경로(tier 1·2 → 사내) · 누출 검사 · 호출 기록
- 근거 = 메타 필터(load_docs) → Hybrid(BM25 ∥ bge-m3) → RRF 순위 그대로 상위 k (본 질문 1·꼬리 2). 절대 점수 관문·CE 없음 (api/retrieve.py)
  본 질문 질의 = 이력서 경험 서술(3번은 코딩 약점 요약), 꼬리 질의 = 직전 답변 원문, 재질문 = 검색 없이 같은 근거
- guard: 꼬리질문은 인용 확인 → NLI 모순 ≥ 0.3 탈락 → 함의 ≥ 0.6 통과 → 애매하면 사내 LLM(fit_judge). 탈락하면 1번 고치고,
  또 탈락이면 NLI 점수가 높은 쪽 + '신뢰도 낮음'. 모든 질문은 금지어 검사 (1번 고쳐 쓰고, 남으면 코드가 가림)
- evaluate: 루브릭 100점(정확성 30·회사 적용 30·깊이 25·구체성 15), 이유 먼저·점수 나중. 인용은 원문에 있는 것만.
  모든 기술 답변에 CE(질문, 답변) 기록 — 점수에 안 더하고 분기 근거로만
- 오류가 나도 면접은 멈추지 않는다: 질문 실패 → 고정 기본 질문, 판정 실패 → 점수 '보류'(parse_error) + 다음 주제.
  쓴 경로는 Question.defense['경로'] / Judgement.rationale에 남겨 관리자 화면에 보인다
"""
from __future__ import annotations

import logging
import os
import re
from typing import Annotated

import fake_modules as F
from contracts import (
    Check,
    CompanyDoc,
    Evaluation,
    Judgement,
    Question,
    QuestionContext,
    Turn,
)
from pydantic import BaseModel, Field

from api import llm_gate as G
from api import nli_client, retrieve

ECHO = ("만드세요", "문항:", "질문을 하나", "하세요.", "[가린 이력서]", "지원자에게 읽어 줄", "마세요", "자 이내", "구어체",
        "약점이 있는지", "약점을 확인", "확인해 보세요", "알려주세요", "코딩 테스트 약점", "회사 문서", "PRJ-", "INC-", "#s")   # 지시문 베끼기 표시 (작은 모델)
log = logging.getLogger(__name__)
VALUES = {"OWN": "주인의식", "COL": "협업", "INT": "정직", "CUS": "고객 중심", "GRW": "성장"}   # seed/corpus_6_1/09_인재상.md (TAL-01)
NLI_CONTRA, NLI_ENTAIL = 0.3, 0.6   # Q-24 닫음 (648문항 실측)
NONE = "(없음)"


class QOut(BaseModel):
    question_text: str = Field(description="지원자에게 읽어 줄 질문 (150자 이내)")
    key_points: list[str] = Field(description="좋은 답에 들어가야 할 핵심 요소 2~4개 (각 15자 이내)")
    basis: str = Field(description="이 질문을 낸 근거 한 줄 (관리자용)")


class QFollow(QOut):
    premise: str = Field(description="이 질문이 지원자 답변에서 전제로 삼는 내용을 평서문 한 문장으로")
    quote: str = Field(description="질문의 바탕이 된 지원자 답변 구절 (답변에 있는 그대로 복사)")


class JTech(BaseModel):                      # 근거를 먼저 쓰고 점수를 나중에 매기게 칸 순서를 둔다 (이유 먼저·점수 나중)
    rationale: str = Field(description="답변에서 맞게 말한 것과 빠진 것을 두세 문장으로 (관리자용)")
    strengths: str = Field(description="좋았던 점 한 문장. 없으면 '없음'")
    weaknesses: str = Field(description="부족한 점 한 문장")
    quotes: list[str] = Field(description="점수 근거가 된 답변 원문 구절 1~3개 (답변에 있는 그대로 복사, 질문 문장은 넣지 않음)")
    accuracy: int = Field(ge=0, le=30, description="정확성 0~30")
    company_fit: int = Field(ge=0, le=30, description="회사 적용 0~30: 근거 문서의 상황에 맞게 답했는가")
    depth: int = Field(ge=0, le=25, description="문제 해결 깊이 0~25: 원인·대안·한계까지 설명했는가")
    specificity: int = Field(ge=0, le=15, description="구체성 0~15: 수치·예시·절차")
    lang_structure: int = Field(ge=0, le=10, description="말의 구조 0~10")
    lang_terms: int = Field(ge=0, le=10, description="용어 정확성 0~10")
    lang_intent: int = Field(ge=0, le=10, description="질문 의도 부합 0~10")


class JNonTech(BaseModel):
    opinion: str = Field(description="답변에서 드러난 지원자에 대한 의견 두세 문장 (점수 없음)")
    matches_resume: bool = Field(description="답변이 이력서 내용과 맞는가 (1번 문항), 2번은 가치를 보여 주는 경험이 있는가")
    to_check: str = Field(description="다음 전형에서 확인할 점 한 문장")
    quotes: list[str] = Field(description="근거가 된 답변 원문 구절 1~2개 (답변에 있는 그대로 복사)")
    lang_structure: int = Field(ge=0, le=10)
    lang_terms: int = Field(ge=0, le=10)
    lang_intent: int = Field(ge=0, le=10)
    rationale: str = Field(description="의견 근거 한두 문장")


class JTechLocal(JTech):
    """사내 모델용 (llm_gate.LOCAL_SCHEMA): 글 칸 최대 길이를 생성 단계에서 강제 → 출력 제한에 잘리지 않음 (11/16)"""
    rationale: str = Field(max_length=200, description="답변에서 맞게 말한 것과 빠진 것을 두 문장으로 (200자 안)")
    strengths: str = Field(max_length=80, description="좋았던 점 한 문장. 없으면 '없음'")
    weaknesses: str = Field(max_length=80, description="부족한 점 한 문장")
    quotes: list[str] = Field(max_length=3, description="점수 근거가 된 답변 원문 구절 1~3개 (답변에 있는 그대로 복사, 질문 문장은 넣지 않음)")


class JNonTechLocal(JNonTech):
    """사내 모델용 (JTechLocal과 같은 이유)"""
    opinion: str = Field(max_length=200, description="답변에서 드러난 지원자에 대한 의견 두 문장 (점수 없음, 200자 안)")
    to_check: str = Field(max_length=80, description="다음 전형에서 확인할 점 한 문장")
    quotes: list[str] = Field(max_length=2, description="근거가 된 답변 원문 구절 1~2개 (답변에 있는 그대로 복사)")
    rationale: str = Field(max_length=120, description="의견 근거 한 문장")


Point = Annotated[str, Field(max_length=20)]


class QOutLocal(QOut):
    """사내 모델용 질문 형식 (11/16): 꼬리질문 생성이 근거 칸을 길게 쓰다 출력 제한(700토큰)에 잘려 6번 중 5번 실패 → 일반 질문으로 대체되던 문제"""
    question_text: str = Field(max_length=150, description="지원자에게 읽어 줄 질문 (150자 이내)")
    key_points: list[Point] = Field(min_length=2, max_length=4, description="좋은 답에 들어가야 할 핵심 요소 2~4개 (각 15자 이내)")
    basis: str = Field(max_length=100, description="이 질문을 낸 근거 한 줄 (관리자용, 100자 안)")


class QFollowLocal(QOutLocal):
    premise: str = Field(max_length=100, description="이 질문이 지원자 답변에서 전제로 삼는 내용을 평서문 한 문장으로 (100자 안)")
    quote: str = Field(max_length=120, description="질문의 바탕이 된 지원자 답변 구절 (답변에 있는 그대로 복사)")


G.LOCAL_SCHEMA.update({JTech: JTechLocal, JNonTech: JNonTechLocal, QOut: QOutLocal, QFollow: QFollowLocal})


class Fit(BaseModel):
    verdict: str = Field(description="적합 / 모순 / 무관 중 하나")
    reason: str


class EvalCheck(BaseModel):
    consistent: bool = Field(description="모든 문항에서 점수와 판정 근거·인용이 서로 맞으면 true")
    reason: str


# ---------- 공통 ----------

def _gate(ctx: QuestionContext | None, purpose: str, schema, name: str, values: dict, min_tier: int | None,
          local_only: bool = False, extra: str = "", llm_cfg: dict | None = None) -> G.Result:
    return G.call(purpose, schema, name, values, llm_cfg=llm_cfg if llm_cfg is not None else (ctx.llm if ctx else None),
                  min_tier=min_tier, consent=bool(ctx and ctx.overseas_consent), local_only=local_only,
                  session_id=ctx.session_id if ctx else None, application_id=ctx.application_id if ctx else None, extra=extra)


def _resume(ctx: QuestionContext, n: int = 3000) -> str:
    return ctx.resume_text[:n] or NONE


def _forbid_hits(text: str, forbid: list[str]) -> list[str]:
    return [w for w in forbid if w and w in text]


def _write(ctx: QuestionContext, base: Question, purpose: str, name: str, values: dict, forbid: list[str],
           schema=QOut) -> tuple[Question, object | None]:
    """base(근거·종류가 정해진 기본 질문)의 문장을 LLM으로 쓴다. 지시문 베끼기면 1번 다시.
    금지어가 남으면 1번 고쳐 쓰고(defend_fix), 그래도 남으면 코드가 가린다. LLM이 끝내 실패하면 base 그대로(대체 질문)"""
    extra, path, out = "", [], None
    for _ in range(2):
        r = _gate(ctx, purpose, schema, name, values, base.min_tier, extra=extra)
        if r.note:
            path.append(r.note)
        if r.out is None:
            break
        text = re.sub(r"\s*\([^)]*\)", "", r.out.question_text).strip()   # 괄호 설명은 지운다 (말로 읽는 질문)
        if not text or len(text) > 220 or any(w in text for w in ECHO):
            extra = "앞서 쓴 것은 지시문을 베꼈습니다. 지원자에게 바로 읽어 줄 질문 문장 하나만 question_text에 쓰세요."
            continue
        out, hits = r.out, _forbid_hits(text, forbid)
        if hits and not extra.startswith("금지어"):
            extra, path = f"금지어 {', '.join(hits)}를 쓰지 말고 다시 쓰세요.", path + ["금지어 고쳐 쓰기"]
            continue
        for w in hits:                                                   # 고쳐 써도 남은 금지어는 코드가 가림
            text = text.replace(w, "○○")
        if hits:
            path.append("금지어 가림")
        q = base.model_copy(update={"question_text": text[:300], "key_points": [k[:30] for k in out.key_points[:4]] or base.key_points,
                                    "basis": f"{base.basis} · {out.basis}"[:500], "model": r.model,
                                    "defense": {**base.defense, **({"경로": path} if path else {})}})
        return q, out
    return base.model_copy(update={"basis": base.basis + " · LLM 질문 생성 실패로 기본 질문",
                                   "defense": {**base.defense, "경로": path + ["대체 질문"]}}), None


# ---------- 질문 ----------

def q1_verify(ctx: QuestionContext) -> Question:
    """1번: handoff의 '면접 확인 필요 목록'을 먼저 쓰고, 비면 이력서 원문에서 경험 하나 (검색 없음)"""
    check = ctx.handoff.check_list
    base = Question(kind="non_tech", question_text="이력서에 적은 프로젝트에서 직접 맡은 부분과 결과를 설명해 주세요.",
                    basis=("1차 면접 확인 필요: " + " / ".join(check))[:300] if check else "이력서 원문 (검색 없음)",
                    key_points=["본인 역할", "결과"], model="rule")
    focus = (f"1차 서류에서 근거가 부족해 면접에서 확인하기로 한 항목이 있습니다: {' / '.join(check)}. 이 중 하나를 골라 이력서의 관련 경험과 이어서"
             if check else "이력서의 프로젝트나 경력 중 가장 중요한 하나를 골라 이름을 넣어,")
    return _write(ctx, base, "q1_verify", "q1_verify", {"focus": focus, "resume": _resume(ctx)}, [])[0]


def _indicators(code: str) -> str:
    """인재상 지표 TAL (tier 0) 키 조회 — 벡터 검색 안 함"""
    try:
        from api.db import connect
        with connect() as db:
            r = db.execute("""SELECT body FROM company_doc_chunk WHERE doc_type = 'talent' AND sec_title LIKE %s LIMIT 1""",
                           (code + "%",)).fetchone()
        return r["body"][:800] if r else NONE
    except Exception:  # noqa: BLE001  DB가 없으면 지표 없이
        return NONE


def q2_value(ctx: QuestionContext) -> Question:
    v = ctx.handoff.deficit_value
    name = VALUES.get(v, v)
    base = Question(kind="non_tech", question_text=f"이력서에 적은 장점 말고, 이력서에 없는 다른 장점이 있다면 '{name}'을(를) 보여 준 경험과 함께 말씀해 주세요.",
                    basis=f"이력서 밖 질문 · 1차 결핍 가치 {v}({name}): {ctx.handoff.deficit_reason}", min_tier=0, key_points=["상황", "행동"], model="rule")
    return _write(ctx, base, "q2_value", "q2_value", {"value_name": name, "deficit_reason": ctx.handoff.deficit_reason or NONE,
                                                       "indicators": _indicators(v), "resume": _resume(ctx, 1500)}, [])[0]


def _weak_query(ctx: QuestionContext) -> str:
    w = ctx.weakness
    return f"{' '.join(w.algorithms)} {' '.join(w.weakness_tags)}" if w else ""


def pick_project(ctx: QuestionContext) -> str | None:
    """기술 주제(프로젝트) = 주제 구분 없이 한 번 검색해 각 주제 문서가 처음 나온 순위 (RRF). 1위 주제로 3~10번을 묻는다"""
    tier3 = [d for d in ctx.docs if d.tier == 3]
    hits = retrieve.rank(f"{_weak_query(ctx)} {retrieve.experience_query(ctx.resume_text)}", tier3)
    return hits[0].doc.topic if hits else F.pick_project(ctx)


def _main_ok(d: CompanyDoc) -> bool:
    """본 질문 근거: project 또는 resolved incident 공개판 (tier 3)"""
    return d.tier == 3 and (d.doc_type == "project" or (d.doc_type == "incident" and d.status in (None, "resolved")))


def tech_main(ctx: QuestionContext, used: list[str]) -> Question | None:
    left = [d for d in ctx.docs if _main_ok(d) and d.chunk_id not in used]
    cands = [d for d in left if ctx.project is None or d.topic == ctx.project]
    reuse = not cands and bool(left)                 # 주제가 모자라면 다른 주제 문서 + '주제 재사용' 표시
    cands = cands or left
    if not cands:
        return None
    first = not used
    query = _weak_query(ctx) if first and ctx.weakness else retrieve.experience_query(ctx.resume_text)
    hit = retrieve.rank(query, cands, k=1)[0]
    d = hit.doc
    lead = re.split(r"(?<=[.다])\s", d.body.strip(), maxsplit=1)[0][:150]   # LLM이 실패할 때 쓸 기본 질문: 문서 첫 문장으로 상황 설명
    basis = (f"코딩 약점 {', '.join(ctx.weakness.weakness_tags)} × {d.chunk_id}" if first and ctx.weakness else f"{d.chunk_id} × 이력서")
    rag = {"query": "코딩 약점 요약" if first and ctx.weakness else "이력서 경험", "rrf": round(hit.rrf, 4), "bm25": hit.bm25_rank,
           "vector": hit.vec_rank, **({"주제 재사용": True} if reuse else {})}
    base = Question(kind="tech", tech_stack=d.topic, question_text=f"이런 상황을 맡았다고 해 볼게요. {lead} 어떻게 설계하고 구현하시겠어요?",
                    basis=basis, source_doc_ids=[d.chunk_id], min_tier=3, key_points=["방법", "이유"], model="rule", defense={"검색": rag})
    weak = (f"지원자의 코딩 테스트 약점: 알고리즘 {', '.join(ctx.weakness.algorithms)} / {', '.join(ctx.weakness.weakness_tags)}. "
            "이 약점을 확인할 수 있게 물으세요." if first and ctx.weakness else "약점 정보 없음: 상황 설계 능력을 묻습니다.")
    return _write(ctx, base, "tech_main", "tech_main", {"weakness": weak, "evidence": d.body[:1500], "resume": _resume(ctx, 1200)},
                  d.forbid or [])[0]


def tech_followup(ctx: QuestionContext, question: Question, stt_text: str) -> Question:
    """꼬리 1 = tier 2(같은 주제, 같은 사건 1개만), 꼬리 2 = tier 1 research(꼬리 1 근거의 related 먼저). 질의 = 직전 답변 원문.
    상위 2개를 근거로, 0개면 답변만 보고 질문. tier 1·2가 든 프롬프트는 사내 모델로만"""
    depth = question.depth + 1
    tier = 3 - depth
    prev = [d for d in ctx.docs if d.chunk_id in question.source_doc_ids]
    cands = [d for d in ctx.docs if d.tier == tier and d.topic == question.tech_stack]
    related = [d for d in cands if any(d.chunk_id.split("#")[0] in p.related or d.chunk_id in p.related for p in prev)]
    hits = retrieve.rank(stt_text or question.question_text, related or cands, k=2)
    if depth == 1:                                   # 같은 사건(문서)은 1개만
        hits = [h for i, h in enumerate(hits) if h.doc.chunk_id.split("#")[0] not in {x.doc.chunk_id.split("#")[0] for x in hits[:i]}]
    docs = [h.doc for h in hits]
    min_tier = min([d.tier for d in docs] + [question.min_tier if question.min_tier is not None else 3])
    base = Question(kind="tech", question_type="followup", depth=depth, tech_stack=question.tech_stack,
                    question_text="방금 설명하신 방법에서 가장 어려웠던 점과 그 이유를 말씀해 주세요.",
                    basis=f"꼬리 {depth}: 답변 원문 → {[d.chunk_id for d in docs] or '근거 없음'}", source_doc_ids=[d.chunk_id for d in docs],
                    min_tier=min_tier, key_points=["원인", "해결"], model="rule",
                    defense={"검색": {"query": "직전 답변 원문", "related 먼저": bool(related),
                                      "rrf": [round(h.rrf, 4) for h in hits]}})
    evidence = "\n\n".join(d.body[:800] for d in docs) or "근거 문서 없음: 답변만 보고 질문합니다."
    q, out = _write(ctx, base, "tech_followup", "tech_followup",
                    {"depth": depth, "question": question.question_text, "answer": (stt_text or NONE)[:1500], "evidence": evidence},
                    sorted({w for d in docs for w in d.forbid}), schema=QFollow)
    if out is not None:
        q = q.model_copy(update={"defense": {**q.defense, "premise": out.premise, "quote": out.quote}})
    return q


def tech_retry(question: Question, ctx: QuestionContext | None = None, stt_text: str = "", reason: str = "low") -> Question:
    """재질문: 검색 없음, 본 질문 근거를 다시 씀. reason: low(40점 미만) / off_target(70점 이상인데 CE < 0.4 → 범위를 좁혀)"""
    base = F.tech_retry(question).model_copy(update={"defense": {"재질문 유형": reason}})
    if ctx is None:
        return base
    return _write(ctx, base.model_copy(update={"question_text": question.question_text}), "tech_retry", "tech_retry",
                  {"reason": "질문과 다른 내용을 답함 → 범위를 좁혀서" if reason == "off_target" else "답이 부족함 → 형식을 바꿔서",
                   "question": question.question_text, "answer": (stt_text or NONE)[:1200]},
                  [w for d in (ctx.docs if ctx else []) if d.chunk_id in question.source_doc_ids for w in d.forbid])[0]


def check_followup(question: Question, stt_text: str, ctx: QuestionContext | None = None) -> dict:
    """guard (FR-77): 인용 확인 → NLI(답변 ⇒ 질문 전제) 모순 ≥ 0.3 탈락 → 함의 ≥ 0.6 통과 → 그 사이는 사내 LLM(fit_judge).
    NLI 서버가 없으면 인용 확인만 하고 '검사 생략' 표시"""
    quote, premise = question.defense.get("quote", ""), question.defense.get("premise", "")
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip()
    words = [w for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", quote or "")]
    seen = sum(w in norm(stt_text) for w in words)
    quote_ok = not quote or norm(quote) in norm(stt_text) or seen >= max(1, len(words)) * 0.5   # 조금 바꾼 인용은 낱말 절반 이상이면 인정
    n = nli_client.nli(stt_text or "", premise or question.question_text) if stt_text else None
    if n is None:                                    # NLI가 없으면 인용 확인만
        return {"verdict": "pass" if quote_ok else "fail", "by": "검사 생략 (NLI 없음, 인용 확인만)", "entailment": None,
                "contradiction": None, **({} if quote_ok else {"reason": "질문이 인용한 구절이 답변에 없음"})}
    # 임시: 사내 4B 모델이 quote 칸에 답변 대신 질문을 넣는 일이 잦아(11/9), 인용이 안 맞아도 탈락시키지 않고 표시만 하고 NLI가 판정
    base = {"entailment": n["entailment"], "contradiction": n["contradiction"], "nli_model": n.get("model"),
            **({} if quote_ok else {"인용": "답변에 없음"})}
    if n["contradiction"] >= NLI_CONTRA:
        return {**base, "verdict": "fail", "by": "NLI", "reason": f"모순 {n['contradiction']:.2f} ≥ {NLI_CONTRA}"}
    if n["entailment"] >= NLI_ENTAIL:
        return {**base, "verdict": "pass", "by": "NLI"}
    r = _gate(ctx, "fit_judge", Fit, "fit_judge", {"answer": (stt_text or NONE)[:1500], "question": question.question_text}, 1,
              local_only=True)                       # 애매한 것만 사내 4B (서브그래프 LLM)
    if r.out is None:
        return {**base, "verdict": "pass", "by": "fit_judge 실패 → 통과 (신뢰도 낮음)", "low_confidence": True}
    return {**base, "verdict": "pass" if r.out.verdict.strip().startswith("적합") else "fail", "by": f"fit_judge {r.model}",
            "reason": f"{r.out.verdict}: {r.out.reason}"[:200]}


def fix_followup(ctx: QuestionContext, question: Question, stt_text: str, check: dict) -> Question:
    q, out = _write(ctx, question, "followup_fix", "fix_followup",
                    {"reason": check.get("reason") or "답변과 맞지 않음", "answer": (stt_text or NONE)[:1500], "question": question.question_text},
                    [], schema=QFollow)
    return q.model_copy(update={"defense": {**q.defense, "premise": out.premise, "quote": out.quote}}) if out else q


# ---------- 판정 ----------

def _quotes(qs: list[str], stt: str) -> list[str]:
    """인용은 답변 원문에 그대로 있는 것만 (공백 차이는 허용, 5자 이상)"""
    norm = re.sub(r"\s+", " ", stt)
    return [q.strip() for q in qs if len(q.strip()) >= 5 and re.sub(r"\s+", " ", q.strip()) in norm][:3]


def _failed(question: Question, path: str) -> Judgement:
    """평가 실패: 자동 탈락 없이 점수 '보류'(NULL) → 다음 주제. 담당자가 STT 원문으로 판단"""
    return Judgement(status="parse_error", score=None, quotes=[], rationale=f"평가 실패 — 점수 보류 ({path}), 담당자 확인 필요",
                     lang_structure=0, lang_terms=0, lang_intent=0, model_tier="eval", model="rule", latency_ms=0)


def judge_answer(question: Question, stt_text: str | None, ctx: QuestionContext | None = None) -> Judgement:
    """답변 판정. 무응답은 모델을 부르지 않는다. 모델이 끝내 답하지 않으면 점수 보류(면접은 계속)"""
    if not stt_text or not stt_text.strip():
        return F.judge_answer(question, stt_text).model_copy(update={"model": "rule"})   # 무응답: 모델 없이 규칙으로
    if question.kind == "non_tech":
        r = _gate(ctx, "judge_non_tech", JNonTech, "judge_non_tech",
                  {"question": question.question_text, "basis": question.basis or NONE, "answer": stt_text,
                   "resume": _resume(ctx, 1500) if ctx else NONE}, question.min_tier)
        if r.out is None:
            return _failed(question, r.role)
        o = r.out
        return Judgement(opinion={"의견": o.opinion, "이력서·가치 근거 있음": o.matches_resume, "확인할 점": o.to_check},
                         quotes=_quotes(o.quotes, stt_text), rationale=o.rationale or "의견", lang_structure=o.lang_structure,
                         lang_terms=o.lang_terms, lang_intent=o.lang_intent, model_tier="fast" if r.role == "fast" else "eval",
                         model=r.model, latency_ms=0)
    docs = [d for d in (ctx.docs if ctx else []) if d.chunk_id in question.source_doc_ids]
    r = _gate(ctx, "judge_tech", JTech, "judge_tech",
              {"question": question.question_text, "key_points": ", ".join(question.key_points) or NONE,
               "evidence": "\n\n".join(d.body[:1200] for d in docs) or NONE, "answer": stt_text}, question.min_tier)
    relevance = nli_client.ce(question.question_text, stt_text)       # 모든 기술 답변에 CE 기록 (분기 근거로만)
    if r.out is None:
        return _failed(question, r.role).model_copy(update={"relevance": relevance})
    o = r.out
    rubric = {"정확성": o.accuracy, "회사 적용": o.company_fit, "깊이": o.depth, "구체성": o.specificity, "강점": o.strengths, "약점": o.weaknesses}
    return Judgement(score=o.accuracy + o.company_fit + o.depth + o.specificity, rubric=rubric, quotes=_quotes(o.quotes, stt_text),
                     rationale=o.rationale or "-", relevance=relevance, lang_structure=o.lang_structure, lang_terms=o.lang_terms,
                     lang_intent=o.lang_intent, model_tier="fast" if r.role == "fast" else "eval", model=r.model, latency_ms=0)


def evaluate_interview(turns: list[Turn], version_no: int = 1) -> Evaluation:
    """최종 평가: 점수 산식·코드 검사 1~4는 가짜 모듈과 같은 코드(임시 산식, CLAUDE.md 5장).
    검사 5(근거–점수 정합)는 사내 빠른 모델이 판단 (평가 모델과 다른 모델). 앞 문항 tier를 이어받으므로 사내로만"""
    ev = F.evaluate_interview(turns, version_no)
    lines = "\n".join(f"{t.ask_order}번 점수 {t.judgement.score} · 근거: {t.judgement.rationale} · 인용: {' / '.join(t.judgement.quotes)}"
                      for t in turns if t.question.kind == "tech" and t.judgement.status == "ok")
    fast = os.environ.get("LLM_LOCAL_FAST_MODEL", "qwen3:1.7b")
    r = _gate(None, "eval_check", EvalCheck, "eval_check", {"lines": lines or "(판정한 기술 답변 없음)"}, 1, local_only=True,
              llm_cfg={"local": fast}) if lines else None
    passed, detail = (True, "판정한 기술 답변 없음") if not lines else ((r.out.consistent, r.out.reason[:200]) if r.out else (False, "검사 실패"))
    checks = [c for c in ev.checks if c.check_no != 5] + [Check(check_no=5, passed=passed, checker=r.model if r and r.out else "code",
                                                               detail=f"근거–점수 정합: {detail}")]
    return ev.model_copy(update={"checks": checks, "status": "passed" if all(c.passed for c in checks) else "failed",
                                 "model": r.model if r and r.out else ev.model})
