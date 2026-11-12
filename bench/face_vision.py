"""얼굴·표정 비교 (11/12, bench-vision 이미지, CPU):
- 본인 대조: InsightFace buffalo_l (얼굴 찾기 SCRFD + ArcFace 계열)
- 사진 비추기(대리 응시) 감지: DeepFace MiniFASNet (ONNX)
- 표정: HSEmotion 8가지 · 지금 화면의 규칙(MediaPipe 얼굴 계수 → 미소·놀람·긴장·시선 아래·무표정, web/lib/face.ts와 같은 기준)
  docker run --rm -v bench:/bench -v records:/records -v bench_models:/models bench-vision python /bench/face_vision.py
"""
import os
import sys
import time
import urllib.request  # noqa: F401  hsemotion이 가져오지 않고 쓴다
from collections import Counter

os.environ["HOME"] = "/models/home"     # hsemotion 가중치(~/.hsemotion)를 모델 볼륨에 두고 다시 받지 않게

import cv2
import numpy as np

sys.path.insert(0, "/bench")
from affect_common import detail, faces, record, verify_metrics  # noqa: E402


def insight(rows):
    import insightface
    app = insightface.app.FaceAnalysis(name="buffalo_l", root="/models/insightface", providers=["CPUExecutionProvider"],
                                       allowed_modules=["detection", "recognition"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    cache, t = {}, time.monotonic()

    def emb(p):
        if p not in cache:
            f = app.get(cv2.imread(p))
            cache[p] = max(f, key=lambda x: x.bbox[2] - x.bbox[0]).normed_embedding if f else None
        return cache[p]

    def dist(a, b):
        x, y = emb(a), emb(b)
        return None if x is None or y is None else float(1 - x @ y)
    rows += verify_metrics("InsightFace buffalo_l", dist, 0.65, 0.0, "기준 0.65 = 유사도 0.35 (흔히 쓰는 값)")
    rows[-1]["value"] = round((time.monotonic() - t) / max(1, len(cache)), 3)
    return app


def spoof(rows, app):
    from deepface.models.spoofing.onnx.FasNet import Fasnet
    fas, det = Fasnet(), []
    for label, p in faces():
        img = cv2.imread(p)
        f = app.get(img)
        if not f:
            det.append({"label": label, "file": p.split("/")[-1], "real": None})
            continue
        x1, y1, x2, y2 = max(f, key=lambda x: x.bbox[2] - x.bbox[0]).bbox.astype(int)
        real, score = fas.analyze(img, (x1, y1, x2 - x1, y2 - y1))
        det.append({"label": label, "file": p.split("/")[-1], "real": bool(real), "score": round(float(score), 3)})
    detail("fasnet", det)
    live = [d for d in det if d["label"] != "spoof" and d["real"] is not None]
    fake = [d for d in det if d["label"] == "spoof" and d["real"] is not None]
    m = "DeepFace MiniFASNet (사진 위조 감지)"
    if live:
        rows.append({"area": "대리 응시 감지", "model": m, "test": "실제 얼굴", "n": len(live), "metric": "진짜로 본 비율",
                     "value": round(sum(d["real"] for d in live) / len(live), 3), "note": "높을수록 좋음 (낮으면 정상 응시자를 의심)"})
    if fake:
        rows.append({"area": "대리 응시 감지", "model": m, "test": "휴대폰 화면 속 사진", "n": len(fake), "metric": "가짜로 잡은 비율",
                     "value": round(sum(not d["real"] for d in fake) / len(fake), 3), "note": "높을수록 좋음"})


def rule_label(shapes: dict) -> str:
    """web/lib/face.ts expression()과 같은 기준"""
    g = lambda *n: sum(shapes.get(k, 0) for k in n) / len(n)   # noqa: E731
    smile, brow, press = g("mouthSmileLeft", "mouthSmileRight"), g("browDownLeft", "browDownRight"), g("mouthPressLeft", "mouthPressRight")
    up, jaw, down = g("browInnerUp"), g("jawOpen"), g("eyeLookDownLeft", "eyeLookDownRight")
    if smile > 0.4:
        return "미소"
    if up > 0.5 and jaw > 0.3:
        return "놀람"
    if brow > 0.4 or press > 0.4:
        return "긴장"
    if down > 0.5:
        return "시선 아래"
    return "무표정"


def expressions(rows, app):
    import mediapipe as mp
    from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
    from mediapipe.tasks.python import BaseOptions, vision
    lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path="/bench/face_landmarker.task"), output_face_blendshapes=True, num_faces=2))
    hse = HSEmotionRecognizer(model_name="enet_b0_8_best_vgaf")
    det = []
    for label, p in faces():
        img = cv2.imread(p)
        r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        shapes = {c.category_name: c.score for c in r.face_blendshapes[0]} if r.face_blendshapes else {}
        f = app.get(img)
        hs = "얼굴 없음"
        if f:
            x1, y1, x2, y2 = np.clip(max(f, key=lambda x: x.bbox[2] - x.bbox[0]).bbox.astype(int), 0, None)
            hs, _ = hse.predict_emotions(cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2RGB), logits=False)
        det.append({"label": label, "file": p.split("/")[-1], "rule": rule_label(shapes) if shapes else "얼굴 없음", "hsemotion": hs,
                    **{k: round(shapes.get(k, 0), 2) for k in ("mouthSmileLeft", "browInnerUp", "jawOpen", "browDownLeft", "mouthPressLeft",
                                                              "eyeLookDownLeft", "eyeBlinkLeft", "eyeWideLeft")}})
    lm.close()
    detail("expressions", det)
    for col, model in (("rule", "지금 규칙 (MediaPipe 계수, 5가지)"), ("hsemotion", "HSEmotion (8가지)")):
        for label in dict.fromkeys(d["label"] for d in det):
            c = Counter(d[col] for d in det if d["label"] == label)
            rows.append({"area": "표정", "model": model, "test": label, "n": sum(c.values()), "metric": "가장 많이 나온 결과",
                         "value": c.most_common(1)[0][0], "note": " · ".join(f"{k} {v}" for k, v in c.most_common())})


def main():
    rows = []
    app = insight(rows)
    spoof(rows, app)
    expressions(rows, app)
    record(rows)


if __name__ == "__main__":
    main()
