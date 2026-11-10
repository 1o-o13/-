"""얼굴 대조 작업자 (face 컨테이너, CPU). worker·api가 큐 'face'로 보낸다.
face.verify(frame_b64, photo_key) → {"distance": 코사인 거리(1 - 유사도) | None(얼굴 없음), "model": MODEL}
- 11/16 InsightFace buffalo_l (얼굴 찾기 SCRFD + 인식 ArcFace 계열)로 바꿈. 같은 자료 비교(엑셀 '얼굴 비교')에서
  그 전 DeepFace ArcFace(기준 0.45)는 본인 웹캠 장면 80%만 통과, InsightFace는 본인 100%·다른 사람 0·LFW 같은 사람 97%
- 프레임은 메모리에서만 쓰고 저장하지 않는다. 지원서 사진은 PHOTO_DIR(읽기 전용)에서 읽는다
- 가중치(buffalo_l 약 280MB)는 처음 한 번 INSIGHTFACE_HOME(/models 볼륨)에 내려받는다. 사진에 얼굴이 여럿이면 가장 큰 얼굴
"""
import base64
import os
import threading

import cv2
import numpy as np
from celery import Celery
from celery.signals import worker_process_init

celery = Celery("face", broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"), backend=os.environ.get("REDIS_URL", "redis://redis:6379/0"))
MODEL = "InsightFace buffalo_l"
_app = None
_lock = threading.Lock()


def model():   # 이름을 app으로 하면 celery -A app이 이 함수를 Celery 앱으로 찾는다
    global _app
    with _lock:
        if _app is None:
            import insightface
            a = insightface.app.FaceAnalysis(name="buffalo_l", root=os.environ.get("INSIGHTFACE_HOME", "/models/insightface"),
                                             providers=["CPUExecutionProvider"], allowed_modules=["detection", "recognition"])
            a.prepare(ctx_id=-1, det_size=(640, 640))
            _app = a
    return _app


def _img(data: bytes):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def _emb(img):
    faces = model().get(img) if img is not None else []
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])).normed_embedding if faces else None


@celery.task(name="face.verify")
def verify(frame_b64: str, photo_key: str) -> dict:
    frame = _img(base64.b64decode(frame_b64))
    photo = os.path.join(os.environ.get("PHOTO_DIR", "/photos"), os.path.basename(photo_key))
    if frame is None or not os.path.exists(photo):
        return {"distance": None, "model": MODEL, "reason": "프레임 또는 사진 없음"}
    a, b = _emb(frame), _emb(cv2.imread(photo))
    if a is None or b is None:
        return {"distance": None, "model": MODEL, "reason": "얼굴을 찾지 못함 (" + ("웹캠" if a is None else "증명사진") + ")"}
    return {"distance": round(float(np.clip(1 - a @ b, 0, 2)), 4), "model": MODEL}


@celery.task(name="face.warm")
def warm() -> str:
    model()
    return "ok"


@worker_process_init.connect
def _warm(**_):
    """작업 프로세스마다 모델을 미리 올린다 (첫 본인 확인이 모델 적재를 기다리지 않게)"""
    try:
        model()
    except Exception:  # noqa: BLE001  미리 올리기 실패는 첫 요청 때 다시 올림
        pass
