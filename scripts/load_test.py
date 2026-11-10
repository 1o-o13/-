"""동시 접속 부하 시험 (11/10: 50명 이상). 시험용 공고·지원자 N명을 만들고, 모두 동시에 면접을 끝까지 본다.
지원자마다 SSE를 열어 둔 채 점검 → 본인 확인 → 준비 → 시작 → 10문항 답변. 답변 제출 → 다음 질문 표시까지 시간을 잰다(목표 ≤60초).
끝나면 만든 자료를 지운다. api 컨테이너 안에서:  python scripts/load_test.py 50
가짜 모듈(MODULE_MODE=stub)로 돌려야 LLM 비용 없이 서버·DB·작업자 처리량만 잰다 (compose.loadtest.yml)
"""
import asyncio
import os
import statistics
import sys
import time

import httpx
import jwt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import psycopg
from psycopg.rows import dict_row

BASE = os.environ.get("LOAD_BASE", "http://localhost:8000")
TITLE = "부하 시험 공고 (자동 삭제)"
CHECK = {"chrome": True, "camera": True, "mic": True, "upload_mbps": 20, "single_face": True,
         "consent_voice": True, "consent_face": True, "consent_ai": True, "consent_overseas": True}


def cookie(cid: int) -> dict:
    return {"session": jwt.encode({"typ": "candidate", "sub": str(cid), "exp": int(time.time()) + 7200}, os.environ["JWT_SECRET"], algorithm="HS256")}


def setup(db, n: int) -> list[tuple[int, int]]:
    hr = db.execute("SELECT id FROM admin_user WHERE login_id = 'hr01'").fetchone()["id"]
    handoff = db.execute("SELECT handoff FROM document_evaluation WHERE handoff IS NOT NULL LIMIT 1").fetchone()["handoff"]
    snap = db.execute("SELECT resume_snapshot FROM application ORDER BY id LIMIT 1").fetchone()["resume_snapshot"]
    pid = db.execute("""INSERT INTO job_posting(title, job_role, job_category, career_level, headcount, status, published_at, apply_start,
                            apply_end, doc_announce_at, stage2_start, stage2_end, final_announce_at, created_by)
                        VALUES (%s, '백엔드', 'non_dev', 'new', 5, 'published', now() - interval '3 day', now() - interval '3 day',
                                now() + interval '1 hour', now() + interval '2 hour', now() + interval '3 hour', now() + interval '2 day',
                                now() + interval '3 day', %s) RETURNING id""", (TITLE, hr)).fetchone()["id"]
    db.execute("INSERT INTO interview_setting(posting_id) VALUES (%s) ON CONFLICT DO NOTHING", (pid,))
    out = []
    for i in range(n):
        cid = db.execute("""INSERT INTO candidate(email, password_hash, name, phone, ci_hash) VALUES (%s, NULL, %s, %s, %s) RETURNING id""",
                         (f"load{i:03d}@test.local", f"부하{i:03d}", f"010-9{i:03d}-{i:04d}", f"load-ci-{i:03d}")).fetchone()["id"]
        aid = db.execute("INSERT INTO application(posting_id, candidate_id, resume_snapshot) VALUES (%s, %s, %s) RETURNING id",
                         (pid, cid, psycopg.types.json.Jsonb(snap))).fetchone()["id"]
        db.execute("INSERT INTO document_evaluation(application_id, version_no, fit_score, criteria_scores, rationale, handoff, provider, model, status) "
                   "VALUES (%s, 1, 0, '{}', '부하 시험', %s, 'rule', 'rule', 'passed')", (aid, psycopg.types.json.Jsonb(handoff)))
        db.execute("INSERT INTO stage_result(application_id, stage, result, decided_by) VALUES (%s, 'document', 'pass', %s)", (aid, hr))
        out.append((cid, aid))
    # 응시 기간 안으로 (접수 기간 안에 지원서를 넣어야 해서 나중에 옮김) · 2차 대상
    db.execute("""UPDATE job_posting SET apply_end = now() - interval '3 hour', doc_announce_at = now() - interval '2 hour',
                      stage2_start = now() - interval '1 hour' WHERE id = %s""", (pid,))
    db.execute("UPDATE application SET status = 'stage2' WHERE posting_id = %s", (pid,))
    from api import pregen                             # 실제 흐름처럼 1차 합격 때 질문을 미리 만들고 검증해 둔다 (시간 재기 전)
    for _, aid in out:
        pregen.prepare(db, aid)
        pregen.prepare_q3(db, aid)
    return out


