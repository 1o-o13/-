"""판정 시험용 고정 답변 세트 (11/12). 시험 데이터의 답변은 가짜 모듈이 만든 조각이라 판정 일관성·사람 채점 비교에 못 쓴다.
기술 질문 10개마다 수준이 다른 답변 3개를 만든다: 좋음(예시 답변 기능으로 생성) · 보통(좋은 답의 앞부분만) · 약함(일반론).
api 컨테이너 안에서 실행 (MODULE_MODE=real).  python scripts/build_answer_set.py [질문 수=10]  → bench/answers.json
한 번 만든 세트를 계속 쓴다 (다시 만들면 지난 결과와 비교가 안 됨). 실제 지원자 답변이 아니라 '시험용으로 만든 답변'임을 기록에 남긴다
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pydantic import BaseModel  # noqa: E402

from api import llm_gate  # noqa: E402
from api.db import connect  # noqa: E402
from api.interview import store  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "answers.json")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
WEAK = "그 부분은 직접 해 본 경험이 많지는 않지만, 상황에 맞게 잘 판단해서 처리하겠습니다. 팀원들과 충분히 상의하고 좋은 방법을 찾아 적용하겠습니다."


class SampleOut(BaseModel):
    answer: str


def main() -> int:
    with connect() as db:
        qs = db.execute("""SELECT DISTINCT ON (q.question_text) q.*, q.session_id FROM interview_question q
                           WHERE q.kind = 'tech' AND q.question_type = 'main' AND q.min_tier >= 3 ORDER BY q.question_text, q.id""").fetchall()
        qs = sorted(qs, key=lambda r: r["id"])[:N]
        ctxs = {r["session_id"]: store.context(db, r["session_id"]) for r in qs}
    out = []
    for r in qs:
        q, ctx = store.to_question(r), ctxs[r["session_id"]]
        docs = [d.body[:800] for d in ctx.docs if d.chunk_id in q.source_doc_ids]
        g = llm_gate.call("sample_answer", SampleOut, "sample_answer",
                          {"question": q.question_text, "evidence": "\n".join(docs) or "(없음)", "resume": ctx.resume_text[:2000] or "(없음)"},
                          llm_cfg=ctx.llm, min_tier=q.min_tier, consent=True, session_id=r["session_id"], max_tokens=2000).out
        if g is None:
            print("생성 실패", r["id"])
            continue
        sents = [x for x in re.split(r"(?<=[.!?다])\s+", g.answer.strip()) if x]
        medium = " ".join(sents[:max(1, len(sents) * 2 // 5)])
        for level, text in (("좋음", g.answer.strip()), ("보통", medium), ("약함", WEAK)):
            out.append({"key": f"{r['id']}-{level}", "question_id": r["id"], "session_id": r["session_id"], "level": level,
                        "question": q.question_text, "text": text})
        print(r["id"], len(g.answer), flush=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(out)}개 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
