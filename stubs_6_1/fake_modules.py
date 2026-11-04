"""다른 파트 모듈이 오기 전까지 쓰는 가짜 모듈 (영찬 RAG TRD v0.6 방식). LLM 없이 늘 같은 결과.

- q1_verify / q2_value : 1번 이력서 본인 확인, 2번 결핍 가치 (비기술, 의견만)
- pick_project         : 이력서와 가장 비슷한 회사 프로젝트 1개 (진짜는 RAG 검색)
- tech_main            : 본 질문 (고른 프로젝트의 tier 3 근거, 첫 기술 질문은 코딩 약점 요약)
- tech_followup        : 꼬리 1(tier 2)·꼬리 2(tier 1, related 우선). 진짜는 답변 원문으로 Hybrid 검색
- tech_retry           : 재질문 (같은 근거, 형식만 바꿈)
- check_followup / fix_followup : 꼬리질문 모순 검사·1회 수정 (진짜는 NLI + 온프레미스 LLM, 가짜는 늘 통과)
- judge_answer         : 기술 100점(체크리스트 충족 비율로 흉내) + 답변 관련성(가짜 CE), 비기술 의견
- evaluate_interview   : 주제 점수 + 임시 산식 + 적합성·확장성 의견 + 코드 검사 1~4
"""
import os
import re
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app_6_1"))
from flow import topic_score  # noqa: E402

from contracts import Check, CompanyDoc, Evaluation, Judgement, Question, QuestionContext, Turn  # noqa: E402

STUB = "stub"
_FORBIDDEN = ["성별", "나이", "외모", "출신", "말투", "표정", "시선", "목소리"]   # 검사 4: 판정 근거에 나오면 안 됨


def q1_verify(ctx: QuestionContext) -> Question:
    return Question(kind="non_tech", question_text="이력서의 프로젝트에서 직접 맡은 부분과 결과를 설명해 주세요.",
                    basis="이력서 원문 (검색 없음)", key_points=["역할", "결과"], model=STUB)


def q2_value(ctx: QuestionContext) -> Question:
    v = ctx.handoff.deficit_value
    return Question(kind="non_tech", question_text=f"이력서에 적은 장점 말고, 이력서에 없는 다른 장점을 '{v}' 가치와 관련된 경험으로 말해 주세요.",
                    basis=f"1차 결핍 가치 {v}: {ctx.handoff.deficit_reason}", key_points=["상황", "행동"], model=STUB)


def _pick(ctx, tier, topic=None, prefer=()):
    cands = [d for d in ctx.docs if d.tier == tier and (topic is None or d.topic == topic)]
    cands.sort(key=lambda d: d.chunk_id not in prefer)
    return cands[0] if cands else None


def pick_project(ctx: QuestionContext) -> str | None:
    """이력서와 가장 비슷한 회사 프로젝트(topic) 1개. 후보는 지원 직무·난이도로 걸러진 tier 3 문서.
    가짜: 이력서 단어가 프로젝트 tier 3 문서에 나오는 수가 가장 많은 것. 진짜는 이력서 기술로 RAG 검색.
    3번은 코딩 약점을 반영해야 하므로(FR-73) 약점 알고리즘이 나오는 섹션이 있는 프로젝트를 먼저 고른다 (없으면 전체에서)."""
    words = {w.lower() for w in re.findall(r"[0-9A-Za-z가-힣+#]{2,}", ctx.resume_text)}
    score: dict[str, int] = {}
    weak: set[str] = set()
    for d in ctx.docs:
        if d.tier == 3:
            body = d.body.lower()
            score[d.topic] = score.get(d.topic, 0) + sum(w in body for w in words)
            if ctx.weakness and any(a in d.body for a in ctx.weakness.algorithms):
                weak.add(d.topic)
    return max(sorted(weak or score), key=lambda t: score[t]) if score else None


def tech_main(ctx: QuestionContext, used: list[str]) -> Question | None:
    """다음 본 질문. 고른 프로젝트(ctx.project)에서 아직 안 쓴 tier 3 섹션(used = 쓴 chunk_id) 순서.
    첫 기술 질문(3번)은 코딩 약점 알고리즘이 들어간 섹션을 먼저 고른다.
    프로젝트 섹션이 바닥나면(무응답이 이어져 본 질문만 계속 나올 때) 다른 프로젝트 섹션으로 채운다."""
    left = [d for d in ctx.docs if d.tier == 3 and d.chunk_id not in used]
    docs = [d for d in left if ctx.project is None or d.topic == ctx.project] or left
    first = not used
    if first and ctx.weakness:
        docs.sort(key=lambda d: not any(a in d.body for a in ctx.weakness.algorithms))
    if not docs:
        return None
    d = docs[0]
    basis = (f"코딩 약점 {', '.join(ctx.weakness.weakness_tags)} × {d.chunk_id} × 이력서" if first and ctx.weakness
             else f"{d.chunk_id} × 이력서")
    return Question(kind="tech", tech_stack=d.topic, question_text=f"{d.topic} 프로젝트의 '{d.body[:20]}'를 어떻게 구현하겠습니까?",
                    basis=basis, source_doc_ids=[d.chunk_id], min_tier=3, key_points=["방법", "이유"], model=STUB)


