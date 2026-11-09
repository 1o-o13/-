"""LLM 호출 관문 (활동다이어그램 1109 5쪽). 실제 모듈의 모든 LLM 호출은 이 call() 하나를 거친다.

프롬프트 조립(api/prompts/*.md, 빈 변수면 중단) → 지원자 개인정보 가림(이름·학교·주소 등, 면접 답변 포함, 11/12) → min_tier로 경로(route) → 외부면 누출 검사
(tier 1·2 본문·금지어, 개인정보 → 가림 1회 재검사, 그래도 걸리면 LEAK_BLOCKED → 사내 모델로) → 호출
(30초 대체·60초 한도, 연결 끊김 3회 재시도, 401·403은 재시도 없이 운영자 알림 + 사내 모델로) → 형식 오류면 오류 내용을 붙여 1회 재요청
→ 호출 기록 llm_call (목적·프롬프트 버전·제공자·모델·min_tier·토큰·시간·성공 여부. 프롬프트 본문은 남기지 않음)
"""
import logging
import os
import re
import time
from dataclasses import dataclass

from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

# 사내 모델(Ollama)에 보낼 때만 쓰는 형식: 글 칸에 최대 길이를 박은 같은 모양 (11/16). 작은 모델은 '두세 문장' 안내를 무시하고
# 이유를 길게 쓰다 출력 제한(700토큰)에 잘려 점수 칸까지 못 가는 일이 잦았다(판정 12번 중 5번). Ollama는 스키마의 maxLength를
# 생성 단계에서 강제하므로 짧게 끝나고 점수 칸이 반드시 채워진다. 외부 모델 형식은 그대로 (real_modules가 등록)
LOCAL_SCHEMA: dict = {}
# 아래 import가 real_modules를 불러 위 표에 등록하므로 표가 먼저 있어야 한다 (순환 import)
from api import modules as _paths  # noqa: F401  app_6_1·stubs_6_1 경로를 연다 (llm·contracts)
from api import prompt as P

# isort: split
import llm

log = logging.getLogger(__name__)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"01\d[- ]?\d{3,4}[- ]?\d{4}")
_RRN = re.compile(r"\d{6}[- ]?[1-4]\d{6}")          # 주민등록번호 형태
_secret: dict = {}                                   # tier 1·2 금지어·본문 조각 (프로세스마다 한 번 읽음)


@dataclass
class Result:
    role: str              # eval·fast·parse_error·system_error·blocked
    out: object | None
    model: str
    provider: str
    note: str = ""         # LEAK_BLOCKED·AUTH_ERROR·RETRY 등 (관리자 화면·리포트에 표시)


def _load_secret() -> dict:
    """tier 1·2 청크의 금지어와 본문 앞 40자 (누출 검사용). DB를 못 읽으면 빈 목록 (시험·DB 없는 실행)"""
    if not _secret:
        try:
            from api.db import connect
            with connect() as db:
                rows = db.execute("SELECT forbid, body FROM company_doc_chunk WHERE tier IN (1, 2)").fetchall()
            _secret["words"] = sorted({w for r in rows for w in r["forbid"] if len(w) >= 2}, key=len, reverse=True)
            _secret["bodies"] = [re.sub(r"\s+", " ", r["body"].strip())[:40] for r in rows if len(r["body"].strip()) >= 40]
        except Exception:
            _secret.update(words=[], bodies=[])
    return _secret


def leak_scan(text: str) -> list[str]:
    """외부 전송 직전 누출 검사: 걸린 항목 이름 목록 (비면 통과)"""
    s, flat = _load_secret(), re.sub(r"\s+", " ", text)
    hits = [f"금지어:{w}" for w in s["words"] if w in text][:3]
    hits += ["tier1·2 본문" for b in s["bodies"] if b in flat][:1]
    hits += [k for k, rx in (("PII:이메일", _EMAIL), ("PII:전화", _PHONE), ("PII:주민번호", _RRN)) if rx.search(text)]
    return hits


def mask_pii(text: str) -> str:
    return _RRN.sub("(가림)", _PHONE.sub("(가림)", _EMAIL.sub("(가림)", text)))


def choices(llm_cfg: dict | None) -> tuple[llm.LLMChoice, llm.LLMChoice]:
    """(외부 = 응시에 저장된 모델, 사내 = Ollama). 값이 없으면 .env"""
    m, env = llm_cfg or {}, llm.from_env()
    cloud = llm.LLMChoice(m.get("provider", env.provider), m.get("eval", env.eval_model), m.get("fast", env.fast_model))
    local = llm.LLMChoice("ollama", m.get("local", os.environ.get("LLM_LOCAL_MODEL", "qwen3:4b")),
                          os.environ.get("LLM_LOCAL_FAST_MODEL", "qwen3:1.7b"))
    return cloud, local


