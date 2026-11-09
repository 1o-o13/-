"""CE·NLI 판정 서버(nli 컨테이너) 부르기. NLI_URL이 비었거나 서버가 응답하지 않으면 None
→ CE는 '측정 안 함'(점수로만 분기), NLI는 '검사 생략'(인용 확인 + 금지어 검사만) 표시 (RAG TRD 12쪽 대체 경로)"""
import logging
import os

import httpx

log = logging.getLogger(__name__)


def _post(path: str, body: dict, timeout: float = 20) -> dict | None:
    url = os.environ.get("NLI_URL", "")
    if not url:
        return None
    try:
        r = httpx.post(url + path, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        log.warning("nli 서버 %s 실패: %s", path, e)
        return None


def ce(question: str, answer: str) -> float | None:
    """CE(질문, 답변) 관련성 0~1 (bge-reranker-v2-m3 정방향). 분기 근거로만, 점수에 더하지 않음"""
    r = _post("/ce", {"pairs": [[question, answer[:2000]]]})
    return r["scores"][0] if r else None


def nli(premise: str, hypothesis: str) -> dict | None:
    """{entailment, neutral, contradiction, model}: premise(답변 원문) ⇒ hypothesis(꼬리질문의 전제, 평서문)"""
    return _post("/nli", {"premise": premise[:2000], "hypothesis": hypothesis})
