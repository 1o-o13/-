"""시연용: 김하늘(지원 1번)을 '면접을 잘 본 합격자'로 만든다 (11/16). E2E 뒤에 실행한다 (E2E는 가짜 마이크라 3~10번 답변이 비어 과락·불합격으로 끝남).
  docker compose exec -T api python scripts/demo_strong_candidate.py [지원 번호=1]

하는 일 (점수를 손으로 넣지 않고 실제 모듈로 다시 매긴다):
1. 그 응시의 10문항 답변을 아래 '잘한 답변'으로 바꾼다 (말한 시간·침묵 비율도 보통 응시처럼)
2. 실제 판정 모델로 문항마다 다시 판정 (이전 판정은 is_current = false로 남김)
3. 최종 평가(5검사)를 다시 만들고 hr01이 확정 → 2차 종합 점수·순위
4. 최종 결과를 합격으로 (stage_result·지원서 상태·상세 단계)
※ 질문 순서는 그대로라 '점수 70 이상이면 꼬리질문' 흐름은 다시 타지 않는다. 시연·포트폴리오 화면용 데이터이며 실제 응시가 아님
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api import modules as M  # noqa: E402
from api import stage  # noqa: E402
from api.admin.routes import rank_stage2  # noqa: E402
from api.db import connect  # noqa: E402
from api.graph import interview as G  # noqa: E402
from api.interview import store  # noqa: E402

ANSWERS = {
    1: "새봄물류 인턴 때 배달 경로 추천 API에서 제가 직접 맡은 건 후보 경로 조회 부분이었습니다. 원래는 요청마다 기사 위치와 배송지를 다시 계산했는데, "
       "자주 쓰는 구역 간 거리를 Redis에 캐시하고 PostgreSQL에 구역 좌표 인덱스를 추가했습니다. 그 결과 평균 응답이 1.2초에서 0.5초로 줄었습니다. "
       "경로 점수를 매기는 알고리즘 자체는 선배 개발자가 만들었고, 저는 조회와 캐시, 그리고 응답 시간 측정 대시보드를 만든 것까지가 제 몫이었습니다.",
    2: "적지 않은 장점은 기준을 정하면 끝까지 지키는 점입니다. 인턴 때 마감 전날 배포를 앞두고 부하 시험에서 오류율이 기준 1%를 조금 넘었습니다. "
       "팀에서는 일단 배포하자는 의견도 있었지만, 제가 측정 결과를 정리해서 원인이 커넥션 풀 크기라는 걸 보여 드리고 하루 미루자고 말씀드렸습니다. "
       "풀 크기를 고친 뒤 오류율이 0.2%로 내려가서 배포했고, 이후 장애 없이 운영됐습니다. 숫자로 근거를 보여 주면 일정 압박 속에서도 원칙을 지킬 수 있다는 걸 배웠습니다.",
    3: "시나리오를 노드와 선택지 간선으로 된 방향 그래프로 보고, 시작 노드에서 BFS를 한 번 돌리겠습니다. 큐에 넣을 때 깊이를 같이 저장하고, 방문 여부는 해시 집합으로 관리해서 "
       "같은 노드를 두 번 보지 않게 합니다. BFS가 끝나면 거리가 5보다 큰 답변 노드가 '너무 먼 노드'이고, 전체 노드 집합에서 방문 집합을 뺀 나머지가 어디서도 닿지 않는 고아 노드입니다. "
       "중복을 줄이려고 그래프 만들기, BFS 거리 계산, 두 가지 판별을 각각 함수로 나누고, 판별 함수는 거리 사전만 받게 해서 다른 검사에도 다시 쓸 수 있게 하겠습니다.",
    4: "먼저 어디가 느린지 측정하겠습니다. APM이나 로그로 쿼리 시간, 직렬화 시간, 전송 시간을 나눠 보면 보통 한 번에 수백만 행을 메모리에 올리는 게 병목입니다. "
       "그래서 요청 방식을 바꿔서, 다운로드 요청을 받으면 작업을 큐에 넣고 바로 작업 번호를 돌려주는 비동기 방식으로 하겠습니다. 워커는 주문 일자와 id 기준 키셋 페이지네이션으로 "
       "만 행씩 나눠 읽어 CSV로 스트리밍해 저장소에 올리고, 끝나면 내려받기 링크를 알림으로 보냅니다. 중간에 실패하면 마지막으로 처리한 키부터 재시도하고, 같은 요청이 두 번 와도 작업 번호로 중복을 막겠습니다.",
    5: "검색어는 먼저 정규화하겠습니다. 공백과 특수문자를 정리하고 소문자로 바꾸고, 형태소 분석기로 조사를 떼서 OpenSearch에는 multi_match 질의로 상품명과 태그에 가중치를 다르게 줍니다. "
       "품절 상품은 결과를 받은 뒤 거르면 20개가 안 채워질 수 있어서, 재고 상태를 색인에 넣고 filter 절로 질의 단계에서 거르겠습니다. 재고가 자주 바뀌면 재고 변경 이벤트로 색인을 갱신합니다. "
       "트래픽이 몰릴 때는 인기 검색어 결과를 Redis에 짧게 캐시하고, FastAPI는 비동기 클라이언트로 OpenSearch를 부르고 타임아웃을 두고, 응답 시간 p95를 보면서 노드를 늘리겠습니다.",
    6: "카드사 호출에는 평소 응답 300ms를 기준으로 1초 정도의 짧은 타임아웃을 두겠습니다. asyncio로 부르되 장애 때 요청이 계속 쌓이지 않게 서킷 브레이커를 두어서, 실패율이 기준을 넘으면 "
       "일정 시간 바로 실패를 돌려주고 다른 기능으로 장애가 번지지 않게 합니다. 중요한 건 타임아웃이 났다고 결제가 실패한 게 아니라는 점이라, 이 경우 결제 상태를 '확인 중'으로 저장하고 "
       "카드사 조회 API로 나중에 실제 승인 여부를 맞춥니다. 재시도는 멱등 키를 붙여서 이중 결제를 막고, 카드사별 응답 시간과 타임아웃 비율을 대시보드와 알림으로 측정하겠습니다.",
    7: "먼저 지난 문의 데이터로 시간대·요일별 문의량을 예측하고, 배송 지연이나 결제 장애 같은 사건은 별도 변수로 넣어 평소 예측에 곱하는 방식으로 보정하겠습니다. "
       "배치는 동아리에서 푼 DP처럼, 시간대를 순서대로 보면서 교대 규칙, 예를 들어 최소 4시간 근무와 휴식 시간을 상태로 두고 필요한 인원을 채우는 최소 비용 배치를 구하겠습니다. "
       "예측이 어긋날 때를 대비해 대기열 길이가 기준을 넘으면 대기 상담원을 호출하는 규칙을 두고, 매주 예측 오차와 평균 대기 시간을 측정해서 모델과 여유 인원을 조정하겠습니다.",
    8: "먼저 40초가 어디서 나는지 쿼리 시간, 전송량, 화면 그리기 시간을 나눠 재겠습니다. 센서 300개를 1초 단위로 1주면 점이 수억 개라, 대부분 원본을 다 읽고 다 보내는 게 문제일 겁니다. "
       "그래서 1분, 1시간 단위 평균·최대·최소를 미리 집계한 테이블을 기간별로 두고, 조회 기간에 맞는 단위를 고르겠습니다. 화면 폭보다 많은 점은 의미가 없으니 센서당 전송 점 개수를 "
       "1000개 정도로 제한하고, 이상치가 사라지지 않게 최대·최소를 함께 보냅니다. 바꾼 뒤에는 같은 조건으로 응답 시간을 다시 측정해 목표 2초 안에 들어오는지 검증하겠습니다.",
    9: "같은 이벤트가 두 번 와도 결과가 한 번만 반영되게 멱등성을 보장하겠습니다. 이벤트마다 주문 서비스가 만든 고유 이벤트 id를 붙이고, 처리 전에 Redis에 SET NX로 이 id를 기록해서 "
       "이미 있으면 건너뜁니다. 키에는 재전송이 일어날 수 있는 기간보다 넉넉하게 예를 들어 하루 만료 시간을 두어 메모리가 계속 늘지 않게 합니다. 다만 Redis 기록 뒤 처리 중에 죽으면 "
       "이벤트를 잃을 수 있어서, 처리 완료 표시는 DB 트랜잭션 안에서 처리 결과와 함께 남기고, 주문 테이블에도 이벤트 id 유니크 제약을 걸어 오판이나 Redis 장애 때도 중복이 막히게 하겠습니다.",
    10: "먼저 오분류를 측정할 기준이 필요해서, 지난 상담 일부를 사람이 쉬움·어려움으로 표시한 평가 세트를 만들겠습니다. 라우터는 문의 길이, 주문·결제 같은 키워드, 이전 상담 이력과 "
        "작은 모델의 확신도를 보고 판단하는데, 확신도가 기준보다 낮으면 큰 모델로 보냅니다. 작은 모델로 잘못 보낸 건은 답변 품질 검사나 고객의 재문의를 신호로 잡아서 큰 모델로 다시 처리하고, "
        "그 사례를 평가 세트에 넣어 기준을 조정합니다. 매주 건당 비용과 오분류율, 고객 만족도를 함께 보면서 비용과 품질의 균형점을 정하겠습니다.",
}


def main(app_id: int) -> None:
    with connect() as db:
        sid = db.execute("SELECT id FROM interview_session WHERE application_id = %s ORDER BY attempt_no DESC LIMIT 1", (app_id,)).fetchone()["id"]
        rows = db.execute("""SELECT a.id AS answer_id, q.* FROM interview_answer a JOIN interview_question q ON q.id = a.question_id
                             WHERE q.session_id = %s ORDER BY q.ask_order""", (sid,)).fetchall()
        ctx = store.context(db, sid)
    for r in rows if "--skip-judge" not in sys.argv else []:     # 이미 다시 판정했으면 건너뜀
        text = ANSWERS[r["ask_order"]]
        with connect() as db:
            db.execute("""UPDATE interview_answer SET stt_text = %s, stt_original = %s, no_response = false, answer_sec = %s,
                              silence_ratio = 0.08, finished_in_time = true, stt_edit_ratio = 0 WHERE id = %s""",
                       (text, text, 70 + r["ask_order"] * 4, r["answer_id"]))
        j = M.judge_answer(store.to_question(r), text, ctx)
        with connect() as db, db.transaction():
            db.execute("UPDATE answer_judgement SET is_current = false WHERE answer_id = %s AND is_current", (r["answer_id"],))
            store.save_judgement(db, r["answer_id"], j)
        print(f"{r['ask_order']:>2}번 {r['kind']:<8} {j.status} 점수 {j.score}", flush=True)
    with connect() as db, db.transaction():
        db.execute("DELETE FROM evaluation_check WHERE evaluation_id IN (SELECT id FROM interview_evaluation WHERE session_id = %s)", (sid,))
        db.execute("DELETE FROM ai_error_alert WHERE interview_evaluation_id IN (SELECT id FROM interview_evaluation WHERE session_id = %s)", (sid,))
        db.execute("DELETE FROM interview_evaluation WHERE session_id = %s", (sid,))
    G.report({"session_id": sid, "application_id": app_id})
    with connect() as db, db.transaction():
        ev = db.execute("""SELECT id, total_score, status FROM interview_evaluation WHERE session_id = %s AND status = 'passed'
                           ORDER BY version_no DESC LIMIT 1""", (sid,)).fetchone()
        if ev is None:
            raise SystemExit("최종 평가가 5검사를 통과하지 못했습니다 — 관리자 화면에서 확인")
        hr = db.execute("SELECT id FROM admin_user WHERE login_id = 'hr01'").fetchone()["id"]
        db.execute("UPDATE interview_evaluation SET confirmed_by = %s, confirmed_at = now() WHERE id = %s", (hr, ev["id"]))
        db.execute("""INSERT INTO stage2_score(application_id, interview_score, coding_score)
                      SELECT s.application_id, %s, cr.q3_converted FROM interview_session s
                      LEFT JOIN coding_result cr ON cr.session_id = s.coding_session_id WHERE s.id = %s
                      ON CONFLICT (application_id) DO UPDATE SET interview_score = EXCLUDED.interview_score,
                          coding_score = EXCLUDED.coding_score, computed_at = now()""", (ev["total_score"], sid))
        pid = db.execute("SELECT posting_id FROM application WHERE id = %s", (app_id,)).fetchone()["posting_id"]
        rank_stage2(db, pid)
        db.execute("""INSERT INTO stage_result(application_id, stage, result, decided_by) VALUES (%s, 'final', 'pass', %s)
                      ON CONFLICT (application_id, stage) DO UPDATE SET result = 'pass', decided_by = EXCLUDED.decided_by, decided_at = now()""",
                   (app_id, hr))
        db.execute("UPDATE application SET status = 'final_passed' WHERE id = %s", (app_id,))
        why = "시연 데이터: 면접 답변 보강 후 다시 판정 (scripts/demo_strong_candidate.py)"
        stage.path(db, app_id, ["interview", "final_pass"], actor_type="admin", actor_id=hr, reason=why, strict=True)   # 결정 취소와 같은 길
        s = db.execute("SELECT interview_score, coding_score, total_score, fail_cut, ai_rank, ai_recommendation FROM stage2_score WHERE application_id = %s",
                       (app_id,)).fetchone()
    print("최종 평가", ev["total_score"], "| 2차 종합", dict(s), "| 최종 합격")


if __name__ == "__main__":
    nums = [a for a in sys.argv[1:] if a.isdigit()]
    main(int(nums[0]) if nums else 1)