def teardown(db) -> None:
    pid = db.execute("SELECT id FROM job_posting WHERE title = %s", (TITLE,)).fetchone()
    if not pid:
        return
    pid = pid["id"]
    sessions = "SELECT s.id FROM interview_session s JOIN application a ON a.id = s.application_id WHERE a.posting_id = %s"
    db.execute(f"DELETE FROM llm_call WHERE session_id IN ({sessions})", (pid,))
    db.execute("DELETE FROM ai_error_alert WHERE application_id IN (SELECT id FROM application WHERE posting_id = %s)", (pid,))
    db.execute(f"DELETE FROM suspicion_case WHERE interview_session_id IN ({sessions})", (pid,))
    db.execute(f"DELETE FROM interview_session WHERE id IN ({sessions})", (pid,))
    db.execute("DELETE FROM prepared_question WHERE application_id IN (SELECT id FROM application WHERE posting_id = %s)", (pid,))
    db.execute("DELETE FROM application WHERE posting_id = %s", (pid,))
    db.execute("DELETE FROM candidate WHERE email LIKE 'load%%@test.local'")
    db.execute("DELETE FROM interview_setting WHERE posting_id = %s", (pid,))
    db.execute("DELETE FROM job_posting WHERE id = %s", (pid,))


async def one(cid: int, aid: int, lat: list[float], errs: list[str]) -> None:
    async with httpx.AsyncClient(base_url=BASE, cookies=cookie(cid), timeout=120) as c:
        base = f"/api/interview/applications/{aid}"
        for step, kw in (("precheck", {"json": CHECK}), ("identity", {"files": {"frame": ("f.jpg", b"x", "image/jpeg")}}), ("prepare", {}), ("start", {})):
            r = await c.post(f"{base}/{step}", **kw)
            if r.status_code != 200:
                errs.append(f"{aid} {step} {r.status_code} {r.text[:80]}")
                return
        sid = r.json()["session_id"]
        sse = asyncio.create_task(c.get(f"/api/interview/sessions/{sid}/events", timeout=900))   # SSE를 열어 둔 채로
        last = None
        for _ in range(12):
            st = (await c.get(f"/api/interview/sessions/{sid}/state")).json()
            if st["status"] != "in_progress":
                break
            q = st["question"]
            if q is None or q["id"] == last:
                await asyncio.sleep(0.5)
                continue
            last = q["id"]
            r = await c.post(f"/api/interview/sessions/{sid}/questions/{q['id']}/answer", files={"audio": ("a.webm", b"voice", "audio/webm")},
                             data={"answer_sec": "60", "silence_ratio": "0.1", "finished_in_time": "true", "voiced_sec": "50"})
            if r.status_code != 202:
                errs.append(f"{aid} answer {r.status_code} {r.text[:80]}")
                return
            t0 = time.monotonic()
            while time.monotonic() - t0 < 90:              # 다음 질문(또는 종료)이 보일 때까지
                st = (await c.get(f"/api/interview/sessions/{sid}/state")).json()
                if st["status"] != "in_progress" or (st["question"] and st["question"]["id"] != last):
                    lat.append(time.monotonic() - t0)
                    break
                await asyncio.sleep(0.5)
            else:
                errs.append(f"{aid} 90초 안에 다음 질문 없음")
                return
        sse.cancel()


async def run(n: int) -> None:
    db = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    teardown(db)
    users = setup(db, n)
    lat, errs = [], []
    t0 = time.monotonic()
    try:
        await asyncio.gather(*(one(c, a, lat, errs) for c, a in users))
    finally:
        done = db.execute("""SELECT count(*) AS n FROM interview_session s JOIN application a ON a.id = s.application_id
                             JOIN job_posting p ON p.id = a.posting_id WHERE p.title = %s AND s.status = 'completed'""", (TITLE,)).fetchone()["n"]
        conns = db.execute("SELECT count(*) AS n FROM pg_stat_activity").fetchone()["n"]
        teardown(db)
    lat.sort()
    p = lambda q: lat[min(len(lat) - 1, int(len(lat) * q))] if lat else float("nan")   # noqa: E731
    print(f"동시 {n}명 · 전체 {time.monotonic() - t0:.0f}초 · 면접 완료 {done}/{n} · 답변 {len(lat)}건 · 오류 {len(errs)}건 · DB 연결(끝날 때) {conns}")
    print(f"답변 제출 → 다음 질문: 중앙값 {statistics.median(lat) if lat else float('nan'):.2f}초 · p95 {p(0.95):.2f}초 · 최대 {lat[-1] if lat else float('nan'):.2f}초 (목표 ≤60초)")
    for e in errs[:10]:
        print("  오류:", e)


if __name__ == "__main__":
    asyncio.run(run(int(sys.argv[1]) if len(sys.argv) > 1 else 50))
