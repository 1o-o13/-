"""집단별 점수 차이 점검 (11/12). AI에는 성별·나이를 가려서 보내지만, 말투·목소리·경력 차이로 집단별 결과가 달라질 수 있어 확인한다.
PC(호스트)에서 실행, DB는 읽기만.
  python scripts/fairness_check.py   → records/fairness.csv (집단·단계별 인원·평균·추천 비율) + 화면 출력
비교: 1차 AI 추천 비율(공고 상위 30%), 2차 면접 총점(확정 전 포함, 최신 평가). 4/5 규칙(가장 낮은 집단 비율 ÷ 가장 높은 집단 비율 < 0.8이면 살펴볼 것)을 참고로 표시.
시험 데이터(가상 지원자)라 지금 숫자 자체는 의미가 없고, 실제 지원자 데이터가 쌓이면 같은 방법으로 본다.
"""
import csv
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from human_scoring import ROOT, sql  # noqa: E402


def band(age) -> str:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return "모름"
    return "20대 초반(~25)" if a <= 25 else "20대 후반(26~29)" if a <= 29 else "30대 이상"


def ai_recommended() -> set[int]:
    """화면과 같은 규칙(screen.final_conclusions)으로 공고마다 추천된 지원 건 (api 컨테이너에서 계산)"""
    import json
    import subprocess
    code = ("import json; from api.db import connect; from api import screen\n"
            "with connect() as db:\n"
            "    ps=[r['id'] for r in db.execute('SELECT id FROM job_posting').fetchall()]\n"
            "    print(json.dumps([k for p in ps for k,v in screen.final_conclusions(db,p).items() if v=='추천']))")
    r = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", code], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", check=True)
    return set(json.loads(r.stdout.strip().splitlines()[-1]))


def main() -> int:
    apps = sql("""SELECT a.id, a.resume_snapshot->'인적사항'->>'성별' AS gender, a.resume_snapshot->'인적사항'->>'나이' AS age,
                         EXISTS (SELECT 1 FROM document_evaluation d WHERE d.application_id = a.id AND d.criteria_scores ? '결론') AS screened,
                         (SELECT e.total_score FROM interview_session s JOIN interview_evaluation e ON e.session_id = s.id
                          WHERE s.application_id = a.id ORDER BY s.attempt_no DESC, e.version_no DESC LIMIT 1) AS interview
                  FROM application a""")
    rec = ai_recommended()
    rows = []
    for key, name in (("gender", "성별"), ("age", "나이대")):
        groups: dict[str, list[dict]] = {}
        for a in apps:
            g = (a["gender"] or "모름") if key == "gender" else band(a["age"])
            groups.setdefault(g, []).append(a)
        rates = {}
        for g, xs in sorted(groups.items()):
            scr = [x for x in xs if x["screened"]]
            iv = [float(x["interview"]) for x in xs if x["interview"] is not None]
            rate = sum(x["id"] in rec for x in scr) / len(scr) if scr else None
            if rate is not None:
                rates[g] = rate
            rows.append({"기준": name, "집단": g, "지원자": len(xs), "1차 AI 검토": len(scr),
                         "1차 AI 추천 비율": round(rate, 3) if rate is not None else "",
                         "2차 면접 인원": len(iv), "2차 면접 평균": round(st.mean(iv), 1) if iv else "", "4/5 규칙": ""})
        if len(rates) >= 2 and max(rates.values()) > 0:
            ratio = min(rates.values()) / max(rates.values())
            for r in rows:
                if r["기준"] == name:
                    r["4/5 규칙"] = f"{ratio:.2f} ({'살펴볼 것' if ratio < 0.8 else '통과'})"
    with open(os.path.join(ROOT, "records", "fairness.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
