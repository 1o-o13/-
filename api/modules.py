"""질문 생성·판정·평가 모듈을 고르는 유일한 곳. MODULE_MODE=stub → stubs_6_1/fake_modules.py, real → api/real_modules.py (LLM).
api·worker는 여기 이름만 쓴다 (q1_verify, q2_value, pick_project, tech_main, tech_followup, tech_retry, check_followup, fix_followup,
judge_answer, evaluate_interview, load_docs).
"""
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# contracts·fake_modules·flow는 서로를 최상위 이름으로 import하므로 경로를 그대로 연다 (같은 클래스가 두 번 생기지 않게 api도 이 이름으로 쓴다)
sys.path.insert(0, os.path.join(_ROOT, "stubs_6_1"))
sys.path.insert(0, os.path.join(_ROOT, "app_6_1"))

from contracts import CompanyDoc  # noqa: E402

MODE = os.environ.get("MODULE_MODE", "stub")
if MODE == "stub":
    import fake_modules as _impl  # noqa: E402
elif MODE == "real":
    from api import real_modules as _impl  # noqa: E402   LLM 질문 생성·판정 (api/real_modules.py)
else:
    raise RuntimeError(f"MODULE_MODE={MODE!r}: stub 또는 real만 가능")

q1_verify = _impl.q1_verify
q2_value = _impl.q2_value
pick_project = _impl.pick_project
tech_main = _impl.tech_main
tech_followup = _impl.tech_followup
tech_retry = _impl.tech_retry
check_followup = _impl.check_followup
fix_followup = _impl.fix_followup
judge_answer = _impl.judge_answer
evaluate_interview = _impl.evaluate_interview
MODEL_NAME = getattr(_impl, "STUB", "llm")


def provider_of(model: str) -> str:
    """판정·평가 기록의 제공사 칸: 실제로 쓴 모델에서 (가짜 모듈이면 stub)"""
    return "ollama" if model.startswith("qwen") else "anthropic" if model.startswith("claude") else "rule" if model == "rule" else MODE


def load_docs(db, ct_band: str | None, dept: str, level: str) -> list[CompanyDoc]:
    """질문 근거 후보. 임시: 진짜 retrieve()(조건 필터 → BM25 ∥ bge-m3 → RRF → 재정렬)가 오기 전까지 조건 필터만 한다.
    - 2차 단계, internal 제외(어떤 프롬프트에도 넣지 않음), 개요(sec=ov) 제외
    - 본 질문(tier 3): 난이도 대역·부서·직급 일치 / 꼬리질문(tier 2·1): 같은 주제면 대역·부서 무관 (주제는 fake_modules가 맞춤)"""
    rows = db.execute("""SELECT doc, sec, doc_type, tier, topic, status, related, forbid, body FROM company_doc_chunk
                         WHERE '2차' = ANY(stages) AND disclosure <> 'internal' AND sec <> 'ov'
                           AND (tier IN (1, 2) OR (tier = 3 AND ct_band IS NOT DISTINCT FROM %s
                                                   AND %s = ANY(dept) AND %s = ANY(level)))
                         ORDER BY tier DESC, doc, sec""", (ct_band, dept, level)).fetchall()
    return [CompanyDoc(chunk_id=f"{r['doc']}#{r['sec']}", doc_type=r["doc_type"], tier=r["tier"], topic=r["topic"],
                       status=r["status"], related=r["related"], forbid=r["forbid"], body=r["body"]) for r in rows]
