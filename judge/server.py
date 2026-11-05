"""코딩 테스트 채점 실행기 (judge 컨테이너). 지원자 코드를 받아 케이스 입력마다 실행하고 출력·시간·상태만 돌려준다.
기대 출력은 받지 않는다 (비교는 api가 한다). Python 표준 라이브러리만 쓴다.

컨테이너 쪽 격리 (compose.yml): 네트워크 없음(internal), 읽기 전용 파일시스템 + /tmp만 쓰기, CPU·메모리·프로세스 수 제한, 권한 없는 사용자
여기서 더 막는 것: 케이스마다 제한 시간(벽시계), CPU 시간·파일 크기 한도, 출력 1MB까지만 읽기, 끝나면 프로세스 그룹째 종료

POST /run  {"language": "python"|"java", "code": str, "time_limit_ms": int, "cases": [{"id": str, "input": str}]}
→ {"compile_error": str|null, "results": [{"id", "status": ok|tle|re|ce, "stdout", "stderr", "time_ms"}]}
"""
import json
import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT_LIMIT = 1 << 20          # 출력 1MB
COMPILE_SEC = 15


def _limits(cpu_sec: int, python: bool):
    def apply():
        os.setsid()                                                    # 끝날 때 자식까지 한꺼번에 끝내려고
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (OUT_LIMIT * 4, OUT_LIMIT * 4))
        if python:                                                     # JVM은 가상 메모리를 크게 잡아 -Xmx로 따로 막는다
            resource.setrlimit(resource.RLIMIT_AS, (512 << 20, 512 << 20))
    return apply


def _run(cmd: list[str], stdin: str, limit_ms: int, cwd: str, python: bool) -> dict:
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         preexec_fn=_limits(max(1, limit_ms // 1000 + 1), python), env={"PATH": os.environ["PATH"]})
    try:
        out, err = p.communicate(stdin.encode(), timeout=limit_ms / 1000)
        status = "ok" if p.returncode == 0 else "re"
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, err = p.communicate()
        status = "tle"
    ms = int((time.monotonic() - t0) * 1000)
    if status == "re" and p.returncode in (-signal.SIGXCPU, -signal.SIGKILL):
        status = "tle"
    return {"status": status, "stdout": out[:OUT_LIMIT].decode(errors="replace"), "stderr": err[-2000:].decode(errors="replace"),
            "time_ms": ms}


def judge(req: dict) -> dict:
    lang, code, limit = req["language"], req["code"], int(req["time_limit_ms"])
    work = tempfile.mkdtemp(dir="/tmp")
    try:
        if lang == "python":
            path = os.path.join(work, "main.py")
            open(path, "w", encoding="utf-8").write(code)
            cmd = ["python3", "-I", path]                               # -I: 사용자 모듈 경로 무시
        elif lang == "java":
            open(os.path.join(work, "Main.java"), "w", encoding="utf-8").write(code)
            c = _run(["javac", "-encoding", "UTF-8", "-J-Xmx256m", "Main.java"], "", COMPILE_SEC * 1000, work, False)
            if c["status"] != "ok":
                return {"compile_error": (c["stderr"] or "컴파일 시간 초과")[:2000],
                        "results": [{"id": x["id"], "status": "ce", "stdout": "", "stderr": "", "time_ms": 0} for x in req["cases"]]}
            cmd = ["java", "-Xmx256m", "-Xss64m", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1", "-cp", work, "Main"]
            limit += 1000                                               # JVM 시작 시간 (문서: 제한 + 여유)
        else:
            return {"compile_error": f"지원하지 않는 언어: {lang}", "results": []}
        return {"compile_error": None,
                "results": [{"id": x["id"], **_run(cmd, x["input"], limit, work, lang == "python")} for x in req["cases"]]}
    finally:
        shutil.rmtree(work, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):                                                   # 상태 확인
        self._send(200, {"ok": True, "python": shutil.which("python3") is not None, "java": shutil.which("java") is not None})

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, {"error": "없음"})
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(200, judge(req))
        except Exception as e:                                          # 잘못된 요청 → 400 (채점 서버는 계속 살아 있어야 함)
            self._send(400, {"error": f"{type(e).__name__}: {e}"})

    def _send(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):                                          # 지원자 코드가 로그에 남지 않게
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
