"""얼굴·표정·목소리 비교 공통 (11/12): 시험 자료 목록, 결과 기록(records/affect_bench.csv), 본인 대조 지표"""
import csv
import datetime as dt
import glob
import os
import re
import statistics as st

DATA, OUT, REC = "/bench/data", "/bench/out/affect", "/records/affect_bench.csv"
FIELDS = ["date", "area", "model", "test", "n", "metric", "value", "note"]


def faces() -> list[tuple[str, str]]:
    """(표기, 경로) — bench/data/face/<표기>_<n>.jpg"""
    out = []
    for p in sorted(glob.glob(f"{DATA}/face/*.jpg")):
        m = re.match(r"(.+)_\d+\.jpg$", os.path.basename(p))
        if m:
            out.append((m.group(1), p))
    return out


def lfw() -> list[tuple[str, str]]:
    """(사람 이름, 경로) — 다른 사람 얼굴 60명 × 2장"""
    return [(re.sub(r"_\d+\.jpg$", "", os.path.basename(p)), p) for p in sorted(glob.glob(f"{DATA}/lfw/*.jpg"))]


def styles() -> list[tuple[str, str, str]]:
    """(말투, 문장, 경로) — bench/data/style/<말투>_<문장>.wav"""
    out = []
    for p in sorted(glob.glob(f"{DATA}/style/*.wav")):
        m = re.match(r"(.+)_([slt]\d\d)\.wav$", os.path.basename(p))
        if m:
            out.append((m.group(1), m.group(2), p))
    return out


def record(rows: list[dict]) -> None:
    new = not os.path.exists(REC)
    with open(REC, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        today = dt.date.today().isoformat()
        for r in rows:
            w.writerow({"date": today, **r})
            print(r, flush=True)


def detail(name: str, rows: list[dict]) -> None:
    os.makedirs(OUT, exist_ok=True)
    if rows:
        with open(f"{OUT}/{name}.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
            w.writeheader()
            w.writerows(rows)


def verify_metrics(model: str, dist, thr: float, sec_per: float, note: str = "") -> list[dict]:
    """dist(a, b) → 거리 (작을수록 같은 사람, 얼굴 못 찾으면 None). 본인 증명사진 vs 본인 웹캠 · 타인(LFW) vs 본인 사진 · LFW 같은/다른 사람 쌍"""
    ref = f"{DATA}/face_ref.jpg"
    me = [p for k, p in faces() if k != "spoof"]
    others = lfw()
    d_me = [d for d in (dist(ref, p) for p in me) if d is not None]
    d_other = [d for d in (dist(ref, p) for _, p in others) if d is not None]
    names = sorted({n for n, _ in others})
    by = {n: [p for m, p in others if m == n] for n in names}
    same = [d for d in (dist(*by[n][:2]) for n in names if len(by[n]) >= 2) if d is not None]
    diff = [d for d in (dist(by[a][0], by[b][0]) for a, b in zip(names, names[1:])) if d is not None]
    rows = []
    a = "본인 대조"
    if d_me:
        rows += [{"area": a, "model": model, "test": "본인 사진 vs 본인 웹캠", "n": len(d_me), "metric": "평균 거리", "value": round(st.mean(d_me), 3), "note": note},
                 {"area": a, "model": model, "test": "본인 사진 vs 본인 웹캠", "n": len(d_me), "metric": f"통과율(기준 {thr})",
                  "value": round(sum(d <= thr for d in d_me) / len(d_me), 3), "note": "표정·시선이 다른 웹캠 장면 포함"},
                 {"area": a, "model": model, "test": "본인 사진 vs 본인 웹캠", "n": len(d_me), "metric": "최대 거리", "value": round(max(d_me), 3), "note": ""}]
    if d_other:
        rows += [{"area": a, "model": model, "test": "타인(LFW) vs 본인 사진", "n": len(d_other), "metric": "최소 거리", "value": round(min(d_other), 3), "note": ""},
                 {"area": a, "model": model, "test": "타인(LFW) vs 본인 사진", "n": len(d_other), "metric": f"오통과 수(기준 {thr})",
                  "value": sum(d <= thr for d in d_other), "note": "0이어야 함"}]
    if d_me and d_other:
        rows.append({"area": a, "model": model, "test": "분리 여유", "n": "", "metric": "타인 최소 - 본인 최대", "value": round(min(d_other) - max(d_me), 3),
                     "note": "0보다 크면 기준값 하나로 완전히 나뉨"})
    if same and diff:
        rows += [{"area": a, "model": model, "test": "LFW 같은 사람 쌍", "n": len(same), "metric": f"통과율(기준 {thr})",
                  "value": round(sum(d <= thr for d in same) / len(same), 3), "note": "다른 사람들에게도 통하는지"},
                 {"area": a, "model": model, "test": "LFW 다른 사람 쌍", "n": len(diff), "metric": f"오통과율(기준 {thr})",
                  "value": round(sum(d <= thr for d in diff) / len(diff), 3), "note": ""}]
    rows.append({"area": a, "model": model, "test": "속도", "n": "", "metric": "장당 초(CPU)", "value": round(sec_per, 3), "note": ""})
    return rows
