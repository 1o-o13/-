"""내 목소리 녹음 페이지 (11/12). 고정 문장을 한 줄씩 보여 주고 읽은 소리를 bench/data/mine/me_<id>.wav로 저장한다.
  python bench/record_server.py   → http://localhost:8765
이 PC 안에서만 돈다 (밖으로 보내지 않음). 녹음은 개인정보라 bench/data/mine은 저장소에 올리지 않는다.
"""
import http.server
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "mine")
os.makedirs(OUT, exist_ok=True)

import sys  # noqa: E402
sys.path.insert(0, HERE)
from sentences import SENTENCES  # noqa: E402
from affect_items import FACES, SHOTS_PER_FACE, STYLE_SENTENCES, STYLES  # noqa: E402

STYLE_DIR, FACE_DIR = os.path.join(HERE, "data", "style"), os.path.join(HERE, "data", "face")   # 11/12 말투·표정 비교용
os.makedirs(STYLE_DIR, exist_ok=True)
os.makedirs(FACE_DIR, exist_ok=True)
TEXT = {i: t for i, t, _ in SENTENCES}


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, open(os.path.join(HERE, "record.html"), "rb").read(), "text/html; charset=utf-8")
        if self.path in ("/style", "/face"):
            return self._send(200, open(os.path.join(HERE, f"{self.path[1:]}.html"), "rb").read(), "text/html; charset=utf-8")
        if self.path == "/style/items":
            return self._send(200, json.dumps([{"style": k, "label": lb, "hint": h, "id": i, "text": TEXT[i],
                                                "done": os.path.exists(os.path.join(STYLE_DIR, f"{k}_{i}.wav"))}
                                               for k, lb, h in STYLES for i in STYLE_SENTENCES], ensure_ascii=False).encode())
        if self.path == "/face/items":
            return self._send(200, json.dumps([{"key": k, "label": lb, "hint": h, "shots": SHOTS_PER_FACE,
                                                "done": os.path.exists(os.path.join(FACE_DIR, f"{k}_{SHOTS_PER_FACE}.jpg"))}
                                               for k, lb, h in FACES], ensure_ascii=False).encode())
        if self.path == "/sentences":
            done = {f[3:6] for f in os.listdir(OUT) if f.startswith("me_")}
            return self._send(200, json.dumps([{"id": i, "text": t, "done": i in done} for i, t, _ in SENTENCES], ensure_ascii=False).encode())
        if m := re.fullmatch(r"/stt/([slt]\d\d)", self.path):       # 확인용 STT(bench/stt_live.py, 127.0.0.1:8766)로 넘김
            import urllib.error
            import urllib.request
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:8766/stt/{m.group(1)}", timeout=120) as r:
                    return self._send(200, r.read())
            except (urllib.error.URLError, OSError):
                return self._send(503, json.dumps({"error": "확인용 STT가 꺼져 있습니다"}, ensure_ascii=False).encode())
        if m := re.fullmatch(r"/clip/([slt]\d\d)", self.path):
            p = os.path.join(OUT, f"me_{m.group(1)}.wav")
            return self._send(200, open(p, "rb").read(), "audio/wav") if os.path.exists(p) else self._send(404, b"{}")
        self._send(404, b"{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        styles, faces = "|".join(k for k, _, _ in STYLES), "|".join(k for k, _, _ in FACES)
        if (m := re.fullmatch(rf"/save-style/({styles})/([slt]\d\d)", self.path)) and 0 < n < 20_000_000:
            with open(os.path.join(STYLE_DIR, f"{m.group(1)}_{m.group(2)}.wav"), "wb") as f:
                f.write(self.rfile.read(n))
            return self._send(200, b'{"ok":true}')
        if (m := re.fullmatch(rf"/save-face/({faces})/([1-9])", self.path)) and 0 < n < 5_000_000:
            with open(os.path.join(FACE_DIR, f"{m.group(1)}_{m.group(2)}.jpg"), "wb") as f:
                f.write(self.rfile.read(n))
            return self._send(200, b'{"ok":true}')
        m = re.fullmatch(r"/save/([slt]\d\d)", self.path)
        if not m or not 0 < n < 20_000_000:
            return self._send(400, b'{"ok":false}')
        with open(os.path.join(OUT, f"me_{m.group(1)}.wav"), "wb") as f:
            f.write(self.rfile.read(n))
        self._send(200, b'{"ok":true}')

    def log_message(self, *a):
        pass


print("녹음 페이지: http://localhost:8765 · 말투 녹음 /style · 표정 촬영 /face  (끝내려면 Ctrl+C)")
http.server.ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
