"""면접 DB 읽기·쓰기. api 라우터와 worker가 같이 쓴다."""
import difflib
import json
import os
import re

from psycopg.types.json import Jsonb

from api import modules as M
from api.interview import engine
from contracts import Handoff, Judgement, Question, QuestionContext, WeaknessSummary

# 11/11 지원자 STT 확인·수정: 답변 뒤 인식된 글을 보여 주고, 인식 오류만 고친 뒤 '완료'를 누르면 판정·다음 질문 (60초 지나면 원본 그대로)
REVIEW_SEC = int(os.environ.get("STT_REVIEW_SEC", "60"))   # 0이면 확인 없이 바로 판정 (부하 시험)
EDIT_MAX = 0.3                                              # 원본 대비 바뀐 글자 비율 상한 (말하지 않은 답을 써 넣지 못하게)


def edit_ratio(original: str, edited: str) -> float:
    """원본 대비 바뀐 비율 (0 = 같음). 띄어쓰기 차이는 세지 않는다"""
    a, b = re.sub(r"\s+", "", original), re.sub(r"\s+", "", edited)
    if not a:
        return 0.0 if not b else 1.0
    return round(1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


def review(db, sid: int) -> dict | None:
    """지금 확인을 기다리는 답변: STT 중(ready=False)이거나 인식 글을 보여 주는 중(ready=True). 없으면 None"""
    r = db.execute("""SELECT a.id, q.id AS question_id, q.ask_order, a.stt_original, a.stt_done_at IS NOT NULL AS ready,
                             extract(epoch FROM now() - a.stt_done_at)::float AS since
                      FROM interview_answer a JOIN interview_question q ON q.id = a.question_id
                      WHERE q.session_id = %s AND a.stt_confirmed_at IS NULL ORDER BY q.ask_order DESC LIMIT 1""", (sid,)).fetchone()
    if r is None:
        return None
    left = max(0.0, REVIEW_SEC - (r.pop("since") or 0)) if r["ready"] else REVIEW_SEC
    return {"answer_id": r["id"], "question_id": r["question_id"], "ask_order": r["ask_order"], "ready": r["ready"],
            "text": r["stt_original"], "remaining_sec": round(left, 1), "edit_max": EDIT_MAX}


def audio_path(key: str) -> str:
    """답변 음성 임시 위치 (api·worker 공유 볼륨 AUDIO_DIR). STT 뒤 바로 지운다"""
    return os.path.join(os.environ.get("AUDIO_DIR", "/audio"), key)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"01\d-?\d{3,4}-?\d{4}")
_SCHOOL = re.compile(r"(?<!\S)\S+?(?:대학교|대학|대|고등학교)(?=[\s,(]|$)")


def mask_resume(snap: dict) -> str:
    """LLM에 넣는 이력서 글 (CLAUDE.md 0-8, IV-24). 인적사항(이름·성별·생년월일·나이·연락처·이메일·주소)은 빼고,
    그 값과 학력·학력사항의 학교 이름(줄임말 'OO대' 포함)이 본문에 나오면 가린다. 이메일·휴대폰 번호 형태도 가린다. 시험용 수준은 시험 데이터 전용이라 뺀다."""
    text = json.dumps({k: v for k, v in snap.items() if k not in ("인적사항", "시험용 수준")}, ensure_ascii=False)
    return mask_words(text, personal_words(snap))


def personal_words(snap: dict) -> list[str]:
    """이 지원자를 알아볼 수 있는 낱말 (긴 것부터): 인적사항 값(이름·연락처·이메일·주소·생년월일 등), 주소의 시·구·동,
    학력·학력사항의 학교 이름(줄임말 'OO대' 포함). 이력서와 면접 답변을 LLM에 보낼 때 가린다 (CLAUDE.md 0-8)"""
    personal = snap.get("인적사항") or {}
    words = [v for v in personal.values() if isinstance(v, str) and len(v) >= 2]
    words += [t for t in str(personal.get("주소", "")).split() if len(t) >= 2 and t[-1] in "시구동읍면군"]   # 11/12: 답변에 동네만 말해도
    words += _SCHOOL.findall(snap.get("학력", ""))
    schools = [e["학교"] for e in snap.get("학력사항") or [] if e.get("학교")]
    words += schools + [s[:-2] for s in schools if s.endswith("대학교")]          # 한빛대학교 → 한빛대
    return sorted(set(words), key=len, reverse=True)


def mask_words(text: str, words: list[str]) -> str:
    for w in words:
        text = text.replace(w, "(가림)")
    return _PHONE.sub("(가림)", _EMAIL.sub("(가림)", text))


