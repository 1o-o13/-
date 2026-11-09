"""1차 서류 S0 (활동다이어그램 1109 2쪽). 점수는 어디에도 없고, AI는 요건별 라벨·근거와 추천(참고)만 낸다.
결정과 상태 변경은 담당관(사람)·코드가 한다.

  retrieve(비교 문서) → score(LLM 의견) → verify(코드 검증) → [hr_screen 사람 판단] → save_decision → handoff

임시(팀 확정 전, 이 저장소 기준):
- 요건 = 공통 스키마 '서류 평가 기준' 표(document_criteria, F-ADM-68)의 항목. 모두 '우대'(없어도 지원 가능, 있으면 우대, 11/10 결정).
  표가 비어 있으면 공고 설명의 '필수:'·'우대:' 항목으로 처음 한 번 채운다. 가중치 칸은 공통 스키마 필수라 50(점수에 안 씀)
- 저장 = document_evaluation 다음 판(version 2까지). fit_score는 공통 스키마가 NOT NULL이라 0으로 두고 화면·정렬에 쓰지 않는다
  (공통 스키마 변경은 다른 파트 소유라 하지 않음). 라벨·결론·검증 결과는 criteria_scores jsonb에
- 담당관 결정 기록(쌓기만 함) = audit_log(action 'screen_decision'). 최근 결정 pass·reject는 stage_result(document)에도 둔다
- 결핍 가치(handoff): 1109 문서 방법. 1차 AI 검토 때 HyDE 가상 글 + 이력서 ↔ 인재상 지표 유사도(cov), 합격 뒤 지원자 간 z 점수 →
  가장 낮은 두 가치의 이력서 원문 근거 확인 → 근거 없는 가치 (11/10). 1차 AI 검토를 거치지 않은 지원 건은 1차 파트가 넣은 값 그대로
"""
import logging
import math
import re

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api import llm_gate as G
from api import modules as M
from api import retrieve

from api.interview.store import mask_resume

# isort: split
from contracts import CompanyDoc  # stubs_6_1 경로는 api.modules가 연다

log = logging.getLogger(__name__)
LABELS = ("충족", "부분", "부족", "근거 없음")


# ---------- 요건 ----------

CRIT_WEIGHT = 50     # document_criteria.weight는 1~100 필수 칸. 점수에 쓰지 않음 (모두 우대)


def criteria(db, posting_id: int) -> list[dict]:
    """1차 평가 기준 (모두 우대). 비어 있으면 공고 설명에서 처음 한 번 채운다 → [{id: CRIT-n, kind: 우대, text, crit_id}]"""
    rows = db.execute("SELECT id, item, description FROM document_criteria WHERE posting_id = %s ORDER BY id", (posting_id,)).fetchall()
    if not rows:
        desc = db.execute("SELECT description FROM job_posting WHERE id = %s", (posting_id,)).fetchone()["description"]
        for r in requirements(desc):
            db.execute("""INSERT INTO document_criteria(posting_id, item, weight, description) VALUES (%s, %s, %s, '우대')
                          ON CONFLICT (posting_id, item) DO NOTHING""", (posting_id, r["text"][:200], CRIT_WEIGHT))
        rows = db.execute("SELECT id, item, description FROM document_criteria WHERE posting_id = %s ORDER BY id", (posting_id,)).fetchall()
    return [{"id": f"CRIT-{i}", "kind": "우대", "text": r["item"], "note": r["description"] if r["description"] != "우대" else None,
             "crit_id": r["id"]} for i, r in enumerate(rows, 1)]


def requirements(description: str | None) -> list[dict]:
    """공고 설명 → [{id, kind 필수·우대, text}]. 'Python 또는 Java로 REST API 개발' 같은 한 항목이 요건 하나"""
    out, text = [], description or ""
    for kind, key in (("필수", "필수"), ("우대", "우대")):
        m = re.search(key + r"\s*:\s*(.+?)(?:\.\s*(?:필수|우대)\s*:|$)", text)
        if not m:
            continue
        for i, item in enumerate([x.strip(" .") for x in re.split(r",\s*(?![^()]*\))", m.group(1)) if x.strip(" .")], 1):
            out.append({"id": f"{'REQ' if kind == '필수' else 'PREF'}-{i}", "kind": kind, "text": item})
    if not out and text.strip():                     # '필수:' 표시가 없는 공고는 설명 전체를 필수 요건 하나로
        out.append({"id": "REQ-1", "kind": "필수", "text": text.strip()[:200]})
    return out