def tech_followup(ctx: QuestionContext, question: Question, stt_text: str) -> Question:
    depth = question.depth + 1
    prev = next((x for x in ctx.docs if x.chunk_id in question.source_doc_ids), None)
    d = _pick(ctx, 3 - depth, question.tech_stack, prefer=prev.related if prev else ())
    ids, tier = ([d.chunk_id], d.tier) if d else ([], question.min_tier)   # 근거가 없으면 답변만 보고 질문
    return Question(kind="tech", question_type="followup", depth=depth, tech_stack=question.tech_stack,
                    question_text=f"방금 답변을 바탕으로, {d.body[:20] if d else '그 방법'}에서 생기는 문제를 어떻게 풀겠습니까?",
                    basis=f"꼬리 {depth}: 답변 원문 → {ids or '근거 없음'}", source_doc_ids=ids, min_tier=tier,
                    key_points=["원인", "해결"], model=STUB)


def tech_retry(question: Question, ctx: QuestionContext | None = None, stt_text: str = "", reason: str = "low") -> Question:
    return question.model_copy(update={"question_type": "reask",
                                       "question_text": "질문을 바꿔 드리겠습니다. " + question.question_text})


def judge_answer(question: Question, stt_text: str | None, ctx: QuestionContext | None = None) -> Judgement:
    base = dict(model_tier="eval", model=STUB, latency_ms=0)
    if not stt_text or not stt_text.strip():
        return Judgement(status="silent", score=0 if question.kind == "tech" else None, quotes=[], rationale="무응답",
                         lang_structure=0, lang_terms=0, lang_intent=0, **base)
    met = [p for p in question.key_points if p in stt_text]
    quotes = [s.strip() for s in stt_text.split(".") if any(p in s for p in met)][:2]
    lang = 4 + 2 * len(met)
    if question.kind == "non_tech":
        return Judgement(opinion={"의견": f"체크리스트 {len(met)}/{len(question.key_points)}", "이력서 일치": bool(met)},
                         quotes=quotes, rationale="비기술은 점수 없이 의견", lang_structure=lang, lang_terms=lang,
                         lang_intent=lang, **base)
    ratio = len(met) / max(len(question.key_points), 1)
    score = 85 if ratio >= 1 else 55 if met else 20          # 모두·일부·없음 (질문 은행 질문은 핵심 요소가 3개, 11/10)
    return Judgement(score=score, rubric={"정확성": score * 0.3, "회사 적용": score * 0.3, "깊이": score * 0.25,
                                          "구체성": score * 0.15},
                     quotes=quotes, rationale=f"체크리스트 {len(met)}/{len(question.key_points)}개 언급",
                     relevance=0.9 if met else 0.2,      # 가짜 CE: 핵심 요소를 하나라도 말하면 관련 있음. 진짜는 cross-encoder
                     lang_structure=lang, lang_terms=lang, lang_intent=lang, **base)


def check_followup(question: Question, stt_text: str, ctx: QuestionContext | None = None) -> dict:
    """꼬리질문 모순 검사 (FR-77). 진짜: 인용 확인 → NLI(답변 ⇒ 질문 전제) 모순 ≥ 0.3 탈락 → 함의 ≥ 0.6 통과 → 그 사이는 LLM.
    가짜: 늘 통과 (NLI 모델 없음)"""
    return {"verdict": "pass", "by": STUB, "entailment": 0.7, "contradiction": 0.05}


def fix_followup(ctx: QuestionContext, question: Question, stt_text: str, check: dict) -> Question:
    """검사에 떨어진 꼬리질문을 RAG 근거를 참고해 1번 고친다 (FR-77). 가짜: 답변 내용을 전제하지 않는 열린 질문으로"""
    return question.model_copy(update={"question_text": "방금 설명하신 방법에서 가장 어려웠던 점과 그 이유를 말씀해 주세요."})


