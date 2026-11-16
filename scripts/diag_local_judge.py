"""사내 판정 모델(qwen3:4b) 형식 실패 진단 (11/16). 고정 답변 세트(bench/answers.json)로 기술 답변 판정 프롬프트를 사내 모델에 직접 보내
모델이 낸 원래 글·끝난 이유(길이 제한에 걸렸는지)·형식 오류 종류를 센다. DB는 읽기만, 판정 결과는 저장하지 않는다.
  python scripts/diag_local_judge.py [개수=15] [--max-tokens N]
"""
import argparse
import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api import llm_gate as G  # noqa: E402
from api import prompt as P  # noqa: E402
from api.db import connect  # noqa: E402
from api.interview import store  # noqa: E402
from api.real_modules import JTech, NONE  # noqa: E402

import llm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("n", nargs="?", type=int, default=15)
ap.add_argument("--max-tokens", type=int, default=1024)
ap.add_argument("--before", action="store_true", help="고치기 전 형식(JTech 그대로)으로")
a = ap.parse_args()
items = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "answers.json"), encoding="utf-8"))[: a.n]
with connect() as db:
    qs = {r["question_text"]: r for r in db.execute("SELECT * FROM interview_question WHERE kind = 'tech'").fetchall()}
_, local = G.choices(None)
kinds, lens, secs, scores = collections.Counter(), [], [], {}
for x in items:
    q = qs.get(x["question"])
    if q is None:
        continue
    with connect() as db:
        ctx = store.context(db, q["session_id"])
    qq = store.to_question(q)
    docs = [d for d in ctx.docs if d.chunk_id in qq.source_doc_ids]
    text, _ = P.render("judge_tech", question=qq.question_text, key_points=", ".join(qq.key_points) or NONE,
                       evidence="\n\n".join(d.body[:1200] for d in docs) or NONE, answer=x["text"])
    system, _ = P.load("system")
    m = llm.chat_model(local, "eval", timeout=120, max_tokens=a.max_tokens)
    t = time.monotonic()
    schema = JTech if a.before else G.LOCAL_SCHEMA.get(JTech, JTech)      # 관문(llm_gate)이 사내 모델에 쓰는 형식
    r = m.with_structured_output(schema, method="json_schema", include_raw=True).invoke([("system", system), ("human", text)])
    secs.append(time.monotonic() - t)
    meta = r["raw"].response_metadata
    out = r["raw"].content or ""
    lens.append(meta.get("eval_count"))
    if r["parsed"] is not None:
        o = r["parsed"]
        kind = f"성공 {o.accuracy + o.company_fit + o.depth + o.specificity}점"
        scores.setdefault(x["level"], []).append(o.accuracy + o.company_fit + o.depth + o.specificity)
    elif meta.get("done_reason") == "length":
        kind = "길이 제한에 잘림"
    else:
        try:
            json.loads(out)
            kind = "JSON은 맞지만 형식 위반: " + str(r["parsing_error"])[:120].replace("\n", " ")
        except json.JSONDecodeError:
            kind = "JSON이 깨짐"
    kinds[kind.split(":")[0].split(" ")[0]] += 1
    print(f"{x['key']:>10} {kind[:90]} | 토큰 {meta.get('eval_count')} | {time.monotonic() - t:.1f}s | 끝 {out[-60:]!r}", flush=True)
print("\n요약:", dict(kinds), "| 출력 토큰 평균", round(sum(l or 0 for l in lens) / max(1, len(lens))), "최대", max(l or 0 for l in lens),
      "| 평균", round(sum(secs) / max(1, len(secs)), 1), "초", "| 수준별 평균 점수", {k: round(sum(v) / len(v)) for k, v in scores.items()})
