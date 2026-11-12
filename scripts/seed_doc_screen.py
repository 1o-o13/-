"""이미 1차 결과를 발표한 공고(시험 데이터)에도 AI 1차 검토 근거를 채운다 (11/12).
시험 데이터의 발표된 공고는 AI 검토(S0) 없이 결정까지 들어가 있어서, 관리자 화면에 '무엇을 보고 뽑았는지'가 비어 있었다.

- 처음 한 번은 실제 S0(api/screen.run: 비교 검색 → LLM 의견 → 코드 검증)을 돌리고 결과를 seed/doc_screen_cache.json에 저장
- 다음 seed부터는 저장해 둔 결과를 그대로 넣는다 (LLM을 다시 부르지 않음, 같은 근거가 나옴)
- 지원 상태·결정·발표는 바꾸지 않는다 (근거만 더함). 접수 중·심사 중 공고는 담당관이 'AI 1차 검토 실행'을 눌러 돌린다
  python scripts/seed_doc_screen.py   (api 컨테이너 안, tasks.ps1 seed가 부름)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api import screen  # noqa: E402
from api.db import connect  # noqa: E402

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "seed", "doc_screen_cache.json")


def main() -> int:
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    with connect() as db:
        apps = db.execute("""SELECT a.id, p.title || ' / ' || c.email AS key FROM application a
                             JOIN job_posting p ON p.id = a.posting_id JOIN candidate c ON c.id = a.candidate_id
                             WHERE EXISTS (SELECT 1 FROM announcement n WHERE n.posting_id = a.posting_id AND n.stage = 'document'
                                           AND n.status IN ('published', 'corrected'))
                             ORDER BY a.id""").fetchall()
        made = loaded = 0
        for a in apps:
            last = db.execute("""SELECT version_no, criteria_scores, handoff FROM document_evaluation WHERE application_id = %s
                                 ORDER BY version_no DESC LIMIT 1""", (a["id"],)).fetchone()
            if last and "결론" in (last["criteria_scores"] or {}):
                continue
            if a["key"] in cache:
                screen.save(db, a["id"], last, cache[a["key"]])
                loaded += 1
            else:
                t = time.monotonic()
                cache[a["key"]] = screen.run(db, a["id"])
                made += 1
                print(f"S0 {a['key']} {time.monotonic() - t:.0f}s → {cache[a['key']].get('결론')}", flush=True)
                json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            db.commit()
    print(f"발표된 공고 근거: 저장분 {loaded}건 · 새로 검토 {made}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