def _checks(turns: list[Turn], ev: dict) -> list[Check]:
    in_range = 0 <= ev["content"] <= 60 and 0 <= ev["language"] <= 30 and 0 <= ev["nonverbal"] <= 10
    quotes_ok = all(q in (t.stt_text or "") for t in turns for q in t.judgement.quotes)
    points_ok = all(t.judgement.status != "ok" or t.question.kind == "non_tech" or t.judgement.score is not None for t in turns)
    clean = not any(w in t.judgement.rationale for t in turns for w in _FORBIDDEN)
    return [Check(check_no=1, passed=in_range, checker="code", detail="형식·범위"),
            Check(check_no=2, passed=quotes_ok, checker="code", detail="인용이 STT 안에 있음"),
            Check(check_no=3, passed=points_ok, checker="code", detail="기술 답변 점수 누락 없음"),
            Check(check_no=4, passed=clean, checker="code", detail="금지 요소 없음"),
            Check(check_no=5, passed=True, checker=STUB, detail="근거–점수 정합 (진짜는 빠른 LLM)")]


def _opinions(turns: list[Turn], chains: dict[str, tuple[int, list[float]]]) -> tuple[str | None, str, str]:
    """적합성(지금 이 프로젝트에 투입 가능) · 확장성(다른 프로젝트로 옮겨도 가능). 점수에는 넣지 않는다.
    가짜 규칙: 적합성 = 기술 답변 평균, 확장성 = 꼬리질문까지 간 주제 수. 진짜는 LLM이 답변 근거로 쓴다"""
    tech = [t for t in turns if t.question.kind == "tech"]
    stacks = [t.question.tech_stack for t in tech if t.question.tech_stack]
    project = max(sorted(set(stacks)), key=stacks.count) if stacks else None
    scores = [t.judgement.score for t in tech if t.judgement.score is not None]
    avg = sum(scores) / len(scores) if scores else 0
    fit = ("투입 가능" if avg >= 70 else "보완 후 투입 가능" if avg >= 40 else "지금 투입은 어려움") + f" (기술 답변 평균 {avg:.0f}점)"
    deep = sum(1 for d, _ in chains.values() if d >= 1)
    growth = ("다른 프로젝트로 옮겨도 해낼 가능성 높음" if deep >= 2 else "같은 분야 프로젝트라면 가능" if deep == 1
              else "근거 부족") + f" (꼬리질문까지 간 주제 {deep}/{len(chains)}개)"
    return project, fit, growth


def evaluate_interview(turns: list[Turn], version_no: int = 1) -> Evaluation:
    """주제 점수 T = S_d + 40 × 평균/100. 주제 = 본 질문 하나와 그 꼬리·재질문 (한 프로젝트 안에서 섹션별).
    내용 = 주제 점수 평균 × 0.6 (배점 Q-15 미결, 임시).
    언어 = 답변별 언어 3항목 합 평균, 비언어 = (시간 안에 마침 0.5 + (1 − 침묵 비율) 0.5) 평균 × 10"""
    chains: dict[str, tuple[int, list[float]]] = {}
    key = None
    for t in turns:
        if t.question.kind != "tech":
            continue
        if t.question.question_type == "main" or key is None:
            key = f"{t.question.tech_stack} {sum(1 for k in chains if k.startswith(f'{t.question.tech_stack} ')) + 1}"
            chains.setdefault(key, (0, []))
        if t.judgement.score is not None:
            d, s = chains[key]
            chains[key] = (max(d, t.question.depth), s + [t.judgement.score])
    topic_scores = {k: topic_score(d, s) for k, (d, s) in chains.items() if s}
    ev = {"content": round(sum(topic_scores.values()) / max(len(topic_scores), 1) * 0.6, 2),
          "language": round(sum(t.judgement.lang_structure + t.judgement.lang_terms + t.judgement.lang_intent
                                for t in turns) / len(turns), 2),
          "nonverbal": round(sum(0.5 * t.finished_in_time + 0.5 * (1 - t.silence_ratio) for t in turns) / len(turns) * 10, 2)}
    project, fit, growth = _opinions(turns, chains)
    checks = _checks(turns, ev)
    return Evaluation(version_no=version_no, topic_scores=topic_scores, content_score=ev["content"],
                      language_score=ev["language"], nonverbal_score=ev["nonverbal"], rationale="가짜 모듈 임시 산식",
                      project_topic=project, fit_opinion=fit, growth_opinion=growth,
                      checks=checks, status="passed" if all(c.passed for c in checks) else "failed", model=STUB)
