"""company_doc_chunk 중 임베딩이 빈 청크를 bge-m3로 채운다. 머리말 [새벽소프트 | 문서 | 난이도 | 부서 | 섹션] + 본문 (META_SPEC v0.3).
실행: DATABASE_URL=postgresql://... OLLAMA_BASE_URL=http://ollama:11434 python scripts/embed_docs.py
"""
import os
import time

import httpx
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
    rows = db.execute("""SELECT doc, sec, '[새벽소프트 | ' || doc_title || ' | ' || coalesce(ct_band, '') || ' | ' ||
                         array_to_string(dept, '·') || ' | ' || sec_title || '] ' || body
                         FROM company_doc_chunk WHERE embedding IS NULL""").fetchall()
    for doc, sec, text in rows:
        for wait in (0, 5, 15, None):                # Ollama가 다른 모델로 바쁘면 잠깐 실패할 수 있어 3번 더 (11/10)
            try:
                r = httpx.post(os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434") + "/api/embed",
                               json={"model": os.environ.get("EMBED_MODEL", "bge-m3"), "input": text}, timeout=120)
                r.raise_for_status()
                break
            except httpx.HTTPError:
                if wait is None:
                    raise
                time.sleep(wait)
        db.execute("UPDATE company_doc_chunk SET embedding = %s::vector WHERE doc = %s AND sec = %s",
                   (str(r.json()["embeddings"][0]), doc, sec))
    print(f"임베딩 채움: {len(rows)}개")
