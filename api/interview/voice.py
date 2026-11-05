"""질문 음성 (TTS_MODE=real → tts 컨테이너 Supertonic). 질문을 만들 때 미리 만들어 /audio/q/{qid}-{글 해시}.wav에 두고, 화면은 그 파일을 받는다.
TTS가 꺼져 있거나 실패하면 None → 화면이 브라우저 음성(임시)이나 글로 진행 (IV-17). 질문 글은 개인정보가 아니라 응시가 끝나도 지우지 않는다(임시).
"""
import hashlib
import os
import threading

import httpx


def enabled() -> bool:
    return os.environ.get("TTS_MODE", "stub") == "real"


def path(qid: int, text: str) -> str:
    """질문 번호 + 글 해시: 다시 적재해 번호가 1부터 돌아와도 다른 질문에 예전 음성이 나가지 않게"""
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    return os.path.join(os.environ.get("AUDIO_DIR", "/audio"), "q", f"{qid}-{h}.wav")


def make(qid: int, text: str) -> str | None:
    """이미 있으면 그대로, 없으면 tts에 요청해 저장 → 파일 경로. 실패하면 None"""
    p = path(qid, text)
    if os.path.exists(p):
        return p
    if not enabled():
        return None
    try:
        r = httpx.post(f"{os.environ.get('TTS_URL', 'http://tts:8000')}/speak", json={"text": text}, timeout=60)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, p)                          # 반쯤 쓴 파일을 화면이 받지 않게
    return p


def prefetch(items: list[tuple[int, str]]) -> None:
    """질문을 만든 직후 음성을 뒤에서 미리 만든다 (요청을 기다리게 하지 않음)"""
    if enabled() and items:
        threading.Thread(target=lambda: [make(q, t) for q, t in items], daemon=True).start()
