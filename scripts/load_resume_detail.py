"""지원자 50명 이력서를 팀 이력서 양식(v0.3 수정본, 4쪽)으로 다시 만든다. tasks.ps1 seed가 test_data.sql·demo_accounts.sql 다음에 한 번 실행.
재료: test_data.sql 기본 이력서(인적사항·학력·기술·자기소개·시험용 수준) + seed/resume_detail(part·essays·essays_add·template).
이력서(resume.content)와 지원서(application.resume_snapshot)를 새 모양으로 통째로 바꾼다.
"""
import os
import re
import sys

import psycopg
from psycopg.types.json import Jsonb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.site import ESSAY_MAX, ESSAYS, essay_list, summary_fields  # noqa: E402
from seed.resume_detail import essays1, essays2, essays3, essays4, essays5, essays_add, template  # noqa: E402
from seed.resume_detail import part1, part2, part3, part4, part5  # noqa: E402

# 예전 자기소개서 5문항 → 팀 양식 4문항 (협업 경험은 양식에 없어 뺀다)
ESSAY_MAP = {"지원 동기": "지원동기", "직무 역량": "기술수행경험 및 문제해결경험", "입사 후 포부": "입사후포부", "성격의 장단점": "성격의 장/단점"}
FIELD = {"Python": "백엔드 개발", "FastAPI": "백엔드 개발", "Django": "백엔드 개발", "Java": "백엔드 개발", "Spring": "백엔드 개발",
         "Node.js": "백엔드 개발", "Express": "백엔드 개발", "PostgreSQL": "데이터베이스", "MySQL": "데이터베이스", "MongoDB": "데이터베이스",
         "Redis": "비동기·캐시", "Kafka": "비동기·캐시", "Celery": "비동기·캐시", "Docker": "개발환경", "GitHub Actions": "개발환경",
         "React": "프론트엔드·웹 기초", "HTML": "프론트엔드·웹 기초", "JavaScript": "프론트엔드·웹 기초", "C": "C·임베디드"}
HIGH = ["새말고등학교", "푸른솔고등학교", "가온고등학교", "솔내고등학교", "하늘빛고등학교"]   # 가상 고등학교
GPA = {"상": (3.9, 4.25), "중": (3.4, 3.85), "하": (2.9, 3.35)}                          # 수준별 학점 범위 (가상)
AWARD = re.compile(r"(대상|최우수상|우수상|장려상|금상|은상|동상|\d위)")


def all_resumes() -> dict:
    """사람별 재료: part(프로젝트·기술 상세·자격증·교육·대외활동) + 자기소개서 4문항(500자 미만은 essays_add 보충) + template.EXTRA"""
    essays = {}
    for m in (essays1, essays2, essays3, essays4, essays5):
        essays.update(m.ESSAYS)
    out = {}
    for part in (part1, part2, part3, part4, part5):
        for ci, r in part.RESUMES.items():
            add = essays_add.ADD.get(ci, {})
            ess = {ESSAY_MAP[k]: v + (" " + add[k] if k in add else "") for k, v in essays[ci].items() if k in ESSAY_MAP}
            out[ci] = {**r, "자기소개서": ess, **template.EXTRA[ci]}
    return out


def _education(base: dict, n: int) -> list[dict]:
    """학력 문구(예: '한빛대 컴퓨터공학과 졸업(2026)') → 대학·고교 두 줄. 대학 기간은 졸업 연도(재학은 학년·나이)에서, 고교는 대학 입학 직전 3년"""
    m = re.match(r"(\S+)대 (\S+) (졸업|재학)(?:\((\d{4})\)|\((\d)학년\))?(?:, (.+))?", base["학력"])
    school, major, state, grad, year, extra = m[1] + "대학교", m[2], m[3], m[4], m[5], m[6]
    born = int(base["인적사항"]["생년월일"][:4])
    lo, hi = GPA[base["시험용 수준"]]
    gpa = f"{lo + (hi - lo) * ((n * 37) % 10) / 9:.2f}·4.5"
    if extra and "부전공" in extra:
        major += f" ({extra})"
    start = int(grad) - 4 if grad else (2027 - int(year) if year else min(born + 19, 2026))   # 재학: n학년이면 2026년 기준 역산
    uni = {"기간": f"{start}.03 - " + (f"{grad}.02" if grad else "재학 중"), "학교": school, "학과": major, "학점": gpa, "상태": state}
    hs = {"기간": f"{start - 3}.03 - {start}.02", "학교": HIGH[n % len(HIGH)], "학과": "", "학점": "", "상태": "졸업"}
    return [uni, hs]


def _org(name: str) -> str:
    if name.startswith(("교내", "학과")) or name.endswith(("학회", "튜터링")):
        return "소속 대학교"
    if name.startswith("사내"):
        return "재직 회사"
    if "온라인" in name or name.startswith("Python 기초"):
        return "온라인 강의"
    if name.startswith("오픈소스"):
        return "오픈소스 커뮤니티"
    if "국비" in name:
        return "국비 지원 교육기관"
    return name.split()[0] if "부트캠프" in name else ""