# ---------- 비교 검색 ----------

def compare_docs(db, snap_text: str, job_role: str) -> dict:
    """비교 4개 (RAG TRD 5절): ① JD 체크리스트(tier 0) ② 공개 프로젝트(tier 3) ③ 장애 회고 공개판(tier 3). 이력서 검색은 지원 건 안에서만.
    칸마다 Hybrid → RRF (재정렬은 1차에서도 점수 표시용이라 생략, 임시)"""
    from api.interview.engine import DEPT
    rows = db.execute("""SELECT doc, sec, doc_type, tier, topic, status, related, forbid, body FROM company_doc_chunk
                         WHERE disclosure = 'public' AND sec <> 'ov' AND ((doc_type = 'criteria' AND doc LIKE 'JD-%%' AND %s = ANY(dept))
                               OR (tier = 3 AND doc_type IN ('project', 'incident')))""", (DEPT.get(job_role, "BE"),)).fetchall()
    docs = [CompanyDoc(chunk_id=f"{r['doc']}#{r['sec']}", doc_type=r["doc_type"], tier=r["tier"], topic=r["topic"], status=r["status"],
                       related=r["related"], forbid=r["forbid"], body=r["body"]) for r in rows]
    out = {}
    for key, pick, k in (("JD 강점", lambda d: d.doc_type == "criteria", 1), ("프로젝트", lambda d: d.doc_type == "project", 3),
                         ("장애 회고", lambda d: d.doc_type == "incident", 3)):
        hits = retrieve.rank(snap_text, [d for d in docs if pick(d)], k=k)
        out[key] = [{"chunk_id": h.doc.chunk_id, "rrf": round(h.rrf, 4), "bm25": h.bm25_rank, "vector": h.vec_rank, "body": h.doc.body[:500]}
                    for h in hits]
    return out


# ---------- AI 의견 (LLM) ----------

class ReqLabel(BaseModel):
    req_id: str
    label: str = Field(description="충족 · 부분 · 부족 · 근거 없음 중 하나")
    quote: str = Field(description="근거가 된 이력서 원문 구절 (그대로 복사, 5자 이상). 근거 없음이면 빈칸")


class ScreenOut(BaseModel):
    labels: list[ReqLabel]
    awards_opinion: str = Field(description="수상·자격 의견 한두 문장")
    work_fit: str = Field(description="업무 가능성: 높음 · 보통 · 낮음")
    overall: str = Field(description="종합 의견 두세 문장 (점수·합격 판정 없이)")
    conclusion: str = Field(description="추천 · 비추천 중 하나 ('AI 추천(참고)'). 애매하면 추천")
    conclusion_req_ids: list[str] = Field(description="결론 근거가 된 요건 ID 2개 이상")
    conclusion_quotes: list[str] = Field(description="결론 근거 이력서 원문 인용 2개 이상")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def verify(out: ScreenOut, reqs: list[dict], resume_flat: str) -> list[str]:
    """코드 검증: 요건 ID 빠짐없음 · 라벨 값 · 충족·부분 인용이 원문에 실재(5자 이상, 공백 차이만) ·
    결론 근거 요건 2개 이상 + 인용 2개 이상, 추천은 '충족'에서만·비추천은 '부족'·'근거 없음'에서만. 반환: 오류 목록 (결론 오류는 'C:' 앞머리)"""
    errs, by = [], {x.req_id: x for x in out.labels}
    missing = [r["id"] for r in reqs if r["id"] not in by]
    if missing:
        errs.append(f"요건 빠짐: {', '.join(missing)}")
    for x in out.labels:
        if x.label not in LABELS:
            errs.append(f"{x.req_id} 라벨 값 오류: {x.label}")
        elif x.label in ("충족", "부분") and (len(_norm(x.quote)) < 5 or _norm(x.quote) not in resume_flat):
            errs.append(f"{x.req_id} 인용이 이력서 원문에 없음")
    if out.conclusion not in ("추천", "비추천"):
        errs.append(f"C: 결론 값 오류 {out.conclusion}")
    ids = [i for i in out.conclusion_req_ids if i in by]
    quotes = [q for q in out.conclusion_quotes if len(_norm(q)) >= 5 and _norm(q) in resume_flat]
    if len(ids) < 2 or len(quotes) < 2:
        errs.append("C: 결론 근거는 요건 ID 2개 이상 + 원문 인용 2개 이상")
    if out.conclusion == "추천" and any(by[i].label != "충족" for i in ids):
        errs.append("C: 추천 근거는 '충족' 요건에서만")
    if out.conclusion == "비추천" and any(by[i].label not in ("부족", "근거 없음") for i in ids):
        errs.append("C: 비추천 근거는 '부족'·'근거 없음' 요건에서만")
    return errs


