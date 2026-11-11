"""시험·측정 기록을 records/에 쌓는다 (포트폴리오 엑셀용, 11/11). PC(호스트)에서 실행. tasks.ps1 test·e2e·seed가 자동으로 부른다.

  python scripts/record_run.py pytest  <로그>     # pytest 결과 한 줄 (통과·실패·소요) + 그때 모델·모드
  python scripts/record_run.py vitest  <로그>
  python scripts/record_run.py e2e     <로그>
  python scripts/record_run.py note <종류> <항목> <값> [비고]   # 부하 시험·얼굴 거리·STT 정확도 같은 측정값
  python scripts/record_run.py export              # DB 초기화 전에 직접 응시한 면접 기록 → records/interviews/
  python scripts/build_portfolio.py                # 쌓인 기록으로 records/portfolio_6_1.xlsx 다시 만들기

기록 파일: records/test_runs.csv (시험), records/measurements.csv (측정), records/interviews/*.json (면접)
"""
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REC = os.path.join(ROOT, "records")
KST = timezone(timedelta(hours=9))
RUN_COLS = ["일시", "종류", "범위", "통과", "실패", "소요_초", "모드", "모델", "비고"]
MEAS_COLS = ["일시", "종류", "항목", "값", "비고"]
ENV_KEYS = ["MODULE_MODE", "STT_MODE", "TTS_MODE", "FACE_MODE", "LLM_PROVIDER", "LLM_EVAL_MODEL", "LLM_FAST_MODEL",
            "LLM_LOCAL_FAST_MODEL", "EMBED_MODEL"]


def now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def read_log(path: str) -> str:
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):                 # PowerShell 5.1 Tee-Object는 UTF-16
        return raw.decode("utf-16")
    return raw.decode("utf-8", errors="replace")


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def env_snapshot() -> dict:
    """그때 쓰던 모드·모델 (api 컨테이너 환경). 비밀값은 읽지 않는다"""
    try:
        out = subprocess.run(["docker", "compose", "exec", "-T", "api", "env"], cwd=ROOT,
                             capture_output=True, text=True, timeout=30).stdout.splitlines()
        return {k: v for k, _, v in (x.partition("=") for x in out) if k in ENV_KEYS}
    except Exception:
        return {}


def append(name: str, cols: list[str], row: dict) -> None:
    os.makedirs(REC, exist_ok=True)
    path = os.path.join(REC, name)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:   # 엑셀에서 바로 열리게 BOM
        w = csv.DictWriter(f, cols)
        if new:
            w.writeheader()
        w.writerow(row)


def parse(kind: str, text: str) -> dict:
    t = strip_ansi(text)
    def num(p):
        m = re.findall(p, t)
        return int(m[-1]) if m else 0
    if kind == "pytest":
        line = ([x for x in t.splitlines() if re.search(r"\d+ (passed|failed)", x) and " in " in x] or [""])[-1]
        dur = re.search(r"in ([\d.]+)s", line)
        return {"통과": num(r"(\d+) passed"), "실패": num(r"(\d+) failed") + num(r"(\d+) errors?"), "소요_초": dur.group(1) if dur else ""}
    if kind == "vitest":
        m = re.search(r"Tests\s+(?:(\d+) failed \| )?(\d+) passed", t)
        dur = re.search(r"Duration\s+([\d.]+)(ms|s)", t)
        sec = (float(dur.group(1)) / (1000 if dur.group(2) == "ms" else 1)) if dur else ""
        return {"통과": int(m.group(2)) if m else 0, "실패": int(m.group(1) or 0) if m else 0, "소요_초": round(sec, 1) if sec != "" else ""}
    # e2e (Playwright): "8 passed (9.2m)" / "1 failed"
    dur = re.findall(r"\d+ passed \(([\d.]+)(m|s)\)", t)
    sec = (float(dur[-1][0]) * (60 if dur[-1][1] == "m" else 1)) if dur else ""
    failed = re.findall(r"^\s+\d+\) .+?›.+?› (.+?) ─", t, re.M)
    return {"통과": num(r"(\d+) passed \("), "실패": num(r"(?m)^\s+(\d+) failed"),
            "소요_초": round(sec) if sec != "" else "", "비고": ("실패: " + "; ".join(failed))[:300] if failed else ""}


def record(kind: str, log: str, scope: str = "전체") -> None:
    r = parse(kind, read_log(log))
    env = env_snapshot()
    modes = " ".join(f"{k.split('_')[0]}={env[k]}" for k in ("MODULE_MODE", "STT_MODE", "TTS_MODE", "FACE_MODE") if env.get(k))
    if kind == "e2e":
        modes += " (E2E: 웹 개발 서버, 얼굴 대조 stub)"
    models = ", ".join(env[k] for k in ("LLM_EVAL_MODEL", "LLM_FAST_MODEL", "LLM_LOCAL_FAST_MODEL", "EMBED_MODEL") if env.get(k))
    append("test_runs.csv", RUN_COLS, {"일시": now(), "종류": kind, "범위": scope, "모드": modes, "모델": models, **r})
    print(f"기록: {kind} 통과 {r['통과']} · 실패 {r['실패']} → records/test_runs.csv")


def export() -> None:
    """DB 초기화 전에 직접 응시한 면접을 저장 (없으면 아무것도 안 함). DB가 꺼져 있어도 seed는 계속한다"""
    try:
        p = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "scripts/export_sessions.py"], cwd=ROOT,
                           capture_output=True, timeout=120)
        data = json.loads(p.stdout.decode("utf-8") or "[]")
    except Exception as e:                                       # noqa: BLE001 — 기록 실패로 seed를 멈추지 않는다
        print(f"면접 기록 꺼내기 건너뜀: {type(e).__name__}")
        return
    if not data:
        print("저장할 직접 응시 면접 기록 없음")
        return
    os.makedirs(os.path.join(REC, "interviews"), exist_ok=True)
    path = os.path.join(REC, "interviews", datetime.now(KST).strftime("%Y%m%d-%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"면접 기록 {len(data)}건 저장 → {os.path.relpath(path, ROOT)}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd in ("pytest", "vitest", "e2e"):
        record(cmd, argv[1], argv[2] if len(argv) > 2 else "전체")
    elif cmd == "note":
        append("measurements.csv", MEAS_COLS, {"일시": now(), "종류": argv[1], "항목": argv[2], "값": argv[3],
                                               "비고": argv[4] if len(argv) > 4 else ""})
    elif cmd == "export":
        export()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
