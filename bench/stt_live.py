"""녹음 확인용 STT (11/12). 녹음 페이지가 저장할 때마다 그 녹음을 받아 적어 정답과 비교해 돌려준다. stt 이미지 컨테이너 안에서 실행.
  GET /stt/<id> → {"text", "ref", "cer", "sec"}
지금 서비스와 같은 모델·설정(large-v3-turbo, VAD)이지만 CPU(int8)로 돈다 — 면접 STT·Ollama가 GPU를 쓰고 있어서. 눈으로 확인하는 용도.
비교 기준값은 tasks.ps1 bench(GPU)로 따로 낸다.
"""
import http.server
import json
import os
import re
import sys
import time

sys.path.insert(0, "/bench")
from faster_whisper import WhisperModel  # noqa: E402
from sentences import SENTENCES  # noqa: E402
from stt_bench import score  # noqa: E402

TRUTH = {sid: (text, terms) for sid, text, terms in SENTENCES}
m = WhisperModel(os.environ.get("STT_WHISPER_MODEL", "large-v3-turbo"), device="cpu", compute_type="int8")
print("모델 준비됨", flush=True)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        mt = re.fullmatch(r"/stt/([slt]\d\d)", self.path)
        p = f"/bench/data/mine/me_{mt.group(1)}.wav" if mt else ""
        if not mt or not os.path.exists(p):
            body, code = {"error": "녹음 없음"}, 404
        else:
            t = time.monotonic()
            segs, _ = m.transcribe(p, language="ko", beam_size=5, vad_filter=True, condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)).strip()
            ref, terms = TRUTH[mt.group(1)]
            sc = score(ref, text, terms)
            body = {"text": text, "ref": ref, "cer": round(sc["char_err"] / max(1, sc["chars"]), 3),
                    "terms": f"{sc['term_hit']}/{sc['terms']}", "sec": round(time.monotonic() - t, 1)}
            code = 200
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


http.server.HTTPServer(("0.0.0.0", 8766), H).serve_forever()     # 한 번에 하나씩 (모델 하나)
