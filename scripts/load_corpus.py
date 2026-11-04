"""새벽소프트 문서(영찬 corpus_v3 + corpus_v3_add, META_SPEC v0.3)를 company_doc_chunk에 넣는다. ## 섹션 1개 = 청크 1개.
실행: DATABASE_URL=postgresql://... python scripts/load_corpus.py seed/corpus_v3 seed/corpus_v3_add
다음: python scripts/embed_docs.py 로 임베딩을 채운다.
"""
import os
import pathlib
import re
import sys

import psycopg

LIST = {"stages", "dept", "level", "related"}


def meta(line):
    m = re.match(r"\s*<!--meta:(.*)-->\s*$", line)
    return dict(kv.strip().split("=", 1) for kv in m.group(1).split(";") if "=" in kv) if m else None


def chunks(path):
    doc, title, sec = {}, "", None
    for line in path.read_text(encoding="utf-8").splitlines() + ["# END"]:
        if line.startswith("# ") or line.startswith("## "):
            if sec and sec.get("doc") and sec["body"].strip():
                yield sec
            if line.startswith("# "):
                doc, title, sec = {}, line[2:].strip(), None
            else:
                sec = {**doc, "doc_title": title, "sec_title": line[3:].strip(), "body": "", "forbid": []}
        elif (m := meta(line)) is not None:
            (sec.update(m) if sec is not None else doc.update(m))
        elif (f := re.match(r"\s*<!--forbid:(.*)-->", line)) and sec is not None:
            sec["forbid"] = [w.strip() for w in f.group(1).split("|") if w.strip()]
        elif sec is not None and not line.startswith("<!--"):
            sec["body"] += line + "\n"


def main(dirs):
    rows, seen = [], {}
    for d in dirs:
        for p in sorted(x for x in pathlib.Path(d).rglob("*.md") if x.name not in ("META_SPEC.md", "README.md")):
            for c in chunks(p):
                n = seen[c["doc"]] = seen.get(c["doc"], 0) + 1
                sec = c.get("sec") or f"s{n}"
                rows.append((c["doc"], sec, c["doc_title"], c["sec_title"], c["doc_type"], int(c["tier"]),
                             c.get("disclosure", "public"), c.get("topic"), c.get("status"),
                             *[c.get(k, "").split("|") if c.get(k) else [] for k in ("stages", "dept", "level")],
                             c.get("ct_band"), c.get("related", "").split("|") if c.get("related") else [], c["forbid"],
                             c["body"].strip()))
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        db.cursor().executemany("""INSERT INTO company_doc_chunk(doc, sec, doc_title, sec_title, doc_type, tier, disclosure, topic,
                                   status, stages, dept, level, ct_band, related, forbid, body)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                   ON CONFLICT (doc, sec) DO UPDATE SET body = EXCLUDED.body, embedding = NULL""", rows)
    print(f"청크 {len(rows)}개 적재")


if __name__ == "__main__":
    main(sys.argv[1:])
