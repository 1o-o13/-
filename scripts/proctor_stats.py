"""감독 경고 오탐 비율 (11/12). 면접 의심 건을 담당관이 어떻게 결정했는지로 잰다: '정상'(normal)으로 끝난 건 = 오탐.
안경·조명·노트북 각도 때문에 얼굴 없음·시선 이탈이 잘못 뜨는지 보고 기준값(lib/face.ts GAZE_OUT·TURN_OUT 등)을 고칠 근거로 쓴다.
PC(호스트)에서 실행, DB는 읽기만.  python scripts/proctor_stats.py → records/proctor_stats.csv
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from human_scoring import ROOT, sql  # noqa: E402

NAME = {"tab_leave": "탭 이탈", "face_missing": "얼굴 없음", "multi_face": "여러 명", "gaze_away": "시선 이탈",
        "identity_unclear": "본인 확인 애매(라이브니스 실패 포함)", "identity_mismatch": "본인 불일치"}


def main() -> int:
    rows = sql("""SELECT reason, count(*) AS total, count(*) FILTER (WHERE decision = 'normal') AS normal,
                         count(*) FILTER (WHERE decision = 'warning') AS warning, count(*) FILTER (WHERE decision = 'disqualified') AS disq,
                         count(*) FILTER (WHERE status <> 'decided') AS open
                  FROM suspicion_case WHERE stage = 'interview' GROUP BY reason ORDER BY reason""")
    out = []
    for r in rows:
        decided = r["total"] - r["open"]
        out.append({"감독 항목": NAME.get(r["reason"], r["reason"]), "의심 건": r["total"], "결정됨": decided, "정상(오탐)": r["normal"],
                    "경고": r["warning"], "부정": r["disq"], "미결": r["open"],
                    "오탐 비율": round(r["normal"] / decided, 3) if decided else ""})
    with open(os.path.join(ROOT, "records", "proctor_stats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["감독 항목"])
        w.writeheader()
        w.writerows(out)
    for x in out:
        print(x)
    if not out:
        print("면접 의심 건이 아직 없습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
