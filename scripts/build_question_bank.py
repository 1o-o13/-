"""직무별 회사 질문 은행(question_bank)을 회사 문서에서 만든다. tasks.ps1 seed가 load_corpus 다음에 실행.
- 직무(job_role)마다 그 부서(dept) tier 3 공개 청크(프로젝트·해결된 장애 회고, 2차, 개요 제외) 하나에 기술 본 질문 하나
- 질문 = 문서 첫 문장으로 상황을 주고 설계·구현을 묻는 기본 질문 (모델 'rule'). 검증(api/pregen.verify)을 통과한 것만 verified
- 지원 건마다 1차 합격 때 이 질문을 이력서에 맞게 다듬어(실제 모듈은 LLM) 다시 검증한다
실행: DATABASE_URL=... python scripts/build_question_bank.py
"""
import os
import re
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api import pregen  # noqa: E402
from api.interview.engine import DEPT  # noqa: E402

from contracts import CompanyDoc, Question  # noqa: E402,I001

KEY_POINTS = ["설계 방법", "선택 이유", "검증·측정"]


def main(url: str | None = None) -> int:
    n = 0
    with psycopg.connect(url or os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row) as db:
        for role, dept in DEPT.items():
            rows = db.execute("""SELECT doc, sec, doc_type, tier, topic, status, forbid, body FROM company_doc_chunk
                                 WHERE tier = 3 AND '2차' = ANY(stages) AND disclosure <> 'internal' AND sec <> 'ov' AND %s = ANY(dept)
                                   AND (doc_type = 'project' OR (doc_type = 'incident' AND coalesce(status, 'resolved') = 'resolved'))
                                 ORDER BY doc, sec""", (dept,)).fetchall()
            texts: list[str] = []
            for r in rows:
                cid = f"{r['doc']}#{r['sec']}"
                lead = re.split(r"(?<=[.다])\s", r["body"].strip(), maxsplit=1)[0][:150]
                q = Question(kind="tech", tech_stack=r["topic"], question_text=f"이런 상황을 맡았다고 해 볼게요. {lead} 어떻게 설계하고 구현하시겠어요?",
                             basis=cid, source_doc_ids=[cid], min_tier=3, key_points=KEY_POINTS, model="rule")
                doc = CompanyDoc(chunk_id=cid, doc_type=r["doc_type"], tier=3, topic=r["topic"], forbid=r["forbid"], body=r["body"])
                check = pregen.verify(q, {cid: doc}, texts)
                failed = ", ".join(k for k, v in check.items() if k != "ok" and v is not True)
                db.execute("""INSERT INTO question_bank(job_role, topic, chunk_id, question_text, key_points, model, verified, verify_note)
                              VALUES (%s, %s, %s, %s, %s, 'rule', %s, %s)
                              ON CONFLICT (job_role, chunk_id) DO UPDATE SET question_text = EXCLUDED.question_text,
                                  verified = EXCLUDED.verified, verify_note = EXCLUDED.verify_note""",
                           (role, r["topic"], cid, q.question_text, Jsonb(KEY_POINTS), check["ok"], failed or "통과"))
                texts.append(q.question_text)
                n += 1
    print(f"질문 은행 {n}개 (직무 {len(DEPT)}개)")
    return n


if __name__ == "__main__":
    main()