def _flat(snap: dict) -> str:
    """인용 확인용 이력서 원문 (글 칸만 이어 붙임)"""
    parts: list[str] = []

    def walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk({k: v for k, v in snap.items() if k not in ("인적사항", "시험용 수준")})
    return _norm(" ".join(parts))


def _stub_screen(reqs: list[dict], flat: str) -> ScreenOut:
    """MODULE_MODE=stub: 요건 낱말이 이력서에 나오면 충족 (LLM 없이, 결과 고정)"""
    labels = []
    for r in reqs:
        words = [w for w in re.findall(r"[A-Za-z]{2,}|[가-힣]{2,}", r["text"]) if w not in ("또는", "기본", "이해", "경험")]
        hit = next((w for w in words if w.lower() in flat.lower()), None)
        if hit:
            i = flat.lower().index(hit.lower())
            labels.append(ReqLabel(req_id=r["id"], label="충족", quote=flat[max(0, i - 4): i + len(hit) + 6]))
        else:
            labels.append(ReqLabel(req_id=r["id"], label="근거 없음", quote=""))
    ok = [x for x in labels if x.label == "충족"]
    bad = [x for x in labels if x.label != "충족"]
    half = len(ok) * 2 >= len(labels)                  # 모두 우대: 절반 이상 충족이면 추천 (가짜 규칙)
    pick = ok if half else bad
    concl = "추천" if half else "비추천"               # 보류 없음 (11/12): 절반 이상 충족이면 추천
    return ScreenOut(labels=labels, awards_opinion="규칙 판정(가짜 모듈): 수상·자격은 이력서 표 참고", work_fit="보통",
                     overall=f"우대 항목 {len(reqs)}개 중 충족 {len(ok)}개",
                     conclusion=concl, conclusion_req_ids=[x.req_id for x in pick][:3], conclusion_quotes=[x.quote for x in ok][:3])


def score(db, app: dict, reqs: list[dict], docs: dict) -> dict:
    """AI 의견 → 코드 검증. 실패하면 오류 내용을 붙여 1회 재요청. 결론 검사만 걸리면 결론 빈칸('결론 근거 확인 실패', 라벨은 저장),
    다른 치명 오류면 결론 없음(빈칸) + '자동 정리 실패' (담당관이 이력서 원문으로 판단)"""
    snap, flat = app["resume_snapshot"], _flat(app["resume_snapshot"])
    if M.MODE == "stub":
        out, errs, model = _stub_screen(reqs, flat), [], "stub"
        errs = verify(out, reqs, flat)
    else:
        values = {"requirements": "\n".join(f"{r['id']} ({r['kind']}) {r['text']}" for r in reqs),
                  "evidence": "\n\n".join(f"[{k}] {d['chunk_id']}: {d['body'][:400]}" for k, v in docs.items() for d in v) or "(없음)",
                  "resume": mask_resume(snap)[:6000]}
        out, errs, model, extra = None, ["호출 전"], "-", ""
        tokens = 3000                                    # 요건 라벨이 많아 길다 (1024면 잘림, 11/9). 면접 밖 일괄 작업이라 시간 여유
        for i in range(2):
            r = G.call("doc_screen", ScreenOut, "doc_screen", values, min_tier=3, consent=True, application_id=app["id"], extra=extra,
                       t_fallback=60, t_error=120, max_tokens=tokens)
            model = r.model
            if r.out is None:
                errs = [f"LLM 실패 ({r.role})"]
                if r.role == "parse_error" and i == 0:   # 응답이 한도에서 잘려 읽지 못함 → 한도를 늘려 한 번 더 (11/12, 이력서가 긴 지원자)
                    tokens = 6000
                    continue
                break
            out, errs = r.out, verify(r.out, reqs, flat)
            if not errs:
                break
            extra = "앞선 결과의 검증 오류: " + "; ".join(errs) + "\n오류를 고쳐 다시 내 주세요."
    fatal = [e for e in errs if not e.startswith("C:")]
    if out is None or fatal:
        conclusion, note = None, "자동 정리 실패: " + "; ".join(errs)
    elif errs:
        conclusion, note = None, "결론 근거 확인 실패 (이력서 원문으로 판단): " + "; ".join(e[3:] for e in errs)   # 보류 없음 (11/12)
    else:
        conclusion, note = out.conclusion, ""
    return {"labels": [x.model_dump() for x in out.labels] if out else [], "awards_opinion": out.awards_opinion if out else "",
            "work_fit": out.work_fit if out else "", "overall": out.overall if out else "", "결론": conclusion,
            "결론 근거": {"요건": out.conclusion_req_ids, "인용": out.conclusion_quotes} if out and conclusion else None,
            "검증": note or "통과", "model": model}


