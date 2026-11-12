"""AI 판정 일관성 시험 (11/12). 같은 기술 답변을 같은 모델로 여러 번, 그리고 외부(Claude)·사내(qwen3) 모델로 판정해
점수가 얼마나 흔들리는지·모델끼리 얼마나 다른지 잰다. api 컨테이너 안에서 실행 (MODULE_MODE=real).
  python scripts/judge_consistency.py [답변 수=30] [반복=3]
답변: bench/answers.json(build_answer_set.py가 만든 고정 세트: 질문 10개 × 좋음·보통·약함)이 있으면 그것, 없으면 DB의 기술 답변
→ records/judge_consistency.csv (답변·모델·회차별 점수) + records/measurements.csv 요약 줄. DB는 바꾸지 않는다 (읽기만)
"""
import csv
import datetime as dt
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api import modules as M  # noqa: E402
from api import nli_client  # noqa: E402

nli_client.ce = lambda *a, **k: None    # 관련성 점수(CE, CPU)는 판정 점수와 무관하고 한 번에 수십 초라 이 시험에서는 뺀다
from api.db import connect  # noqa: E402
from api.interview import store  # noqa: E402

REC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "records")
N, K = (int(sys.argv[1]) if len(sys.argv) > 1 else 30), (int(sys.argv[2]) if len(sys.argv) > 2 else 3)
SET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "answers.json")


def main() -> int:
    with connect() as db:
        if os.path.exists(SET):
            fixed = json.load(open(SET, encoding="utf-8"))[:N]
            qs = {r["id"]: r for r in db.execute("SELECT q.*, q.session_id FROM interview_question q WHERE q.id = ANY(%s)",
                                                 ([x["question_id"] for x in fixed],)).fetchall()}
            rows = [{**qs[x["question_id"]], "answer_id": x["key"], "stt_text": x["text"], "level": x["level"]} for x in fixed]
        else:
            rows = db.execute("""SELECT a.id AS answer_id, a.stt_text, q.*, q.session_id, '' AS level FROM interview_answer a
                                 JOIN interview_question q ON q.id = a.question_id
                                 WHERE a.stt_text IS NOT NULL AND q.kind = 'tech' AND q.min_tier >= 3
                                 ORDER BY a.id LIMIT %s""", (N,)).fetchall()
        ctxs = {sid: store.context(db, sid) for sid in {r["session_id"] for r in rows}}
    out = []
    for r in rows:
        q, base = store.to_question(r), ctxs[r["session_id"]]
        for side, consent in (("외부", True), ("사내", False)):        # 국외 전송 동의가 없으면 사내 모델로 (route 규칙 그대로)
            ctx = base.model_copy(update={"overseas_consent": consent})
            for k in range(1, K + 1):
                j = M.judge_answer(q, r["stt_text"], ctx)
                out.append({"answer_id": r["answer_id"], "level": r["level"], "side": side, "model": j.model, "try": k, "score": j.score})
                print(r["answer_id"], side, j.model, k, j.score, flush=True)
    with open(os.path.join(REC, "judge_consistency.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    # 요약: 같은 모델 반복 점수 차(최대-최소) 평균, 모델 간 평균 점수 차, 상관
    summ, means = [], {}
    for side in ("외부", "사내"):
        spreads = []
        for aid in {x["answer_id"] for x in out}:
            s = [x["score"] for x in out if x["answer_id"] == aid and x["side"] == side and x["score"] is not None]
            if s:
                spreads.append(max(s) - min(s))
                means.setdefault(aid, {})[side] = st.mean(s)
        model = next((x["model"] for x in out if x["side"] == side), "-")
        summ.append((f"판정 반복 점수 차 평균 ({side} {model})", round(st.mean(spreads), 1) if spreads else "",
                     f"기술 답변 {len(spreads)}개 × {K}번, 같은 답변 최고-최저 (100점 만점)"))
        summ.append((f"판정 반복 점수 차 최대 ({side} {model})", max(spreads) if spreads else "", "가장 흔들린 답변"))
    for side in ("외부", "사내"):                                   # 수준별 평균: 좋음 > 보통 > 약함 순서로 매기는지
        lv = {}
        for x in out:
            if x["side"] == side and x["score"] is not None and x["level"]:
                lv.setdefault(x["level"], []).append(x["score"])
        if lv:
            summ.append((f"수준별 평균 점수 ({side})", " / ".join(f"{k} {st.mean(v):.0f}" for k, v in lv.items()), "좋음 > 보통 > 약함이면 구분함"))
    pairs = [(m["외부"], m["사내"]) for m in means.values() if "외부" in m and "사내" in m]
    if len(pairs) >= 3:
        a, b = zip(*pairs)
        summ.append(("외부·사내 모델 평균 점수 차", round(st.mean(abs(x - y) for x, y in pairs), 1), f"같은 답변 {len(pairs)}개"))
        summ.append(("외부·사내 모델 점수 상관", round(st.correlation(a, b), 2), "1에 가까울수록 같은 순서로 매김"))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(os.path.join(REC, "measurements.csv"), "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for item, v, note in summ:
            w.writerow([now, "판정 일관성", item, v, note])
    for x in summ:
        print(x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
