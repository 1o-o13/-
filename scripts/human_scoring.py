"""사람 채점과 AI 판정 비교 (11/12). PC(호스트)에서 실행 — DB는 docker compose exec로 읽기만.
  python scripts/human_scoring.py export [개수=30]   (judge_consistency.py를 먼저 돌리면 그 답변들로)   → 바탕화면 사람채점지.xlsx (블라인드: 이름·AI 점수 없음)
  python scripts/human_scoring.py compare 파일.xlsx [파일2.xlsx ...]  → 채점자별·평균 vs AI 상관·평균 차 → records/measurements.csv
팀원 여러 명이 같은 파일을 복사해 채점하면 사람끼리의 일치도도 같이 낸다. 채점 기준은 AI와 같은 루브릭(정확성 30·회사 적용 30·깊이 25·구체성 15)
"""
import csv
import datetime as dt
import json
import os
import statistics as st
import subprocess
import sys

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(os.path.expanduser("~"), "Desktop", "사람채점지.xlsx")
RUBRIC = [("정확성", 30), ("회사 적용", 30), ("깊이", 25), ("구체성", 15)]


def sql(q: str) -> list[dict]:
    r = subprocess.run(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "recruit", "-d", "recruit", "-At", "-c",
                        f"SELECT coalesce(json_agg(t), '[]') FROM ({q}) t"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(r.stdout.strip() or "[]")


def ai_scores() -> dict[str, float]:
    """비교할 AI 점수: 실제 판정 모델 점수. records/judge_consistency.csv(외부 모델 반복 평균)가 있으면 그것,
    없으면 DB의 현재 판정 중 가짜 모듈(stub)이 아닌 것 (시험 데이터의 stub 점수는 0·85뿐이라 비교 의미 없음)"""
    p = os.path.join(ROOT, "records", "judge_consistency.csv")
    if os.path.exists(p):
        acc: dict[str, list[float]] = {}
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r["side"] == "외부" and r["score"] not in ("", "None"):
                acc.setdefault(str(r["answer_id"]), []).append(float(r["score"]))
        return {k: st.mean(v) for k, v in acc.items()}
    return {str(r["answer_id"]): float(r["score"]) for r in sql("""SELECT answer_id, score FROM answer_judgement
                                                             WHERE is_current AND score IS NOT NULL AND model <> 'stub'""")}


def export(n: int) -> None:
    fixed = os.path.join(ROOT, "bench", "answers.json")
    if os.path.exists(fixed):                        # 판정 시험과 같은 고정 답변 세트 (수준 표시는 빼고 섞어서)
        import random
        items = json.load(open(fixed, encoding="utf-8"))[:n]
        kp = {r["id"]: r["key_points"] for r in sql(f"""SELECT id, key_points FROM interview_question
                                                       WHERE id IN ({','.join(str(x['question_id']) for x in items) or 0})""")}
        rows = [{"id": x["key"], "question_text": x["question"], "key_points": kp.get(x["question_id"]), "stt_text": x["text"]} for x in items]
        random.Random(12).shuffle(rows)
    else:
        ids = sorted(ai_scores())[:n] or ["0"]
        rows = sql(f"""SELECT a.id, q.question_text, q.key_points, a.stt_text FROM interview_answer a
                       JOIN interview_question q ON q.id = a.question_id
                       WHERE a.id IN ({','.join(ids)}) ORDER BY md5(a.id::text)""")   # 섞어서 (지원자 순서가 드러나지 않게)
    wb = Workbook()
    ws = wb.active
    ws.title = "채점"
    head = ["번호(바꾸지 마세요)", "질문", "핵심어", "답변(STT)"] + [f"{k} (0~{m})" for k, m in RUBRIC] + ["합계", "메모"]
    ws.append(head)
    for i, r in enumerate(rows, 2):
        ws.append([r["id"], r["question_text"], ", ".join(r["key_points"] or []), r["stt_text"], None, None, None, None, f"=SUM(E{i}:H{i})", None])
    for c, w in zip("ABCDEFGHIJ", (10, 40, 22, 70, 10, 10, 10, 10, 8, 24)):
        ws.column_dimensions[c].width = w
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for cell in row[4:8]:
            cell.fill = PatternFill("solid", fgColor="FFF6D5")       # 채울 칸
    for col, (_, m) in zip("EFGH", RUBRIC):
        dv = DataValidation(type="whole", operator="between", formula1="0", formula2=str(m), showErrorMessage=True, error=f"0~{m} 사이 정수")
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{len(rows) + 1}")
    ws.freeze_panes = "E2"
    g = wb.create_sheet("채점 기준")
    for line in ["노란 칸(정확성·회사 적용·깊이·구체성)만 채우세요. 합계는 자동입니다. AI 점수와 지원자 이름은 일부러 뺐습니다(블라인드).",
                 "정확성 30: 기술 내용이 맞는가 · 회사 적용 30: 새벽소프트 상황(근거 문서·프로젝트)에 맞게 적용했는가",
                 "깊이 25: 이유·대안·한계까지 설명하는가 · 구체성 15: 수치·사례·직접 해 본 경험이 있는가",
                 "AI와 같은 기준입니다. 여러 명이 각자 파일을 복사해 채점하면 사람끼리 얼마나 일치하는지도 함께 계산합니다."]:
        g.append([line])
    g.column_dimensions["A"].width = 120
    wb.save(OUT)
    print(f"저장: {OUT} ({len(rows)}문항)")


def read(path: str) -> dict[str, float]:
    ws = load_workbook(path, data_only=False)["채점"]
    out = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is not None and all(isinstance(v, (int, float)) for v in r[4:8]):
            out[str(r[0])] = float(sum(r[4:8]))
    return out


def compare(paths: list[str]) -> None:
    people = {os.path.basename(p): read(p) for p in paths}
    ids = sorted(set().union(*[set(v) for v in people.values()]))
    ai = ai_scores()
    res = []

    def corr(x, y):
        try:
            return round(st.correlation(x, y), 2)
        except st.StatisticsError:                   # 한쪽 점수가 모두 같으면 상관을 낼 수 없다
            return "계산 불가(점수가 모두 같음)"
    for name, sc in people.items():
        both = [(sc[i], ai[i]) for i in sc if i in ai]
        if len(both) >= 3:
            h, a = zip(*both)
            res.append((f"사람({name})·AI 점수 상관", corr(h, a), f"{len(both)}문항"))
            res.append((f"사람({name})·AI 평균 점수 차", round(st.mean(abs(x - y) for x, y in both), 1), "100점 만점, 절댓값"))
    if len(people) >= 2:
        avg = {i: st.mean(v[i] for v in people.values() if i in v) for i in ids if sum(i in v for v in people.values()) >= 2}
        names = list(people)
        pair = [(people[names[0]][i], people[names[1]][i]) for i in ids if i in people[names[0]] and i in people[names[1]]]
        if len(pair) >= 3:
            res.append(("사람끼리 점수 상관", corr(*zip(*pair)), f"{names[0]} · {names[1]}"))
        both = [(avg[i], ai[i]) for i in avg if i in ai]
        if len(both) >= 3:
            res.append(("사람 평균·AI 점수 상관", corr(*zip(*both)), f"{len(people)}명 평균, {len(both)}문항"))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(os.path.join(ROOT, "records", "measurements.csv"), "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for item, v, note in res:
            w.writerow([now, "사람 채점 비교", item, v, note])
    for x in res:
        print(x)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "export":
        export(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    elif len(sys.argv) >= 3 and sys.argv[1] == "compare":
        compare(sys.argv[2:])
    else:
        print(__doc__)