def _record(purpose: str, version: str, r: Result, min_tier: int | None, usage: llm.Usage, ms: int, ok: bool,
            session_id: int | None, application_id: int | None, error: str | None) -> None:
    try:
        from api.db import connect
        with connect() as db:
            db.execute("""INSERT INTO llm_call(session_id, application_id, purpose, prompt_version, provider, model, min_tier,
                              input_tokens, output_tokens, latency_ms, ok, route_note, error)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                       (session_id, application_id, purpose, version, r.provider, r.model, min_tier, usage.input_tokens,
                        usage.output_tokens, ms, ok, r.note or None, (error or "")[:300] or None))
    except Exception as e:
        log.warning("llm_call 기록 실패: %s", e)


def _alert_auth(provider: str, detail: str, application_id: int | None) -> None:
    log.error("LLM 키 오류 (%s): %s — 운영자 확인 필요", provider, detail)
    if application_id is None:
        return
    try:
        from api.db import connect
        with connect() as db:
            db.execute("""INSERT INTO ai_error_alert(stage, application_id, problem_part) VALUES ('interview', %s, %s)""",
                       (application_id, f"LLM 키 오류 {provider}: {detail}"[:300]))
    except Exception:
        pass


def _applicant_words(application_id: int | None, session_id: int | None) -> list[str]:
    """그 지원자의 개인정보 낱말 (store.personal_words). 지원 건을 모르거나 DB를 못 읽으면 빈 목록"""
    if application_id is None and session_id is None:
        return []
    try:
        from api.db import connect
        from api.interview.store import personal_words
        with connect() as db:
            r = db.execute("""SELECT resume_snapshot FROM application WHERE id = %s
                              OR id = (SELECT application_id FROM interview_session WHERE id = %s)""",
                           (application_id, session_id)).fetchone()
        return personal_words(r["resume_snapshot"]) if r else []
    except Exception:                                # noqa: BLE001  DB 없는 시험 실행
        return []


def call(purpose: str, schema, prompt_name: str, values: dict, *, llm_cfg: dict | None = None, min_tier: int | None = None,
         consent: bool = False, local_only: bool = False, session_id: int | None = None, application_id: int | None = None,
         t_fallback: float | None = None, t_error: float | None = None, extra: str = "", max_tokens: int = 1024) -> Result:
    """LLM 한 번 부르기. 형식 오류면 오류 내용을 붙여 1번만 다시. 실패해도 예외를 내지 않고 Result.out=None (부르는 쪽이 대체 경로).
    extra: 재생성 때 덧붙이는 안내 (금지어 고치기 등). 프롬프트 버전은 파일 기준 그대로"""
    text, version = P.render(prompt_name, **values)
    text = text + ("\n\n" + extra if extra else "")
    # 지원자 개인정보는 사내·외부 모델 모두에 보내지 않는다: 이력서는 이미 가린 글이지만, 면접 답변(STT)은 말한 그대로라 여기서 가린다
    from api.interview.store import mask_words
    text = mask_words(text, _applicant_words(application_id, session_id))
    system, _ = P.load("system")
    cloud, local = choices(llm_cfg)
    tier = 3 if min_tier is None else min_tier
    choice = local if local_only else llm.route(cloud, local, tier, consent)
    note = ""
    if choice.provider != "ollama":
        llm.assert_external_ok(choice, tier)
        hits = leak_scan(text)
        if hits and all(h.startswith("PII") for h in hits):
            text = mask_pii(text)                    # 개인정보는 가려서 1번 다시 검사
            hits = leak_scan(text)
        if hits:
            log.warning("LEAK_BLOCKED %s: %s → 사내 모델", purpose, ", ".join(hits))
            choice, note = local, "LEAK_BLOCKED"
    tf = t_fallback if t_fallback is not None else float(os.environ.get("LLM_FALLBACK_SEC", "30"))
    te = t_error if t_error is not None else float(os.environ.get("LLM_ERROR_SEC", "60"))
    msgs = [("system", system), ("human", text)]
    for attempt in (1, 2):
        usage, t0, err = llm.Usage(), time.monotonic(), None
        try:
            use = LOCAL_SCHEMA.get(schema, schema) if choice.provider == "ollama" else schema
            role, out = llm.judge_with_fallback(choice, use, msgs, t_fallback=tf, t_error=te, usage=usage, max_tokens=max_tokens)
        except llm.LLMAuthError as e:
            _alert_auth(choice.provider, str(e), application_id)
            role, out, err = "auth_error", None, str(e)
            if choice.provider != "ollama":          # 외부 키 오류: 다시 시도하지 않고 이 호출은 사내 모델로
                choice, note = local, "AUTH_ERROR"
                continue
        except (OutputParserException, ValidationError) as e:
            role, out, err = "parse_error", None, str(e)[:300]
            msgs = msgs[:2] + [("human", f"앞선 출력이 형식에 맞지 않았습니다: {err[:200]}\n스키마에 맞는 JSON만 다시 내 주세요.")]
        except Exception as e:
            role, out, err = "system_error", None, f"{type(e).__name__}: {e}"[:300]
        model = choice.fast_model if role == "fast" else choice.eval_model
        r = Result(role, out, model, choice.provider, (note + (f" RETRY {attempt}" if attempt > 1 else "")).strip())
        _record(purpose, version, r, min_tier, usage, int((time.monotonic() - t0) * 1000), out is not None, session_id, application_id, err)
        if out is not None or role != "parse_error":
            return r
    return r
