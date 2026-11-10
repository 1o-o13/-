"""지원 건 상세 단계 11종 (DB TRD 11-08, 활동다이어그램 1109 6쪽). 허용 전이는 DB 트리거(stage_transition)가 지킨다.

  submitted → screen_passed / screen_rejected → coding_waiting(합격 후 단계 끝)
  → scheduled(응시 안내 발송) → coding → interview → final_pass · final_fail.  최종 전에는 어디서든 withdrawn.
  1차 합격 뒤 부정행위로 합격을 거두면 screen_rejected (사유·담당관 필수)

공통 스키마 application.status는 그대로 둔다 (다른 파트 소유). 행이 없는 지원 건은 v_application_stage가 공통 상태에서 읽어 낸 값.
"""
import logging

import psycopg

log = logging.getLogger(__name__)
LABEL = {"submitted": "서류 접수", "screen_passed": "1차 합격", "screen_rejected": "1차 불합격",
         "coding_waiting": "합격 후 단계 끝", "scheduled": "응시 안내 발송", "coding": "코딩 테스트", "interview": "화상 면접",
         "final_pass": "최종 합격", "final_fail": "최종 불합격", "withdrawn": "지원 취소"}


def get(db, app_id: int) -> str:
    return db.execute("SELECT stage FROM v_application_stage WHERE application_id = %s", (app_id,)).fetchone()["stage"]


def ensure(db, app_id: int) -> None:
    """공통 상태를 바꾸기 전에 부른다: 행이 없으면 지금 읽어 낸 단계로 행을 만들어 둔다 (안 그러면 바뀐 공통 상태에서 다시 읽어 냄)"""
    db.execute("""INSERT INTO application_stage(application_id, stage) SELECT application_id, stage FROM v_application_stage
                  WHERE application_id = %s ON CONFLICT (application_id) DO NOTHING""", (app_id,))


def move(db, app_id: int, to: str, actor_type: str = "system", actor_id: int | None = None, reason: str | None = None,
         strict: bool = False) -> bool:
    """단계를 to로. 지금 단계에서 갈 수 없으면(DB 트리거가 거부) strict면 예외, 아니면 기록만 남기고 False.
    이미 to면 아무것도 안 함"""
    cur = get(db, app_id)
    if cur == to:
        return True
    try:
        with db.transaction():
            db.execute("""INSERT INTO application_stage(application_id, stage) VALUES (%s, %s)
                          ON CONFLICT (application_id) DO NOTHING""", (app_id, cur))
            db.execute("UPDATE application_stage SET stage = %s WHERE application_id = %s", (to, app_id))
            db.execute("""INSERT INTO application_stage_log(application_id, from_stage, to_stage, actor_type, actor_id, reason)
                          VALUES (%s, %s, %s, %s, %s, %s)""", (app_id, cur, to, actor_type, actor_id, reason))
        return True
    except psycopg.errors.CheckViolation as e:
        if strict:
            raise
        log.warning("app-%s 단계 %s → %s 거부: %s", app_id, cur, to, str(e).splitlines()[0])
        return False


def path(db, app_id: int, steps: list[str], **kw) -> bool:
    """여러 단계를 차례로 (예: 1차 합격 발표 = screen_passed → coding_waiting → scheduled)"""
    return all(move(db, app_id, s, **kw) for s in steps)