def run(db, app_id: int) -> dict:
    """retrieve → score → verify 를 한 지원 건에 돌려 document_evaluation 다음 판으로 저장 (이미 새 형식이 있으면 그대로)"""
    app = db.execute("""SELECT a.id, a.posting_id, a.resume_snapshot, p.description, p.career_level, p.job_role FROM application a
                        JOIN job_posting p ON p.id = a.posting_id WHERE a.id = %s""", (app_id,)).fetchone()
    last = db.execute("""SELECT version_no, criteria_scores, handoff FROM document_evaluation WHERE application_id = %s
                         ORDER BY version_no DESC LIMIT 1""", (app_id,)).fetchone()
    if last and "결론" in (last["criteria_scores"] or {}):
        return last["criteria_scores"]
    reqs = criteria(db, app["posting_id"])
    # 하드 필터(경력 개월 구간 자동 탈락)는 11/12에 없앴다: 아무도 자동으로 떨어뜨리지 않고 모든 지원 건에 AI 의견·근거를 낸다
    docs = compare_docs(db, retrieve.experience_query(mask_resume(app["resume_snapshot"])), app["job_role"])
    cs = {"요건": reqs, "비교": docs, **score(db, app, reqs, docs),
          "가치": value_coverage(db, app_id, app["resume_snapshot"])}       # 결핍 가치용 (합격 뒤 handoff에서 지원자 간 비교)
    save(db, app_id, last, cs)
    return cs


def save(db, app_id: int, last: dict | None, cs: dict) -> None:
    """S0 결과를 document_evaluation 다음 판으로 (판은 2까지 → 넘으면 2판을 덮어씀). 앞 판의 handoff는 그대로 옮긴다"""
    version = (last["version_no"] + 1) if last else 1
    if version > 2:                                  # 공통 스키마: 판은 2까지 → 마지막 판을 새 형식으로 덮어씀
        db.execute("UPDATE document_evaluation SET criteria_scores = %s, rationale = %s WHERE application_id = %s AND version_no = 2",
                   (Jsonb(cs), cs.get("overall") or cs["검증"], app_id))
    else:
        db.execute("""INSERT INTO document_evaluation(application_id, version_no, fit_score, criteria_scores, rationale, handoff, provider,
                          model, status) VALUES (%s, %s, 0, %s, %s, %s, %s, %s, 'passed')""",
                   (app_id, version, Jsonb(cs), cs.get("overall") or cs["검증"], Jsonb(last["handoff"]) if last and last["handoff"] else None,
                    M.provider_of(cs.get("model", "rule")), cs.get("model", "rule")))


# ---------- 공고 단위 AI 추천 (상위 30%) ----------

RECOMMEND_RATE = 0.3     # 11/12 결정: 담당관이 다 검토할 수 있게 AI '추천'은 공고 지원자의 30%까지 (올림)


def final_conclusions(db, posting_id: int) -> dict[int, str | None]:
    """화면·결정에 쓰는 AI 결론 {지원 건 id: 추천 · 비추천 · None(검토 전·정리 실패)}.
    LLM은 지원자마다 의견(추천·비추천)과 요건 라벨만 낸다. 공고 안에서 [LLM 추천 먼저 → '충족' 많은 순 → '부분' 많은 순 → 지원 순]으로
    줄 세워 지원자 수의 30%(올림)만 '추천', 나머지는 '비추천'. 점수는 만들지 않는다"""
    rows = db.execute("""SELECT a.id, d.criteria_scores AS cs FROM application a
                         LEFT JOIN LATERAL (SELECT criteria_scores FROM document_evaluation WHERE application_id = a.id
                                            ORDER BY version_no DESC LIMIT 1) d ON true
                         WHERE a.posting_id = %s AND a.status <> 'withdrawn' ORDER BY a.id""", (posting_id,)).fetchall()
    k = math.ceil(len(rows) * RECOMMEND_RATE)

    def count(cs, label):
        return sum(x.get("label") == label for x in cs.get("labels", []))
    judged = [r for r in rows if r["cs"] and r["cs"].get("결론") in ("추천", "비추천")]
    judged.sort(key=lambda r: (r["cs"]["결론"] != "추천", -count(r["cs"], "충족"), -count(r["cs"], "부분"), r["id"]))
    top = {r["id"] for r in judged[:k]}
    ids = {r["id"] for r in judged}
    return {r["id"]: ("추천" if r["id"] in top else "비추천") if r["id"] in ids else None for r in rows}