def context(db, sid: int) -> QuestionContext:
    r = db.execute("""SELECT s.application_id, s.handoff, s.coding_weakness, s.ct_band, s.project_topic, a.resume_snapshot, p.job_role,
                             p.career_level, s.overseas_consent, s.llm_provider, s.llm_eval_model, s.llm_fast_model, s.llm_local_model
                      FROM interview_session s JOIN application a ON a.id = s.application_id JOIN job_posting p ON p.id = a.posting_id
                      WHERE s.id = %s""", (sid,)).fetchone()
    ctx = QuestionContext(application_id=r["application_id"], job_role=r["job_role"], resume_text=mask_resume(r["resume_snapshot"]),
                          handoff=Handoff(**r["handoff"]),
                          weakness=WeaknessSummary(**r["coding_weakness"]) if r["coding_weakness"] else None, ct_band=r["ct_band"],
                          project=r["project_topic"], overseas_consent=r["overseas_consent"],
                          llm={"provider": r["llm_provider"], "eval": r["llm_eval_model"], "fast": r["llm_fast_model"],
                               "local": r["llm_local_model"]},
                          docs=M.load_docs(db, r["ct_band"], engine.DEPT[r["job_role"]], engine.LEVEL[r["career_level"]]),
                          session_id=sid)
    if ctx.project is None:          # 처음 질문을 준비할 때 이력서와 가장 비슷한 프로젝트를 골라 응시에 고정
        ctx.project = M.pick_project(ctx)
        db.execute("UPDATE interview_session SET project_topic = %s WHERE id = %s AND project_topic IS NULL", (ctx.project, sid))
    return ctx


def setting(db, sid: int) -> dict:
    return db.execute("""SELECT st.* FROM interview_session s JOIN application a ON a.id = s.application_id
                         JOIN interview_setting st ON st.posting_id = a.posting_id WHERE s.id = %s""", (sid,)).fetchone()


def add_question(db, sid: int, q: Question, ask_order: int, parent_id: int | None = None, asked: bool = False) -> int:
    return db.execute("""INSERT INTO interview_question(session_id, kind, question_type, depth, tech_stack, parent_question_id, ask_order,
                             question_text, basis, source_doc_ids, min_tier, key_points, defense, generated_by_model, asked_at)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END) RETURNING id""",
                      (sid, q.kind, q.question_type, q.depth, q.tech_stack, parent_id, ask_order, q.question_text, q.basis,
                       Jsonb(q.source_doc_ids), q.min_tier, Jsonb(q.key_points), Jsonb(q.defense) if q.defense else None, q.model,
                       asked)).fetchone()["id"]


RELEVANCE = "관련성(CE)"   # 임시: 답변 관련성 전용 칸이 없어(스키마 변경은 승인 필요) answer_judgement.rubric jsonb에 같이 둔다. 점수 합에는 안 들어감


def rubric_with_relevance(j: Judgement) -> dict:
    return j.rubric if j.relevance is None else {**j.rubric, RELEVANCE: j.relevance}


def to_question(r: dict) -> Question:
    return Question(kind=r["kind"], question_type=r["question_type"], depth=r["depth"], tech_stack=r["tech_stack"],
                    question_text=r["question_text"], basis=r["basis"], source_doc_ids=r["source_doc_ids"] or [],
                    min_tier=r["min_tier"], key_points=r["key_points"], model=r["generated_by_model"], defense=r.get("defense") or {})


