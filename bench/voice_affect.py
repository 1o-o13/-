"""목소리 톤 비교 (11/12): 같은 문장을 말투 5가지(보통·작게·자신 있게·망설이며·더듬으며)로 녹음한 25개로
  --engine rules       지금 규칙 (stt/app.py tone(): 음량·높이·말 빠르기·쉼 → 작은 목소리·망설임·빠른 말·자신감·차분) + 앞 답변 기준 비교(제안)
  --engine disfluency  군말('음·어·그')·되풀이 세기: faster-whisper 낱말 시간 + 군말을 남기라는 안내 문장       (stt 이미지)
  --engine emotion2vec 음성 감정 9가지 (emotion2vec_plus_base)                                                   (bench-funasr)
  --engine sensevoice  SenseVoice 감정 태그 (STT와 함께 나오는 HAPPY·NEUTRAL·SAD 등)                              (bench-funasr)
결과: records/affect_bench.csv + bench/out/affect/<엔진>.csv
"""
import argparse
import re
import statistics as st
import sys
from collections import Counter

sys.path.insert(0, "/bench")
from affect_common import detail, record, styles  # noqa: E402

KO = {"normal": "보통", "quiet": "작게", "confident": "자신 있게", "hesitant": "망설이며", "stutter": "더듬으며"}


def summarize(model: str, det: list[dict], col: str, rows: list[dict], area: str = "목소리 톤"):
    for s in KO:
        c = Counter(d[col] for d in det if d["style"] == s)
        if c:
            rows.append({"area": area, "model": model, "test": KO[s], "n": sum(c.values()), "metric": "가장 많이 나온 결과",
                         "value": c.most_common(1)[0][0], "note": " · ".join(f"{k} {v}" for k, v in c.most_common())})


def rules(rows):
    sys.path.insert(0, "/app")                       # stt 이미지의 서비스 코드 (stt_app.tone)
    import stt_app as a
    det = []
    for s, sid, p in styles():
        segs, _ = a.model().transcribe(p, language="ko", beam_size=5, vad_filter=True, condition_on_previous_text=False)
        segs = list(segs)
        tones = a.tone(p, segs) if segs else []
        c = Counter(t["label"] for t in tones)
        det.append({"style": s, "sid": sid, "main": c.most_common(1)[0][0] if c else "말 없음", "labels": dict(c),
                    "db": round(st.mean(t["db"] for t in tones), 1) if tones else None,
                    "cps": round(st.mean(t["cps"] for t in tones), 1) if tones else None,
                    "pause_max": max((t["pause"] for t in tones), default=0)})
    detail("rules", det)
    summarize("지금 규칙 (음량·높이·빠르기·쉼)", det, "main", rows)
    # 제안: 같은 사람의 '보통' 답변 음량을 기준으로 비교 (한 답변 안 평균과 비교하면 전체를 작게 말한 답변은 못 잡음)
    base = {d["sid"]: d["db"] for d in det if d["style"] == "normal" and d["db"] is not None}
    q = [d for d in det if d["style"] == "quiet" and d["db"] is not None and d["sid"] in base]
    n_ = [d for d in det if d["style"] != "quiet" and d["db"] is not None and d["sid"] in base and d["style"] != "normal"]
    if q:
        rows.append({"area": "목소리 톤", "model": "지금 규칙", "test": "작게", "n": len(q), "metric": "'작은 목소리' 잡은 비율",
                     "value": round(sum(d["labels"].get("작은 목소리", 0) > 0 for d in q) / len(q), 3), "note": "한 답변 안 평균과 비교 → 전체를 작게 말하면 놓침"})
        rows.append({"area": "목소리 톤", "model": "제안: 앞 답변(보통) 기준 -6dB", "test": "작게", "n": len(q), "metric": "'작은 목소리' 잡은 비율",
                     "value": round(sum(d["db"] < base[d["sid"]] - 6 for d in q) / len(q), 3), "note": "같은 응시의 앞 답변 음량을 기준으로"})
        if n_:
            rows.append({"area": "목소리 톤", "model": "제안: 앞 답변(보통) 기준 -6dB", "test": "작게 아닌 녹음", "n": len(n_), "metric": "잘못 잡은 비율",
                         "value": round(sum(d["db"] < base[d["sid"]] - 6 for d in n_) / len(n_), 3), "note": "낮을수록 좋음"})


