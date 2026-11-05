"""채점 실행기(judge 컨테이너) 호출과 판정·부분 점수 계산. 기대 출력은 실행기로 보내지 않고 여기서 비교한다."""
import os

import httpx

GROUPS = 5                     # 그룹 = 입력 크기 1~5 (CT-21)


def run(language: str, code: str, inputs: list[str], time_limit_ms: int) -> dict:
    """inputs 순서대로 실행 → {"compile_error": str|None, "results": [{status, stdout, stderr, time_ms}]}"""
    r = httpx.post(f"{os.environ.get('JUDGE_URL', 'http://judge:8090')}/run",
                   json={"language": language, "code": code, "time_limit_ms": time_limit_ms,
                         "cases": [{"id": str(i), "input": x} for i, x in enumerate(inputs)]}, timeout=600)
    r.raise_for_status()
    return r.json()


def same(out: str, expected: str) -> bool:
    """줄 끝 공백·마지막 빈 줄 차이는 같은 답으로 본다"""
    norm = lambda s: [ln.rstrip() for ln in s.rstrip().splitlines()]   # noqa: E731
    return norm(out) == norm(expected)


def verdict(res: dict, expected: str) -> str:
    """AC 맞음 / WA 틀림 / TLE 시간 초과 / RE 실행 오류 / CE 컴파일 오류"""
    if res["status"] != "ok":
        return {"tle": "TLE", "re": "RE", "ce": "CE"}[res["status"]]
    return "AC" if same(res["stdout"], expected) else "WA"


def grade(cases: list[dict], results: list[dict]) -> tuple[list[dict], dict, float]:
    """cases: [{case_no, size, expected}] (예제 제외) → (케이스별 판정, 그룹별 점수, 부분 점수 0~100)
    그룹마다 20점, 그룹 안 맞은 케이스 비율만큼 (임시: 그룹 배점 균등, 팀 미정)"""
    rows = [{"case_no": c["case_no"], "size": c["size"], "verdict": verdict(r, c["expected"]), "time_ms": r["time_ms"]}
            for c, r in zip(cases, results)]
    groups = {}
    for g in range(1, GROUPS + 1):
        mine = [x for x in rows if x["size"] == g]
        groups[str(g)] = round(100 / GROUPS * sum(x["verdict"] == "AC" for x in mine) / len(mine), 2) if mine else 0.0
    return rows, groups, round(sum(groups.values()), 2)