def build(ci: str, base: dict, r: dict, n: int) -> dict:
    """팀 양식 이력서 한 명분"""
    level = base["시험용 수준"]
    awards, acts = [], []
    for a in r["교육·대외활동"]:
        hit = AWARD.search(a["내용"])
        if hit:
            awards.append({"수상일": a["기간"], "수상명": f"{a['이름']} {hit[1]}", "수여기관": _org(a["이름"]) or "주최 기관",
                           "내용": "" if a["내용"] == hit[1] else a["내용"]})
        else:
            per = a["기간"].replace("~", " - ")
            acts.append({"기간": per + "진행 중" if per.endswith("- ") else per, "기관": _org(a["이름"]), "과정": a["이름"], "내용": a["내용"]})
    groups: dict[str, list] = {}
    for t in r["기술 상세"]:
        groups.setdefault(FIELD.get(t["기술"], "기타"), []).append(t)
    skills = [{"분야": f, "기술내역": ", ".join(t["기술"] for t in ts), "설명": " ".join(t["설명"] for t in ts)} for f, ts in groups.items()]
    if "데이터베이스" not in groups:
        skills.append({"분야": "데이터베이스", "기술내역": "기재사항 없음", "설명": "관계형 데이터베이스를 연동한 경험은 없습니다."})
    p, car = r["프로젝트"][0], r["경력"]
    inhouse = "(재직)" in p["기간"] or "(인턴)" in p["기간"] or "(계약직)" in p["기간"]
    addr = "사내 프로젝트라 공개 주소 없음" if inhouse else ("외부 공개 자료 없음" if level == "하" else f"https://example.com/projects/{ci[-2:]} (가상 주소)")
    nondev = base["경력"].startswith("비개발")
    lang = base["기술"][0]
    role = "백엔드 개발 직무 전환 지원" if nondev else (f"{lang} 백엔드 개발자 지원" if lang in ("Python", "Java", "Node.js") else "백엔드 개발자 지원")
    snap = {"인적사항": {**base["인적사항"], "Github": None if level == "하" else "https://github.com/example (가상 계정)"},
            "지원직무": role, "소개": [re.split(r"(?<=[.다])\s", base["자기소개"])[0], r["소개2"]],
            "학력사항": _education(base, n), "수상경력": awards,
            "경력사항": [{k: c[k] for k in ("기간", "회사", "직무", "총기간", "요약")} for c in car],
            "보유자격증": [{"취득일": c["취득일"], "자격증명": c["이름"], "발급기관": c["발급기관"]} for c in r["자격증"]],
            "교육활동": acts,
            "경력직무상세": [{"회사": c["회사"], "기간": f"{c['기간']} / 총 {c['총기간']}", "수행직무": c["수행직무"]} for c in car],
            "보유기술": skills,
            "프로젝트소개서": [{"주제": r["주제"], "이름": p["이름"], "주소": addr, "기간": p["기간"].replace("~", " - "), "인원": r["인원"],
                          "동기목표": r["동기"], "개발환경": ", ".join(p["기술"]), "담당역할": p["역할"],
                          "작업과정성과": f"{p['내용']}\n성과: {p['성과']}", "느낀점": r["느낀점"]}],
            "자기소개서": essay_list(r["자기소개서"]), "시험용 수준": level}
    return {**snap, **summary_fields(snap), "기술": base["기술"]}   # 기술 목록은 기본 이력서 그대로 (코딩 언어 확인 등에 씀)


def check(ci: str, snap: dict) -> None:
    """모양 확인: 자기소개서 4문항 순서·분량, 학력·기술·프로젝트 소개서가 있다"""
    assert [e["문항"] for e in snap["자기소개서"]] == [k for k, _ in ESSAYS], ci
    assert all(500 <= len(e["답"]) <= ESSAY_MAX for e in snap["자기소개서"]), (ci, [len(e["답"]) for e in snap["자기소개서"]])
    assert len(snap["학력사항"]) == 2 and snap["보유기술"] and len(snap["프로젝트소개서"]) == 1, ci
    born = int(snap["인적사항"]["생년월일"][:4])
    assert all(int(c["기간"][:4]) >= born + 19 for c in snap["경력사항"]), ci


def main(db_url: str | None = None) -> int:
    data = all_resumes()
    with psycopg.connect(db_url or os.environ["DATABASE_URL"], autocommit=True) as db, db.transaction():
        n = 0
        for i, (ci, r) in enumerate(data.items()):
            row = db.execute("""SELECT r.id, r.content FROM resume r JOIN candidate c ON c.id = r.candidate_id
                                WHERE c.ci_hash = %s ORDER BY r.id LIMIT 1""", (ci,)).fetchone()
            snap = build(ci, row[1], r, i)          # seed는 매번 test_data.sql부터 다시 넣으므로 row는 항상 기본 이력서
            check(ci, snap)
            db.execute("UPDATE resume SET content = %s, updated_at = now() WHERE candidate_id = (SELECT id FROM candidate WHERE ci_hash = %s)",
                       (Jsonb(snap), ci))
            n += db.execute("UPDATE application SET resume_snapshot = %s WHERE candidate_id = (SELECT id FROM candidate WHERE ci_hash = %s)",
                            (Jsonb(snap), ci)).rowcount > 0
    print(f"팀 양식 이력서 {n}명 적재")
    return n


if __name__ == "__main__":
    main()
