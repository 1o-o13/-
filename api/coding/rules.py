"""코딩 테스트 규칙 (코드로 계산, LLM·검색 없음: FR-13, CT-10·23·24)."""

TIERS = ["실버1", "골드5", "골드4", "골드3", "골드2"]
START = {"실버1": 0, "골드5": 15, "골드4": 30, "골드3": 45, "골드2": 60}   # 임시: 등급별 시작 점수 (문서에 수치 없음, 골드3 45는 기존 시험 데이터)
SCORE_TABLE = "v0-임시"
Q12_TIER = "골드3"                                      # 1·2번 기본 등급 (문서는 골드4, 팀 결정으로 골드3)

# 문제 유형 → 화상면접 3번 질문이 찾는 회사 문서의 알고리즘 이름 (seed/corpus_alt 약점 알고리즘). 임시 대응표
ALGO = {"BFS": "BFS", "다익스트라": "다익스트라", "슬라이딩 윈도우": "슬라이딩 윈도우", "우선순위 큐": "우선순위 큐", "정렬": "정렬",
        "유니온 파인드": "Union-Find", "위상 정렬": "DP", "이분 탐색": "투 포인터"}


def q3_tier(p1: float, p2: float) -> str:
    """1·2번 부분 점수 평균 5구간: 80 이상 골드2, 60~80 골드3, 40~60 골드4, 20~40 골드5, 20 미만 실버1 (FR-17)"""
    avg = (p1 + p2) / 2
    return "골드2" if avg >= 80 else "골드3" if avg >= 60 else "골드4" if avg >= 40 else "골드5" if avg >= 20 else "실버1"


def converted(tier: str, p3: float) -> float:
    """3번 환산 점수 = 등급별 시작 점수 + 40 × p/100 → 2차 종합의 코딩 점수 (CT-24)"""
    return round(START[tier] + 40 * p3 / 100, 2)


def weakness(attempts: list[dict]) -> dict:
    """1·2·3번 채점 결과로 약점 요약 (CT-11·33). attempts: [{type, partial, case_results}] (가장 좋은 제출)
    임시: LLM 코드 리뷰 전까지 채점 결과만으로 만든다. 약점 태그는 정해진 목록 안에서만"""
    algos, groups, tags = [], set(), set()
    for a in attempts:
        bad = [c for c in a["case_results"] if c["verdict"] != "AC"]
        if a["partial"] < 100:
            algos.append(ALGO.get(a["type"], a["type"]))
        for c in bad:
            groups.add(c["size"])
            if c["verdict"] == "TLE":
                tags.add("시간 복잡도")
            elif c["size"] == 1:
                tags.add("경계값")
            elif c["verdict"] == "RE":
                tags.add("예외 처리")
            else:
                tags.add("구현 정확성")
    if not algos:                                      # 다 맞았으면 가장 어려웠던(점수가 낮은) 유형을 3번 질문 주제로
        algos = [ALGO.get(min(attempts, key=lambda a: a["partial"])["type"], "")]
    return {"algorithms": list(dict.fromkeys(algos)), "failed_groups": sorted(groups), "weakness_tags": sorted(tags)}


def review(attempt: dict) -> dict:
    """코드 리뷰 (coding_review). 임시: 채점 결과로 만든 규칙 리뷰. LLM 리뷰(가독성·복잡도·경계 처리·관용법)는 실제 모듈 단계"""
    bad = [c for c in attempt["case_results"] if c["verdict"] != "AC"]
    lvl = "상" if attempt["partial"] >= 80 else "중" if attempt["partial"] >= 50 else "하"
    return {"rubric": {"정확성": f"{len(attempt['case_results']) - len(bad)}/{len(attempt['case_results'])} 케이스 통과",
                       "복잡도": "큰 입력에서 시간 초과" if any(c["verdict"] == "TLE" for c in bad) else "큰 입력 통과",
                       "경계 처리": "작은 입력(그룹 1)에서 틀림" if any(c["size"] == 1 for c in bad) else "작은 입력 통과"},
            "summary": weakness([attempt]), "quality_level": lvl}
