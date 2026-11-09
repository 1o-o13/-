"""회사 문서 검색 (RAG TRD 9절, 활동다이어그램 1109 4·6쪽 '공용 부품: 검색').
메타 필터(부르는 쪽이 후보 docs로 넘김) → BM25(kiwipiepy 형태소) ∥ bge-m3 벡터(pgvector) → RRF(k=60) → 상위 k.
2차 면접은 재정렬(CE)을 쓰지 않는다 (11-05 폐기, CE는 답변 관련성에만). 절대 점수 관문 없음.
벡터를 못 쓰면(임베딩 없음·Ollama 꺼짐) BM25만으로 순위를 내고 info['vector']=False로 표시한다.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass

from typing import TYPE_CHECKING

import httpx
from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from contracts import CompanyDoc

RRF_K = 60
log = logging.getLogger(__name__)
_kiwi = None
_kiwi_lock = threading.Lock()                     # worker는 스레드 16개가 분석기 하나를 같이 씀 (11/10 메모리)
_tok: dict[str, list[str]] = {}                   # 청크 본문 토큰 (청크 id → 토큰, 프로세스마다)
_has_vec: list[bool] = []                          # DB에 임베딩이 하나라도 있는가 (없으면 벡터 검색을 부르지 않음)
_POS = ("NN", "NR", "NP", "VV", "VA", "XR", "SL", "SH", "SN")   # 명사·동사·형용사 어근·외국어·숫자


@dataclass
class Hit:
    doc: CompanyDoc
    rrf: float
    bm25_rank: int | None
    vec_rank: int | None


def tokens(text: str) -> list[str]:
    global _kiwi
    with _kiwi_lock:
        if _kiwi is None:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        return [t.form.lower() for t in _kiwi.tokenize(text) if t.tag.startswith(_POS)]


def _embed(text: str) -> list[float] | None:
    try:
        r = httpx.post(os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434") + "/api/embed",
                       json={"model": os.environ.get("EMBED_MODEL", "bge-m3"), "input": text[:4000]}, timeout=30)
        r.raise_for_status()
        return r.json()["embeddings"][0]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        log.info("벡터 검색 건너뜀: %s", e)
        return None


def _vector_ranks(query: str, ids: list[str]) -> dict[str, int]:
    """후보 청크 중 임베딩이 있는 것의 코사인 순위 (1부터). 못 하면 빈 dict"""
    if not _has_vec:
        try:
            from api.db import connect
            with connect() as db:
                _has_vec.append(bool(db.execute("SELECT 1 FROM company_doc_chunk WHERE embedding IS NOT NULL LIMIT 1").fetchone()))
        except Exception:  # noqa: BLE001
            _has_vec.append(False)
    q = _embed(query) if _has_vec[0] else None
    if q is None:
        return {}
    try:
        from api.db import connect
        with connect() as db:
            rows = db.execute("""SELECT doc || '#' || sec AS id FROM company_doc_chunk
                                 WHERE doc || '#' || sec = ANY(%s) AND embedding IS NOT NULL
                                 ORDER BY embedding <=> %s::vector""", (ids, str(q))).fetchall()
    except Exception as e:  # noqa: BLE001  DB에 벡터가 없으면 BM25만
        log.info("벡터 검색 실패: %s", e)
        return {}
    return {r["id"]: i for i, r in enumerate(rows, 1)}


def rank(query: str, docs: list[CompanyDoc], k: int | None = None, vector: bool = True) -> list[Hit]:
    """docs(메타 필터를 통과한 후보)를 query로 Hybrid 검색해 RRF 순으로. k=None이면 전부"""
    if not docs or not query.strip():
        return [Hit(d, 0.0, None, None) for d in docs][:k]
    for d in docs:
        if d.chunk_id not in _tok:
            _tok[d.chunk_id] = tokens(f"{d.topic or ''} {d.body}") or ["_"]
    corpus = [_tok[d.chunk_id] for d in docs]
    scores = BM25Okapi(corpus).get_scores(tokens(query) or ["_"])
    order = sorted(range(len(docs)), key=lambda i: -scores[i])
    bm = {docs[i].chunk_id: r for r, i in enumerate(order, 1) if scores[i] > 0}
    vec = _vector_ranks(query, [d.chunk_id for d in docs]) if vector else {}
    hits = [Hit(d, sum(1 / (RRF_K + r) for r in (bm.get(d.chunk_id), vec.get(d.chunk_id)) if r),
                bm.get(d.chunk_id), vec.get(d.chunk_id)) for d in docs]
    hits.sort(key=lambda h: (-h.rrf, h.doc.chunk_id))
    return hits[:k]


def experience_query(resume_text: str) -> str:
    """본 질문 질의: 이력서 경험 서술(프로젝트·경력·기술) 부분. 가린 이력서 JSON에서 글만 모은다"""
    return " ".join(re.findall(r"[0-9A-Za-z가-힣+#.]{2,}", resume_text))[:3000]
