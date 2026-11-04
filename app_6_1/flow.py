"""면접 진행 규칙 (영찬 RAG TRD v0.6 6.2). 답변 점수를 보고 다음에 무엇을 물을지 정한다.

- 1·2번 비기술(본인 확인·결핍 가치) → 의견만 남기고 다음 질문
- 무응답·STT 실패·시간 초과·평가 실패 → 다음 주제
- 70점 이상, 답변 관련성(CE) ≥ 0.4, 깊이 < 2 → 꼬리질문. 꼬리 체인은 면접 전체에서 최대 2개 주제 (면접 TRD FR-74·81)
- 70점 이상인데 관련성 < 0.4 → 재질문 (같은 깊이, 범위를 좁혀). 이미 재질문한 주제면 다음 주제
- 본 질문 40점 미만, 이 주제에서 재질문 안 함 → 재질문 1회 (같은 근거로 형식만 바꿈)
- 그 밖(40~70, 꼬리 70 미만, 재질문 70 미만) → 다음 주제 본 질문. 재질문 뒤 70 미만은 관리자 화면에 '모름'으로 표시
- 물어본 수가 total_questions(기본 10, 재질문·꼬리 포함)에 닿으면 종료
"""


def next_action(kind: str, depth: int, score: float | None, status: str, topic_retried: bool, asked_count: int,
                total_questions: int = 10, follow_score: int = 70, retry_score: int = 40,
                followup_max_depth: int = 2, *, question_type: str = "main", relevance: float | None = None,
                chains_used: int = 0, max_chains: int = 2, relevance_min: float = 0.4) -> str:
    """반환: 'end' | 'followup' | 'retry' | 'next_topic'
    question_type: 지금 문항 종류(main·followup·reask). relevance: CE(질문, 답변) 관련성, None = 측정 안 함(점수만으로 분기).
    chains_used: 이 면접에서 꼬리질문까지 간 주제 수 (지금 주제 포함). 새 꼬리 체인은 이 값이 max_chains 미만일 때만 시작"""
    if asked_count >= total_questions:
        return "end"
    if kind == "non_tech" or status != "ok" or score is None:
        return "next_topic"
    if score >= follow_score:
        relevant = relevance is None or relevance >= relevance_min
        if relevant and depth < followup_max_depth and (depth >= 1 or chains_used < max_chains):
            return "followup"
        if not relevant and not topic_retried:
            return "retry"                     # 높은 점수라도 질문과 무관한 답 → 같은 깊이에서 범위를 좁혀 다시 (FR-81)
        return "next_topic"
    if question_type == "main" and score < retry_score and not topic_retried:
        return "retry"                         # 재질문은 본 질문에서만 (꼬리 70 미만·재질문 70 미만 → 다른 주제)
    return "next_topic"


def topic_score(depth_reached: int, scores: list[float]) -> float:
    """주제 점수 T = S_d + 40 × 평균/100 (S0 0, S1 30, S2 60). 메인 TRD 3.9 제안값"""
    return round((0, 30, 60)[depth_reached] + 40 * (sum(scores) / len(scores)) / 100, 2)
