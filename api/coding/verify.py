"""문제 검증·저장 (CT-02~09). 문제 모음 적재(scripts/load_coding.py)와 3번 즉석 출제(api/coding/q3.py)가 같이 쓴다.

문제마다:
  예제 + 그룹(입력 크기 1~5)마다 10개 = 50개 채점 케이스를 생성기로 만들고 (임시: 문서 1000개보다 작게)
  ① 모든 입력이 검사기 통과  ② 정답 Python으로 기대 출력, 예제 정답과 일치  ③ 정답 Java 출력 일치
  ④ 완전탐색이 있으면 크기 1~2에서 일치  ⑤ 오답 코드마다 최소 한 케이스에서 틀림(걸린 케이스 기록)
  ⑥ 제한 시간 = 언어별 정답 최대 실행 시간 × 3 (최소 1초, 임시 배수)
하나라도 어기면 저장하지 않는다 (검증 통과 문제만 풀에 들어감, CT-09).
생성기·검사기도 judge 컨테이너에서 돌린다 (3번은 LLM이 쓴 코드라 api·worker 안에서 실행하지 않는다).
"""
import random

from psycopg.types.json import Jsonb

from api.coding import judge

PER_GROUP = 10        # 임시: 그룹마다 10개 (문서 CT-21 1000개·표본 100개보다 작게, 적재 시간 때문)
TIME_FACTOR = 3
GEN_RUN = "\nimport random, sys\n_s, _d = map(int, sys.stdin.read().split())\nsys.stdout.write(gen(_s, random.Random(_d)))\n"
GEN_MAX_BYTES = 900_000      # judge 출력 한도 1MB보다 작게 (넘으면 잘려 검사기에서 틀림)
CHECK_RUN = "\nimport sys\nprint('OK' if check(sys.stdin.read()) else 'BAD')\n"


def build(p: dict) -> tuple[list[dict], dict, list[str]]:
    """→ (케이스 목록, 제한 시간, 문제점 목록)"""
    rnd = random.Random(p["key"])
    jobs = [(g, rnd.randint(1, 10**9)) for g in range(1, 6) for _ in range(PER_GROUP)]
    made = judge.run("python", p["generator"] + GEN_RUN, [f"{g} {d}" for g, d in jobs], 20_000)["results"]
    bad_gen = [n for n, r in enumerate(made) if r["status"] != "ok" or not r["stdout"].strip()]
    if bad_gen:
        return [], {}, [f"생성기 실패 {len(bad_gen)}건: {made[bad_gen[0]]['status']} {made[bad_gen[0]]['stderr'][-200:]}"]
    big = sorted({jobs[n][0] for n, r in enumerate(made) if len(r["stdout"].encode()) >= GEN_MAX_BYTES})
    if big:
        return [], {}, [f"생성기 입력이 너무 큼 (그룹 {big}, 케이스 하나 {GEN_MAX_BYTES // 1000}KB 미만이어야 함)"]
    cases = [{"size": 1, "input": i, "sample": True, "want": o} for i, o in p["examples"]]
    cases += [{"size": g, "input": r["stdout"], "sample": False} for (g, _), r in zip(jobs, made)]
    inputs = [c["input"] for c in cases]
    checked = judge.run("python", p["validator"] + CHECK_RUN, inputs, 20_000)["results"]
    problems = [f"검사기 불통과 케이스 {n} (그룹 {cases[n]['size']}, {r['status']}{' ' + r['stderr'][-150:] if r['stderr'] else ''})"
                for n, r in enumerate(checked) if r["stdout"].strip() != "OK"]
    py = judge.run("python", p["solution_python"], inputs, 20_000)["results"]
    for n, (c, r) in enumerate(zip(cases, py)):
        if r["status"] != "ok":
            problems.append(f"정답 Python 실행 실패 케이스 {n}: {r['status']} {r['stderr'][-200:]}")
        c["expected"] = r["stdout"]
        if c["sample"] and not judge.same(r["stdout"], c["want"]):
            problems.append(f"예제 {n} 정답 불일치: {r['stdout']!r} != {c['want']!r}")
    jv = judge.run("java", p["solution_java"], inputs, 20_000)
    if jv["compile_error"]:
        problems.append("정답 Java 컴파일 오류: " + jv["compile_error"][:300])
    else:
        problems += [f"정답 Java 불일치 케이스 {n}" for n, (c, r) in enumerate(zip(cases, jv["results"]))
                     if judge.verdict(r, c["expected"]) != "AC"]
    if p.get("brute_force"):
        small = [n for n, c in enumerate(cases) if c["size"] <= 2]
        bf = judge.run("python", p["brute_force"], [cases[n]["input"] for n in small], 20_000)["results"]
        problems += [f"완전탐색 불일치 케이스 {n}" for n, r in zip(small, bf) if judge.verdict(r, cases[n]["expected"]) != "AC"]
    limits = {"python": max(1000, TIME_FACTOR * max(r["time_ms"] for r in py)),
              "java": max(1000, TIME_FACTOR * max((r["time_ms"] for r in jv["results"]), default=0))}
    for c in cases:
        c["kills"] = []
    graded = [n for n, c in enumerate(cases) if not c["sample"]]
    for w, wrong in enumerate(p["wrong_codes"]):
        res = judge.run("python", wrong["code"], [cases[n]["input"] for n in graded], limits["python"])["results"]
        killed = [n for n, r in zip(graded, res) if judge.verdict(r, cases[n]["expected"]) != "AC"]
        if not killed:
            problems.append(f"오답 {w} ({wrong['note']})이 모든 케이스를 통과함")
        for n in killed:
            cases[n]["kills"].append(w)
    return cases, limits, problems


def save(db, p: dict, cases: list[dict], limits: dict, origin: str, prompt_version: str) -> int:
    """검증을 통과한 문제와 케이스를 저장 → coding_problem.id"""
    with db.transaction():
        pid = db.execute("""INSERT INTO coding_problem(slot, tier, type, mode, origin, statement, solution_python, solution_java,
                                brute_force, wrong_codes, generator, validator, seed, time_limits, prompt_version, validated_at)
                            VALUES (%s, %s, %s, 'stdio', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING id""",
                         (p["slot"], p["tier"], p["type"], origin, f"# {p['title']}\n\n{p['statement']}", p["solution_python"],
                          p["solution_java"], p.get("brute_force"),
                          Jsonb([{"kind": w["kind"], "note": w["note"], "code": w["code"]} for w in p["wrong_codes"]]),
                          p["generator"], p["validator"], random.Random(p["key"]).randint(1, 10**9), Jsonb(limits),
                          prompt_version)).fetchone()
        pid = pid["id"] if isinstance(pid, dict) else pid[0]
        db.cursor().executemany("""INSERT INTO coding_case(problem_id, case_no, size, input, expected, is_sample, kills)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                                [(pid, n, c["size"], c["input"], c["expected"], c["sample"], Jsonb(c["kills"]))
                                 for n, c in enumerate(cases)])
    return pid
