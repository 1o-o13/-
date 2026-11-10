"""api·worker를 띄우고, 파이썬 코드·프롬프트가 바뀌면 끊김 없이 새 코드로 바꾼다 (11/10). 손으로 docker compose restart 하지 않아도 된다.
  python scripts/devserve.py api    -- uvicorn api.main:app ... --workers 4
  python scripts/devserve.py worker -- celery -A worker.app worker ...
- api: uvicorn에 SIGHUP → 작업 프로세스를 하나씩, 새 프로세스가 준비된 뒤 옛 것을 내린다 (요청 끊김 없음)
- worker: 새 Celery worker를 먼저 띄우고, 옛 worker는 SIGTERM(하던 작업을 끝내고 종료)
- Windows Docker는 파일 변경 알림이 컨테이너에 안 와서 2초마다 수정 시각을 본다
"""
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIRS = ("api", "app_6_1", "stubs_6_1", "worker")
EXT = (".py", ".md")                               # 프롬프트(api/prompts/*.md)도
POLL = 2.0


def sig() -> tuple:
    out = []
    for d in DIRS:
        for base, dirs, files in os.walk(os.path.join(ROOT, d)):
            dirs[:] = [x for x in dirs if not x.startswith((".", "__"))]
            for f in files:
                if f.endswith(EXT) and not f.startswith("test_"):
                    st = os.stat(os.path.join(base, f))
                    out.append((f, st.st_mtime_ns, st.st_size))
    return tuple(sorted(out))


def main() -> None:
    mode, cmd = sys.argv[1], sys.argv[sys.argv.index("--") + 1:]
    proc = subprocess.Popen(cmd, cwd=ROOT)
    signal.signal(signal.SIGTERM, lambda *_: (proc.send_signal(signal.SIGTERM), sys.exit(0)))
    last = sig()
    while True:
        time.sleep(POLL)
        if proc.poll() is not None:                # 본 프로세스가 죽으면 컨테이너도 끝 (restart: unless-stopped가 다시 띄움)
            sys.exit(proc.returncode)
        now = sig()
        if now == last:
            continue
        time.sleep(POLL)                           # 여러 파일을 한꺼번에 저장하는 중일 수 있어 한 번 더 기다린다
        changed = sorted({f for f, *_ in set(sig()) ^ set(last)})[:5]
        last = sig()
        print(f"[devserve] 코드 바뀜 ({', '.join(changed)}) → {mode} 새 코드로 교체", flush=True)
        if mode == "api":
            proc.send_signal(signal.SIGHUP)
        else:
            new = subprocess.Popen(cmd + ["-n", f"w{int(time.time())}@%h"], cwd=ROOT)   # 이름이 겹치지 않게
            proc.send_signal(signal.SIGTERM)       # 옛 worker: 받은 작업을 끝내고 종료 (새 worker가 이미 큐를 받는 중)
            proc = new


if __name__ == "__main__":
    main()
