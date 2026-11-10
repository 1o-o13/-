"""데모: 1차 합격자 중 로그인되지 않는 8명이 2차(AI 화상면접)를 이미 마친 상태로 만든다. tasks.ps1 seed가 상세 이력서 다음에 실행.

실제 API 흐름 그대로(안내 → 점검·동의 → 본인 확인 → 질문 준비 → 시작 → 답변 10문항+ → 최종 평가)를 앱 안에서 돌리고,
채용 담당자(hr01)가 결과를 확정해 2차 종합 점수·순위·AI 추천까지 만든다. 코딩 결과는 시드(test_data.sql) 그대로 쓴다.
음성은 가짜(STT_MODE=stub: 지원자 시험용 수준에 따라 답이 달라 점수가 다양하게 나옴), worker는 요청 안에서 바로 실행한다.
로그인되는 데모 계정(김하늘·오세훈·이준서)은 직접 응시해 보도록 건드리지 않는다.
"""
import os
import random
import sys
import time

os.environ["STT_MODE"] = os.environ["TTS_MODE"] = "stub"          # 데모 데이터는 음성 컨테이너 없이 만든다
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import jwt  # noqa: E402
import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

DEMO = ("haneul.kim@naver.com", "sehun.oh@gmail.com", "junseo.lee@gmail.com")
OK_CHECK = {"chrome": True, "camera": True, "mic": True, "upload_mbps": 20, "single_face": True,
            "consent_voice": True, "consent_face": True, "consent_ai": True, "consent_overseas": True}


def cookie(typ: str, sub: int, role: str | None = None) -> dict:
    tok = jwt.encode({"typ": typ, "sub": str(sub), "role": role, "exp": int(time.time()) + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")
    return {"admin_session" if typ == "admin" else "session": tok}   # 관리자·지원자 쿠키는 따로 (11/10)


def interview(client: TestClient, cand_id: int, app_id: int) -> int:
    client.cookies.clear()
    client.cookies.update(cookie("candidate", cand_id))
    base = f"/api/interview/applications/{app_id}"
    assert client.get(f"{base}/guide").json()["can_start"]
    for step, kw in (("precheck", {"json": OK_CHECK}), ("identity", {"files": {"frame": ("f.jpg", b"x", "image/jpeg")}}),
                     ("prepare", {}), ("start", {})):
        r = client.post(f"{base}/{step}", **kw)
        assert r.status_code == 200, (step, r.text)
    sid = r.json()["session_id"]
    # 지원자마다 답변 태도를 다르게 (같은 수준이어도 점수가 갈리게): 못 답한 문항 비율, 침묵 비율, 시간 안에 마친 비율. 지원서 번호로 고정
    rnd = random.Random(app_id)
    miss, quiet = rnd.choice([0.0, 0.1, 0.2, 0.3]), rnd.uniform(0.05, 0.35)
    for _ in range(30):
        st = client.get(f"/api/interview/sessions/{sid}/state").json()
        if st["status"] != "in_progress":
            break
        q = st["question"]
        skip = q["kind"] == "tech" and rnd.random() < miss                 # 기술 질문에 답을 못 함 → 무응답 0점
        client.post(f"/api/interview/sessions/{sid}/questions/{q['id']}/answer", files={"audio": ("a.webm", b"voice", "audio/webm")},
                    data={"answer_sec": f"{rnd.uniform(40, 170):.1f}", "silence_ratio": f"{min(0.85, quiet + rnd.uniform(-0.05, 0.1)):.2f}",
                          "finished_in_time": str(rnd.random() > 0.15).lower(), "voiced_sec": "0.2" if skip else "60"})
    return sid


def main() -> None:
    from worker.app import celery
    celery.conf.task_always_eager = True
    from api.main import app
    db = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    hr = db.execute("SELECT id, role FROM admin_user WHERE login_id = 'hr01'").fetchone()
    targets = db.execute("""SELECT a.id AS app_id, c.id AS cand_id, c.name FROM application a JOIN candidate c ON c.id = a.candidate_id
                            WHERE a.status = 'stage2' AND c.email <> ALL(%s)
                              AND NOT EXISTS (SELECT 1 FROM interview_session s WHERE s.application_id = a.id)
                            ORDER BY a.id""", (list(DEMO),)).fetchall()
    with TestClient(app) as client:
        for t in targets:
            sid = interview(client, t["cand_id"], t["app_id"])
            client.cookies.clear()
            client.cookies.update(cookie("admin", hr["id"], hr["role"]))
            r = client.post(f"/api/admin/interviews/{sid}/confirm")
            s = r.json().get("stage2_score") if r.status_code == 200 else None
            print(f"{t['name']}: 면접 {s['interview_score'] if s else '-'} · 코딩 {s['coding_score'] if s else '-'} · "
                  f"{'확정' if s else '확정 못 함 ' + r.text[:80]}")
    for r in db.execute("""SELECT c.name, s.total_score, s.ai_rank, s.ai_recommendation FROM stage2_score s
                           JOIN application a ON a.id = s.application_id JOIN candidate c ON c.id = a.candidate_id ORDER BY s.ai_rank""").fetchall():
        print(f"  {r['ai_rank']}위 {r['name']} 총점 {r['total_score']} 추천 {r['ai_recommendation']}")
    db.close()


if __name__ == "__main__":
    main()