# ---------- 합격 뒤: handoff ----------

VALUE_NAME = {"OWN": "주인의식", "COL": "협업", "INT": "정직", "CUS": "고객 중심", "GRW": "성장"}   # TAL (corpus_6_1 09_인재상)


class HydeOut(BaseModel):
    text: str = Field(description="이 지원자가 일하는 방식을 동료가 쓴 것처럼 5~8문장")


class QuoteOut(BaseModel):
    quote: str = Field(description="가치를 행동으로 보여 주는 이력서 원문 문장 그대로. 없으면 빈칸")


def _sentences(text: str, n: int = 40) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.다!?])\s+|\n+", text) if len(x.strip()) >= 10][:n]


def _indicators(db) -> dict[str, list[str]]:
    """가치별 행동 지표 문장 (TAL, tier 0 키 조회)"""
    rows = db.execute("SELECT sec_title, body FROM company_doc_chunk WHERE doc_type = 'talent' ORDER BY sec").fetchall()
    out = {}
    for r in rows:
        code = r["sec_title"].split()[0]
        if code in VALUE_NAME:
            out[code] = _sentences(r["body"], 20) or [r["body"]]
    return out


def _embed(texts: list[str]) -> list[list[float]] | None:
    import os

    import httpx
    try:
        r = httpx.post(os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434") + "/api/embed",
                       json={"model": os.environ.get("EMBED_MODEL", "bge-m3"), "input": texts}, timeout=120)
        r.raise_for_status()
        return r.json()["embeddings"]
    except Exception as e:  # noqa: BLE001  임베딩을 못 쓰면 낱말 겹침으로
        log.info("가치 유사도: 임베딩 없음 (%s) → 낱말 겹침", e)
        return None


def _cos(a: list[float], b: list[float]) -> float:
    import math
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb or 1)


def _overlap(a: str, b: str) -> float:
    ta, tb = set(retrieve.tokens(a)), set(retrieve.tokens(b))
    return len(ta & tb) / (len(ta | tb) or 1)


def value_coverage(db, app_id: int, snap: dict) -> dict:
    """1차 AI 검토 때 (일괄): 가상 '일하는 방식' 글(HyDE, 사실 근거 아님) + 이력서 문장 ↔ 가치마다 행동 지표 문장의
    최대 유사도 평균 cov. bge-m3 코사인 (임베딩을 못 쓰면 형태소 낱말 겹침). 지원자 사이 비교(z)는 합격 뒤 handoff에서"""
    resume = _sentences(_flat(snap))
    hyde = ""
    if M.MODE != "stub":
        r = G.call("hyde_talent", HydeOut, "hyde_talent", {"resume": mask_resume(snap)[:5000]}, min_tier=0, consent=True,
                   application_id=app_id, max_tokens=1500)
        hyde = r.out.text if r.out else ""
    mine = resume + _sentences(hyde, 10)
    ind = _indicators(db)
    if not mine or not ind:
        return {}
    flat_ind = [(v, x) for v, xs in ind.items() for x in xs]
    vec = _embed(mine + [x for _, x in flat_ind]) if M.MODE != "stub" else None
    cov: dict[str, list[float]] = {}
    for k, (v, x) in enumerate(flat_ind):
        if vec:
            best = max(_cos(vec[len(mine) + k], vec[i]) for i in range(len(mine)))
        else:
            best = max(_overlap(x, m) for m in mine)
        cov.setdefault(v, []).append(best)
    return {"cov": {v: round(sum(xs) / len(xs), 4) for v, xs in cov.items()}, "method": "bge-m3 코사인" if vec else "형태소 낱말 겹침",
            "hyde": hyde[:1500], "hyde_is_synthetic": True}