FILLER = re.compile(r"^(음+|어+|으+|그+|저+|아+|에+)[.,…]*$")


def disfluency(rows):
    from faster_whisper import WhisperModel
    m = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8_float16")
    det = []
    for s, sid, p in styles():
        segs, _ = m.transcribe(p, language="ko", beam_size=5, vad_filter=False, word_timestamps=True, condition_on_previous_text=False,
                               initial_prompt="음, 어, 그러니까, 저, 저는… 음, 그, 그게… 네, 어…")   # 군말을 지우지 말라는 안내
        words = [w for g in segs for w in (g.words or [])]
        toks = [re.sub(r"[^\w]", "", w.word) for w in words]
        fillers = sum(bool(FILLER.match(w.word.strip())) for w in words)
        repeats = sum(1 for a, b in zip(toks, toks[1:]) if a and (a == b or (len(a) >= 1 and b.startswith(a) and len(a) <= 2)))
        gaps = sum(1 for a, b in zip(words, words[1:]) if b.start - a.end >= 0.8)
        det.append({"style": s, "sid": sid, "fillers": fillers, "repeats": repeats, "long_gaps": gaps,
                    "flag": "말 끊김 있음" if fillers + repeats + gaps >= 2 else "없음", "text": " ".join(w.word.strip() for w in words)})
    detail("disfluency", det)
    summarize("군말·되풀이·긴 쉼 세기 (faster-whisper 낱말 시간)", det, "flag", rows, area="말 끊김·더듬음")
    for s in KO:
        xs = [d for d in det if d["style"] == s]
        if xs:
            rows.append({"area": "말 끊김·더듬음", "model": "군말·되풀이·긴 쉼 세기", "test": KO[s], "n": len(xs), "metric": "평균 군말 / 되풀이 / 긴 쉼",
                         "value": f"{st.mean(d['fillers'] for d in xs):.1f} / {st.mean(d['repeats'] for d in xs):.1f} / {st.mean(d['long_gaps'] for d in xs):.1f}",
                         "note": "망설이며·더듬으며가 보통보다 커야 구분됨"})


def emotion2vec(rows):
    from funasr import AutoModel
    m = AutoModel(model="emotion2vec/emotion2vec_plus_base", hub="hf", disable_update=True)
    det = []
    for s, sid, p in styles():
        r = m.generate(p, granularity="utterance", extract_embedding=False)[0]
        i = max(range(len(r["scores"])), key=lambda k: r["scores"][k])
        det.append({"style": s, "sid": sid, "pred": r["labels"][i].split("/")[-1], "score": round(r["scores"][i], 3)})
    detail("emotion2vec", det)
    summarize("emotion2vec_plus_base (9가지)", det, "pred", rows)


def sensevoice(rows):
    from funasr import AutoModel
    m = AutoModel(model="FunAudioLLM/SenseVoiceSmall", hub="hf", disable_update=True)
    det = []
    for s, sid, p in styles():
        raw = m.generate(input=p, language="ko", use_itn=False)[0]["text"]
        tags = re.findall(r"<\|([A-Z_]+)\|>", raw)
        emo = next((t for t in tags if t in ("HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED", "EMO_UNKNOWN")), "?")
        det.append({"style": s, "sid": sid, "pred": emo, "tags": " ".join(tags)})
    detail("sensevoice_emotion", det)
    summarize("SenseVoice 감정 태그", det, "pred", rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["rules", "disfluency", "emotion2vec", "sensevoice"])
    a = ap.parse_args()
    if not styles():
        sys.exit("bench/data/style 녹음이 없습니다")
    rows: list[dict] = []
    {"rules": rules, "disfluency": disfluency, "emotion2vec": emotion2vec, "sensevoice": sensevoice}[a.engine](rows)
    record(rows)
