"""얼굴 대조 (본인 확인·면접 중 주기 확인). FACE_MODE=real → face 컨테이너(InsightFace buffalo_l, 큐 'face'), stub → 늘 일치 구간.
프레임은 메모리에서만 넘기고 저장하지 않는다. 기준 사진은 지원서 증명사진(application.photo_object_key, PHOTO_DIR).
거리(1 - 코사인 유사도) ≤0.55 일치 · ≤0.75 애매(재촬영) · 그 위 불일치.
11/16 DeepFace ArcFace(기준 0.45) → InsightFace. 실측(bench/, 엑셀 '얼굴 비교'): 본인 웹캠 35장 0.17~0.34, LFW 같은 사람 쌍 95%가 0.52 이하,
다른 사람은 가장 닮아도 0.88 이상 → 일치 0.55 (다른 사람과 0.33 넘게 떨어짐)"""
MATCH_MAX = 0.55      # 낮을수록 엄격 (더 닮아야 통과)
UNCLEAR_MAX = 0.75
REAL = "InsightFace buffalo_l"   # 실제 대조 모델 이름 (identity_check.model에 기록)
import base64
import logging
import os

from api.interview import media_stub

log = logging.getLogger(__name__)
TIMEOUT = 30


def model() -> str:
    return REAL if os.environ.get("FACE_MODE", "stub") == "real" else media_stub.FACE_MODEL


def band(d: float | None) -> str:
    return "no_face" if d is None else "match" if d <= MATCH_MAX else "unclear" if d <= UNCLEAR_MAX else "mismatch"


def distance(frame: bytes, photo_key: str | None) -> float | None:
    """코사인 거리, 얼굴을 못 찾으면 None. 대조 서버가 응답하지 않아도 None (→ 사람이 확인)"""
    if os.environ.get("FACE_MODE", "stub") != "real":
        return media_stub.face_distance(frame, photo_key)
    from worker.app import celery
    try:
        r = celery.send_task("face.verify", args=[base64.b64encode(frame).decode(), photo_key], queue="face").get(timeout=TIMEOUT)
    except Exception as e:                           # noqa: BLE001  대조 실패로 응시를 막지 않는다
        log.warning("얼굴 대조 실패: %s", e)
        return None
    return r.get("distance")


def photo_path(key: str) -> str:
    return os.path.join(os.environ.get("PHOTO_DIR", "/photos"), os.path.basename(key))