def _quote_for(db, app_id: int, snap: dict, value: str, ind: list[str]) -> str | None:
    """그 가치를 보여 주는 이력서 원문 문장 (HyDE 문장은 근거가 아님). 원문에 실제로 있는 것만 유효"""
    flat = _flat(snap)
    if M.MODE == "stub":
        best = max(((_overlap(" ".join(ind), x), x) for x in _sentences(flat)), default=(0, None))
        return best[1] if best[0] >= 0.08 else None
    r = G.call("value_quote", QuoteOut, "value_quote", {"value_name": VALUE_NAME[value], "indicators": "\n".join(ind),
                                                       "resume": mask_resume(snap)[:5000]}, min_tier=0, consent=True, application_id=app_id)
    q = _norm(r.out.quote) if r.out else ""
    return q if len(q) >= 5 and q in flat else None


def deficit_value(db, app_id: int, posting_id: int, snap: dict, cov: dict) -> dict:
    """결핍 가치 (1109 2쪽 hyde_talent): 같은 공고 지원자 전체 cov로 z 점수 → z가 가장 낮은 가치 2개만 이력서 원문 근거 확인
    → 유효한 인용이 없는 가치 = 결핍 가치 (둘 다 없거나 둘 다 있으면 z가 낮은 쪽)"""
    import statistics
    rows = db.execute("""SELECT d.criteria_scores->'가치'->'cov' AS cov FROM application a
                         JOIN LATERAL (SELECT * FROM document_evaluation WHERE application_id = a.id ORDER BY version_no DESC LIMIT 1) d ON true
                         WHERE a.posting_id = %s AND d.criteria_scores->'가치'->'cov' IS NOT NULL""", (posting_id,)).fetchall()
    allv = [r["cov"] for r in rows] or [cov]
    z = {}
    for v, x in cov.items():
        xs = [c[v] for c in allv if v in c]
        sd = statistics.pstdev(xs) if len(xs) > 1 else 0
        z[v] = round((x - statistics.mean(xs)) / sd, 2) if sd else 0.0
    low = sorted(z, key=lambda v: (z[v], cov[v]))[:2]
    ind = _indicators(db)
    quotes = {v: _quote_for(db, app_id, snap, v, ind.get(v, [])) for v in low}
    missing = [v for v in low if not quotes[v]]
    pick = missing[0] if missing else low[0]
    why = (f"인재상 '{VALUE_NAME[pick]}'의 근거가 이력서 원문에 없음 (지원자 간 비교 z {z[pick]})" if not quotes[pick]
           else f"두 가치 모두 원문 근거가 있어 지원자 간 비교가 더 낮은 '{VALUE_NAME[pick]}' (z {z[pick]})")
    return {"deficit_value": pick, "deficit_reason": why,
            "deficit_evidence": {"z": z, "후보": low, "원문 근거": quotes, "비교 지원자 수": len(allv)}}


def handoff(db, app_id: int) -> dict:
    """합격자만: '면접 확인 필요 목록'(요건 중 부족·근거 없음) + 결핍 가치 → handoff (document_evaluation 최신 판). 끝나면 코드가 상태를 바꾼다"""
    r = db.execute("""SELECT d.version_no, d.criteria_scores, d.handoff, p.job_role, p.career_level, a.resume_snapshot, a.posting_id
                      FROM document_evaluation d JOIN application a ON a.id = d.application_id JOIN job_posting p ON p.id = a.posting_id
                      WHERE d.application_id = %s ORDER BY d.version_no DESC LIMIT 1""", (app_id,)).fetchone()
    cs, h = r["criteria_scores"] or {}, dict(r["handoff"] or {})
    names = {x["id"]: x["text"] for x in cs.get("요건", [])}
    h["check_list"] = [names.get(x["req_id"], x["req_id"]) for x in cs.get("labels", []) if x["label"] in ("부족", "근거 없음")][:5]
    cov = (cs.get("가치") or {}).get("cov")
    if cov:                                          # 1차 AI 검토 때 잰 유사도가 있으면 문서 방법으로 (없으면 1차 파트가 넣은 값 그대로)
        h.update(deficit_value(db, app_id, r["posting_id"], r["resume_snapshot"], cov))
    elif not h.get("deficit_value"):
        h["deficit_value"], h["deficit_reason"] = "GRW", "결핍 가치 없음 — 기본값 (1차 AI 검토 전 지원 건)"
    h.setdefault("job_role", r["job_role"])
    h.setdefault("applied_level", {"new": "신입", "junior": "주니어", "senior": "시니어"}[r["career_level"]])
    db.execute("UPDATE document_evaluation SET handoff = %s WHERE application_id = %s AND version_no = %s", (Jsonb(h), app_id, r["version_no"]))
    return h