def save_judgement(db, answer_id: int, j: Judgement) -> None:
    db.execute("""INSERT INTO answer_judgement(answer_id, status, score, rubric, opinion, lang_structure, lang_terms, lang_intent,
                      quotes, rationale, model_tier, provider, model, latency_ms)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
               (answer_id, j.status, j.score, Jsonb(rubric_with_relevance(j)), Jsonb(j.opinion) if j.opinion is not None else None,
                j.lang_structure, j.lang_terms, j.lang_intent, Jsonb(j.quotes), j.rationale, j.model_tier, M.provider_of(j.model), j.model,
                j.latency_ms))


FACE_LABELS = ("미소", "긴장", "놀람", "무표정", "시선 아래", "얼굴 없음")   # 화면(web/lib/face.ts expression)과 같은 이름


def save_face_signals(db, answer_id: int, raw: str | None) -> None:
    """화면이 보낸 표정 구간 [{t0, t1, label, value}] (ms, 녹음 시작 기준). 이름이 맞는 것만, 최대 200개. 점수에 쓰지 않고 표기만"""
    if not raw:
        return
    try:
        rows = [r for r in json.loads(raw)[:200] if r.get("label") in FACE_LABELS and 0 <= int(r["t0"]) <= int(r["t1"])]
    except (ValueError, TypeError, KeyError):
        return
    db.cursor().executemany("""INSERT INTO answer_signal(answer_id, source, t_start_ms, t_end_ms, label, value)
                               VALUES (%s, 'face', %s, %s, %s, %s)""",
                            [(answer_id, int(r["t0"]), int(r["t1"]), r["label"], Jsonb(r.get("value") or {})) for r in rows])


def save_voice_signals(db, answer_id: int, segments: list[dict]) -> None:
    """STT 구간별 목소리 표기 (stt 컨테이너가 잰 음량·높낮이·말 빠르기). 구간 글도 같이 둔다 (리포트에서 STT와 나란히)"""
    db.cursor().executemany("""INSERT INTO answer_signal(answer_id, source, t_start_ms, t_end_ms, label, value)
                               VALUES (%s, 'voice', %s, %s, %s, %s)""",
                            [(answer_id, int(g["start"] * 1000), int(g["end"] * 1000), g["label"],
                              Jsonb({k: g[k] for k in ("text", "db", "f0", "cps", "pause") if k in g})) for g in segments])


VOICE_SHIFT = 0.35     # 임시: 이 답변 목소리 높이(중앙값)가 앞 답변들과 35% 넘게 다르면 '다른 목소리 의심' 표기 (11/12)


def flag_voice_change(db, answer_id: int) -> bool:
    """다른 사람이 대신 말하는지 참고 표기 (11/12): 이 답변의 목소리 높이(f0) 중앙값을 같은 응시의 앞 답변들(2개 이상)과 비교.
    점수·자동 불합격에 쓰지 않고 관리자 리포트에 '다른 목소리 의심'으로만 남긴다 (감기·긴장으로도 바뀔 수 있음)"""
    import statistics
    rows = db.execute("""SELECT g.answer_id, (g.value->>'f0')::float AS f0, g.t_end_ms FROM answer_signal g
                         JOIN interview_answer a ON a.id = g.answer_id JOIN interview_question q ON q.id = a.question_id
                         WHERE g.source = 'voice' AND g.value ? 'f0' AND g.value->>'f0' IS NOT NULL
                           AND q.session_id = (SELECT q2.session_id FROM interview_answer a2 JOIN interview_question q2 ON q2.id = a2.question_id
                                               WHERE a2.id = %s)""", (answer_id,)).fetchall()
    mine = [r["f0"] for r in rows if r["answer_id"] == answer_id]
    before: dict[int, list[float]] = {}
    for r in rows:
        if r["answer_id"] < answer_id:
            before.setdefault(r["answer_id"], []).append(r["f0"])
    if not mine or len(before) < 2:
        return False
    base = statistics.median(statistics.median(v) for v in before.values())
    now = statistics.median(mine)
    if abs(now - base) / base <= VOICE_SHIFT:
        return False
    end = max(r["t_end_ms"] for r in rows if r["answer_id"] == answer_id)
    db.execute("""INSERT INTO answer_signal(answer_id, source, t_start_ms, t_end_ms, label, value)
                  VALUES (%s, 'voice', 0, %s, '다른 목소리 의심', %s)""", (answer_id, end, Jsonb({"f0": round(now, 1), "앞 답변 f0": round(base, 1)})))
    return True


def history(db, sid: int) -> list[dict]:
    """판정까지 끝난 문항, 물어본 순서대로. 각 줄: qid, q(Question), j(Judgement), stt, answer_sec, finished_in_time, silence_ratio"""
    rows = db.execute("""SELECT q.*, a.stt_text, a.answer_sec, a.finished_in_time, a.silence_ratio,
                                j.status AS j_status, j.score, j.rubric, j.opinion, j.quotes, j.rationale, j.lang_structure, j.lang_terms,
                                j.lang_intent, j.model_tier, j.model AS j_model, j.latency_ms
                         FROM interview_question q JOIN interview_answer a ON a.question_id = q.id
                         JOIN answer_judgement j ON j.answer_id = a.id AND j.is_current
                         WHERE q.session_id = %s ORDER BY q.ask_order""", (sid,)).fetchall()
    return [{"qid": r["id"], "ask_order": r["ask_order"], "q": to_question(r), "stt": r["stt_text"],
             "j": Judgement(status=r["j_status"], score=None if r["score"] is None else float(r["score"]),
                            rubric={k: v for k, v in (r["rubric"] or {}).items() if k != RELEVANCE}, relevance=(r["rubric"] or {}).get(RELEVANCE),
                            opinion=r["opinion"], quotes=r["quotes"] or [], rationale=r["rationale"], lang_structure=r["lang_structure"],
                            lang_terms=r["lang_terms"], lang_intent=r["lang_intent"], model_tier=r["model_tier"], model=r["j_model"],
                            latency_ms=r["latency_ms"]),
             "answer_sec": float(r["answer_sec"]), "finished_in_time": r["finished_in_time"],
             "silence_ratio": float(r["silence_ratio"])} for r in rows]


def state(db, sid: int) -> dict:
    """재접속 복구용 현재 상태 (CAN-012). 점수·판정은 넣지 않는다 (IV-43).
    phase: think(생각) / record(녹음) / review(답변 인식 글 확인, 11/11) / preparing(다음 질문 준비 중) / ended(종료)"""
    s = db.execute("""SELECT s.status, st.total_questions, st.think_sec_non_tech, st.think_sec_tech, st.answer_max_sec, st.silence_skip_sec,
                             EXISTS (SELECT 1 FROM answer_accommodation x WHERE x.application_id = a.id AND x.status = 'approved') AS text_ok
                      FROM interview_session s JOIN application a ON a.id = s.application_id
                      JOIN interview_setting st ON st.posting_id = a.posting_id WHERE s.id = %s""", (sid,)).fetchone()
    out = {"status": s["status"], "total_questions": s["total_questions"], "silence_skip_sec": s["silence_skip_sec"],
           "question": None, "phase": "ended", "remaining_sec": 0, "review": None,
           "answer_mode": "text" if s["text_ok"] else "voice"}          # 11/12 글로 답하기 승인된 지원자
    if s["status"] != "in_progress":
        return out
    rv = review(db, sid)
    if rv:                                          # 답변 인식 글 확인 중 (11/11): 다음 질문은 '완료' 뒤에
        return {**out, "phase": "review", "review": rv}
    # 지금 문항 = 보여 준(asked_at) 뒤 아직 답변이 없는 것. 추가 시간은 이 문항을 보여 준 뒤 받은 것만 (IV-33)
    q = db.execute("""SELECT q.id, q.ask_order, q.kind, q.question_type, q.depth, q.question_text,
                             extract(epoch FROM now() - q.asked_at)::float AS elapsed,
                             (SELECT coalesce(sum(i.extra_time_sec), 0) FROM interview_incident i
                              WHERE i.session_id = q.session_id AND i.chat_ended_at >= q.asked_at) AS extra
                      FROM interview_question q LEFT JOIN interview_answer a ON a.question_id = q.id
                      WHERE q.session_id = %s AND q.asked_at IS NOT NULL AND a.id IS NULL
                      ORDER BY q.ask_order DESC LIMIT 1""", (sid,)).fetchone()
    if q is None:
        return {**out, "phase": "preparing"}
    think = s["think_sec_non_tech"] if q["kind"] == "non_tech" else s["think_sec_tech"]
    elapsed = q.pop("elapsed")
    record_end = think + s["answer_max_sec"] + q.pop("extra")
    phase, remaining = ("think", think - elapsed) if elapsed < think else ("record", max(0.0, record_end - elapsed))
    return {**out, "question": q, "phase": phase, "remaining_sec": round(remaining, 1)}


def identity_ok(s: dict) -> str | None:
    """본인 확인을 마쳐 다음 단계(코딩·면접)로 갈 수 있는지. 못 가면 이유 (11/10: 일치해야만 통과).
    얼굴 대조에 동의하지 않은 응시만 촬영 없이 담당자 확인 경로로 통과"""
    if not s["identity_status"]:
        return "본인 확인을 먼저 해 주세요"
    if s["identity_status"] == "match" or not (s.get("precheck") or {}).get("consent_face", True):
        return None
    return "본인 확인이 되지 않아 응시할 수 없습니다. '문의하기'의 담당자 연락처로 문의해 주세요"


def stop_system_error(db, sid: int, error_code: str) -> None:
    """판정 60초 초과 등: 판정이 아니라 시스템 오류로 응시를 멈추고 장애 기록 (담당자가 재응시를 줄 수 있음, IV-44)"""
    with db.transaction():
        db.execute("""UPDATE interview_session SET status = 'system_error', ended_at = now(), end_reason = 'system_error'
                      WHERE id = %s""", (sid,))
        db.execute("""INSERT INTO interview_incident(session_id, error_code, cause, chat_started_at, outcome)
                      VALUES (%s, %s, 'system', now(), 'stopped_reported')""", (sid, error_code))
