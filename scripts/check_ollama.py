"""실제 Ollama 서버 점검 (GPU 서버 또는 내 PC에서 실행).

  python scripts/check_ollama.py                       # 운영 기준 qwen3:4b · qwen3:1.7b · bge-m3
  (qwen3:4b 약 2.5GB · qwen3:1.7b 약 1.4GB라 VRAM 6GB 개발 PC에서도 기본값으로 시험 가능)

확인 항목: 서버 버전(qwen3는 0.6.6 이상), 모델 내려받기 여부, 한국어 판정 JSON 형식, 응답 시간(30초 규칙),
임베딩 1024차원(DB faq.embedding = vector(1024)).
먼저: ollama pull qwen3:4b && ollama pull qwen3:1.7b && ollama pull bge-m3
"""
import argparse
import json
import sys
import time

import httpx

MIN_VERSION = (0, 6, 6)
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "judgement": {"type": "string", "enum": ["우수", "무난", "미흡", "무응답"]},
        "rationale": {"type": "string"},
    },
    "required": ["judgement", "rationale"],
}
PROMPT = (
    "너는 기술 면접 평가자다. 질문: 데이터베이스 인덱스가 조회를 빠르게 하는 이유는?\n"
    "지원자 답변: 인덱스는 B-트리 같은 정렬된 구조라서 전체를 다 보지 않고 필요한 위치를 바로 찾을 수 있습니다. "
    "대신 쓰기 때 인덱스도 갱신해야 해서 느려질 수 있습니다.\n"
    "판정(우수/무난/미흡/무응답)과 근거 한 문장을 JSON으로."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--eval", default="qwen3:4b")
    ap.add_argument("--fast", default="qwen3:1.7b")
    ap.add_argument("--embed", default="bge-m3")
    a = ap.parse_args()
    ok = True
    c = httpx.Client(base_url=a.url, timeout=120)

    v = c.get("/api/version").json()["version"]
    vt = tuple(int(x) for x in v.split("-")[0].split(".")[:3])
    print(f"[{'OK' if vt >= MIN_VERSION else 'NG'}] Ollama {v} (qwen3는 0.6.6 이상)")
    ok &= vt >= MIN_VERSION

    have = {m["name"] for m in c.get("/api/tags").json()["models"]}
    for m in (a.eval, a.fast, a.embed):
        hit = m in have or f"{m}:latest" in have
        print(f"[{'OK' if hit else 'NG'}] 모델 {m}" + ("" if hit else f"  → ollama pull {m}"))
        ok &= hit
    if not ok:
        sys.exit(1)

    for m in (a.eval, a.fast):
        t = time.monotonic()
        r = c.post("/api/chat", json={"model": m, "stream": False, "format": JUDGE_SCHEMA, "options": {"temperature": 0},
                                      "messages": [{"role": "user", "content": PROMPT}]}).json()
        sec = time.monotonic() - t
        try:
            out = json.loads(r["message"]["content"])
            good = out["judgement"] in JUDGE_SCHEMA["properties"]["judgement"]["enum"] and bool(out["rationale"])
        except (KeyError, ValueError):
            out, good = r.get("message", {}).get("content"), False
        print(f"[{'OK' if good else 'NG'}] {m} 판정 {sec:.1f}초 (30초 넘으면 대체 모델) → {out}")
        ok &= good and sec < 30

    e = c.post("/api/embed", json={"model": a.embed, "input": ["결과 발표는 언제인가요", "발표일이 궁금해요", "비밀번호를 잊었어요"]}).json()["embeddings"]
    dot = lambda x, y: sum(p * q for p, q in zip(x, y))
    near, far = dot(e[0], e[1]), dot(e[0], e[2])
    print(f"[{'OK' if len(e[0]) == 1024 else 'NG'}] {a.embed} {len(e[0])}차원 (DB vector(1024))")
    print(f"[{'OK' if near > far else 'NG'}] 비슷한 질문 유사도 {near:.3f} > 다른 질문 {far:.3f}")
    ok &= len(e[0]) == 1024 and near > far
    print("결과:", "통과" if ok else "확인 필요")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
