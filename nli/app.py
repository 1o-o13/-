"""CE·NLI 판정 서버 (RAG TRD 12·18쪽). api·worker만 부른다 (외부에 포트 안 엶).
- POST /ce  {"pairs": [[질문, 답변], ...]} → {"scores": [0~1]}  bge-reranker-v2-m3 정방향 (질문, 답변), sigmoid. 분기 근거로만 (CE 0.4)
- POST /nli {"premise": 답변 원문, "hypothesis": 꼬리질문의 전제(평서문)} → {"entailment", "neutral", "contradiction"}  mDeBERTa
모델은 처음 시작 때 HF_HOME(/models 볼륨)에 한 번 내려받는다. 둘 다 CPU float32 (GPU 6GB는 qwen3·STT가 씀, 임시)
"""
import threading

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer

CE_MODEL = "BAAI/bge-reranker-v2-m3"
NLI_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
app = FastAPI()
_m: dict = {}
_lock = threading.Lock()
torch.set_num_threads(4)


def _load(name: str):
    with _lock:
        if name not in _m:
            tok = AutoTokenizer.from_pretrained(name)
            model = AutoModelForSequenceClassification.from_pretrained(name).eval()
            _m[name] = (tok, model)
    return _m[name]


@app.on_event("startup")
def warm() -> None:
    threading.Thread(target=lambda: (_load(CE_MODEL), _load(NLI_MODEL)), daemon=True).start()


class CeIn(BaseModel):
    pairs: list[tuple[str, str]]


class NliIn(BaseModel):
    premise: str
    hypothesis: str


@app.get("/health")
def health():
    if CE_MODEL not in _m or NLI_MODEL not in _m:
        raise HTTPException(503, "모델 준비 중")
    return {"ce": CE_MODEL, "nli": NLI_MODEL}


@app.post("/ce")
def ce(body: CeIn):
    tok, model = _load(CE_MODEL)
    with torch.inference_mode():
        x = tok([p[0] for p in body.pairs], [p[1] for p in body.pairs], padding=True, truncation=True, max_length=512, return_tensors="pt")
        s = torch.sigmoid(model(**x).logits.view(-1).float())
    return {"scores": [round(float(v), 4) for v in s], "model": CE_MODEL}


@app.post("/nli")
def nli(body: NliIn):
    tok, model = _load(NLI_MODEL)
    with torch.inference_mode():
        x = tok(body.premise, body.hypothesis, truncation=True, max_length=512, return_tensors="pt")
        p = torch.softmax(model(**x).logits[0].float(), -1)
    labels = {v.lower(): k for k, v in model.config.id2label.items()}
    return {k: round(float(p[labels[k]]), 4) for k in ("entailment", "neutral", "contradiction")} | {"model": NLI_MODEL}
