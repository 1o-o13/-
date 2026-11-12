"""DeepFace 비교 (11/12): 본인 대조 모델 4개(ArcFace=지금 서비스·Facenet512·SFace·GhostFaceNet) + 표정 7가지.
서비스 face 이미지(고정 버전)에서 실행:
  docker compose run --rm --no-deps -v bench:/bench -v records:/records -v bench_models:/bm -e DEEPFACE_HOME=/bm/deepface face python /bench/face_deepface.py
얼굴 찾기는 서비스와 같은 YuNet. 기준값: ArcFace는 서비스 값 0.45, 나머지는 DeepFace 기본값 (코사인 거리)
"""
import sys
import time
from collections import Counter

import numpy as np

sys.path.insert(0, "/bench")
from affect_common import detail, faces, record, verify_metrics  # noqa: E402
from deepface import DeepFace  # noqa: E402

MODELS = {"ArcFace": 0.45, "Facenet512": 0.30, "SFace": 0.593, "GhostFaceNet": 0.65}
_cache: dict = {}


def emb(model: str, path: str):
    k = (model, path)
    if k not in _cache:
        try:
            r = DeepFace.represent(img_path=path, model_name=model, detector_backend="yunet", enforce_detection=True)
            _cache[k] = np.asarray(r[0]["embedding"])
        except Exception:  # noqa: BLE001  얼굴 못 찾음
            _cache[k] = None
    return _cache[k]


def main():
    rows = []
    for model, thr in MODELS.items():
        DeepFace.build_model(model)
        t, n = time.monotonic(), 0

        def dist(a, b, model=model):
            nonlocal n
            x, y = emb(model, a), emb(model, b)
            n += 1
            if x is None or y is None:
                return None
            return float(1 - x @ y / (np.linalg.norm(x) * np.linalg.norm(y)))
        rows += verify_metrics(f"DeepFace {model}" + (" (지금 서비스)" if model == "ArcFace" else ""), dist, thr, 0.0)
        rows[-1]["value"] = round((time.monotonic() - t) / max(1, len([k for k in _cache if k[0] == model])), 3)
    # 표정 7가지 (화남·혐오·두려움·기쁨·슬픔·놀람·무표정)
    det = []
    for label, p in faces():
        try:
            r = DeepFace.analyze(img_path=p, actions=["emotion"], detector_backend="yunet", enforce_detection=True, silent=True)[0]
            det.append({"label": label, "file": p.split("/")[-1], "pred": r["dominant_emotion"], **{k: round(v, 1) for k, v in r["emotion"].items()}})
        except Exception:  # noqa: BLE001
            det.append({"label": label, "file": p.split("/")[-1], "pred": "얼굴 없음"})
    detail("deepface_emotion", det)
    for label in dict.fromkeys(d["label"] for d in det):
        c = Counter(d["pred"] for d in det if d["label"] == label)
        rows.append({"area": "표정", "model": "DeepFace Emotion (7가지)", "test": label, "n": sum(c.values()), "metric": "가장 많이 나온 결과",
                     "value": c.most_common(1)[0][0], "note": " · ".join(f"{k} {v}" for k, v in c.most_common())})
    record(rows)


if __name__ == "__main__":
    main()
