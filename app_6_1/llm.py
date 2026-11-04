"""LLM 연결은 이 파일 한 곳에서만 만든다. 모델을 바꿀 때는 코드가 아니라 .env만 고친다.

  테스트: LLM_PROVIDER=ollama     LLM_EVAL_MODEL=qwen3:4b         LLM_FAST_MODEL=qwen3:1.7b
  운영  : LLM_PROVIDER=anthropic  LLM_EVAL_MODEL=claude-sonnet-5-5  LLM_FAST_MODEL=claude-haiku-5-5  ANTHROPIC_API_KEY=...

바꿔도 오류가 안 나게 하는 장치
1. check_config(): 서버 시작 때 설정을 검사해서, 면접 도중이 아니라 시작할 때 실패시킨다.
2. ping_models(): 시작 때 두 모델에 짧게 요청해 이름 오타·키 오류를 미리 잡는다.
3. 응시 중인 면접은 시작할 때 DB(interview_session)에 복사해 둔 제공사·모델을 그대로 쓴다.
   .env를 바꿔도 진행 중인 면접은 영향이 없고, 새 면접부터 바뀐다.
4. 판정 형식(JSON 스키마)은 제공사와 상관없이 같은 pydantic 모델로 받는다.
"""
import os
import time
from dataclasses import dataclass

import httpx

PROVIDERS = ("ollama", "anthropic")


class LLMConfigError(RuntimeError):
    pass


class LLMAuthError(RuntimeError):
    """API 키 오류 401·403: 재시도하지 않고 멈춘 뒤 운영자에게 알린다 (활동다이어그램 1109 5쪽)"""


CONNECT_RETRY = (1.0, 2.0, 4.0)   # 연결 끊김(RemoteDisconnected 등)은 LLM 오류로 바꿔 지수 백오프로 최대 3회 다시 (5쪽)
_CONNECT = ("ConnectError", "RemoteProtocolError", "ReadError", "APIConnectionError", "RemoteDisconnected", "ConnectionError",
            "ConnectionResetError", "ConnectionRefusedError")


def _status_code(e: Exception) -> int | None:
    return getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)


class Usage:
    """호출 기록용 토큰 수 (LangChain 콜백). 제공사가 알려 주지 않으면 0"""
    def __init__(self):
        from langchain_core.callbacks import BaseCallbackHandler

        outer = self
        self.input_tokens = self.output_tokens = 0

        class _H(BaseCallbackHandler):
            def on_llm_end(self, response, **kw):
                for gen in response.generations:
                    for g in gen:
                        um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                        outer.input_tokens += um.get("input_tokens", 0)
                        outer.output_tokens += um.get("output_tokens", 0)
        self.handler = _H()


@dataclass(frozen=True)
class LLMChoice:              # interview_session에 저장되는 값과 같음 (llm_provider, llm_eval_model, llm_fast_model)
    provider: str
    eval_model: str
    fast_model: str


def from_env(env=os.environ) -> LLMChoice:
    return LLMChoice(env.get("LLM_PROVIDER", "ollama"), env.get("LLM_EVAL_MODEL", ""), env.get("LLM_FAST_MODEL", ""))


def check_config(env=os.environ) -> LLMChoice:
    c = from_env(env)
    errors = []
    if c.provider not in PROVIDERS:
        errors.append(f"LLM_PROVIDER={c.provider!r} 는 지원하지 않음 (가능: {', '.join(PROVIDERS)})")
    if not c.eval_model or not c.fast_model:
        errors.append("LLM_EVAL_MODEL, LLM_FAST_MODEL 둘 다 필요")
    elif c.eval_model == c.fast_model:
        errors.append("평가 모델과 빠른 모델이 같음 (평가 근거 검증은 다른 모델이어야 함)")
    if c.provider == "anthropic" and not env.get("ANTHROPIC_API_KEY"):
        errors.append("LLM_PROVIDER=anthropic 인데 ANTHROPIC_API_KEY 없음")
    if errors:
        raise LLMConfigError(" / ".join(errors))
    return c


def chat_model(choice: LLMChoice, role: str, timeout: float | None = None, env=os.environ, max_tokens: int = 1024):
    """role: 'eval'(질문·판정·평가) 또는 'fast'(30초 대체·검증·챗봇). choice는 응시 중이면 DB에 저장된 값."""
    model = choice.eval_model if role == "eval" else choice.fast_model
    if choice.provider == "ollama":
        from langchain_ollama import ChatOllama
        # reasoning=False: qwen3 생각 모드 끔 (켜 두면 판정 1건에 60초를 넘김, 11/9 측정. 끄면 1~2초)
        return ChatOllama(model=model, base_url=env.get("OLLAMA_BASE_URL", "http://ollama:11434"),
                          temperature=0, reasoning=False, num_predict=700 if max_tokens == 1024 else max_tokens,
                          client_kwargs={"timeout": timeout})
        # num_predict: 작은 모델이 JSON을 못 닫고 끝없이 생성하는 경우 서버 쪽에서 끊는다 (클라이언트 시간 초과만으로는 서버가 계속 돔)
    if choice.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        kw = {"base_url": env["ANTHROPIC_BASE_URL"]} if env.get("ANTHROPIC_BASE_URL") else {}
        # temperature는 넣지 않는다: Claude 5.5는 기본값 외 temperature를 거부함 (11/4 시험에서 확인)
        return ChatAnthropic(model=model, api_key=env.get("ANTHROPIC_API_KEY"),
                             timeout=timeout, max_retries=0, max_tokens=max_tokens, **kw)
    raise LLMConfigError(f"지원하지 않는 제공사: {choice.provider}")


def structured(llm, schema):
    """같은 pydantic 스키마로 결과를 받는다. 둘 다 JSON 스키마 강제
    (Claude 5.5는 도구 호출 강제 방식을 지원하지 않는다는 경고가 나와 json_schema로 바꿈, 11/9)"""
    return llm.with_structured_output(schema, method="json_schema")


def ping_models(choice: LLMChoice, env=os.environ) -> None:
    for role in ("eval", "fast"):
        try:
            chat_model(choice, role, timeout=30, env=env).invoke("ping")
        except Exception as e:                       # 이름 오타·키 오류·서버 꺼짐을 시작 때 알린다
            raise LLMConfigError(f"{role} 모델 연결 실패 ({choice.provider}): {type(e).__name__}: {e}") from e


def warm_local(model: str, env=os.environ) -> None:
    """사내 모델을 GPU에 미리 올려 둔다. 처음 올리는 데 30초 넘게 걸려(1660 SUPER, 11/9) 첫 질문 생성이 시간 초과로
    취소되면 로딩까지 같이 취소되기 때문. 서버 시작 때 백그라운드로 한 번 (OLLAMA_KEEP_ALIVE 24h 동안 유지)"""
    try:
        httpx.post(env.get("OLLAMA_BASE_URL", "http://ollama:11434") + "/api/generate",
                   json={"model": model, "keep_alive": "24h", "prompt": "준비", "think": False, "stream": False,
                         "options": {"num_predict": 1}}, timeout=300)   # 짧은 문장 하나까지 처리해야 첫 요청의 GPU 준비(20초+)가 끝남
    except httpx.HTTPError:
        pass                                          # 못 올려도 첫 요청 때 다시 시도된다


def judge_with_fallback(choice: LLMChoice, schema, prompt, t_fallback=30.0, t_error=60.0, env=os.environ, usage: Usage | None = None,
                        max_tokens: int = 1024):
    """TR-09: 평가 모델이 t_fallback 안에 답하지 않으면 빠른 모델로, 전체가 t_error를 넘으면 시스템 오류(None).
    연결 끊김은 시간 안에서 1·2·4초 쉬고 최대 3회 다시, 401·403은 다시 하지 않고 LLMAuthError."""
    t0 = time.monotonic()
    config = {"callbacks": [usage.handler]} if usage else None
    for role, limit in (("eval", t_fallback), ("fast", None)):
        for wait in (*CONNECT_RETRY, None):
            left = t_error - (time.monotonic() - t0)
            if left <= 0:
                return "system_error", None
            timeout = min(limit, left) if limit else left
            try:
                return role, structured(chat_model(choice, role, timeout=timeout, env=env, max_tokens=max_tokens), schema).invoke(prompt, config=config)
            except (httpx.TimeoutException, TimeoutError):
                break                                # 이 모델은 시간 초과 → 다음(빠른) 모델
            except Exception as e:                   # Anthropic SDK의 시간 초과는 자체 예외 클래스(APITimeoutError)
                name = type(e).__name__
                if "Timeout" in name:
                    break
                if _status_code(e) in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
                    raise LLMAuthError(f"{choice.provider} 키 오류 {_status_code(e)}: {name}") from e
                if name in _CONNECT or isinstance(e, (httpx.TransportError, ConnectionError)):
                    if wait is None:
                        raise
                    time.sleep(min(wait, max(0.0, t_error - (time.monotonic() - t0))))
                    continue
                raise
    return "system_error", None


def route(choice: LLMChoice, local: LLMChoice, min_tier: int, overseas_consent: bool) -> LLMChoice:
    """LLM 경로 (영찬 RAG TRD 9장, RAG-17). 프롬프트 근거 중 tier 1·2가 하나라도 있으면 온프레미스(local)로 보낸다.
    tier 0(공용 기준 문서)은 tier 3과 같이 취급. 국외 전송 동의는 응시 필수(1109)지만, 동의가 없는 옛 응시는 안전하게 사내로."""
    if choice.provider == "ollama" or (min_tier not in (1, 2) and overseas_consent):
        return choice
    return local


def assert_external_ok(choice: LLMChoice, min_tier: int) -> None:
    """외부로 보내기 직전 강제 검사: tier 1·2가 든 프롬프트는 Ollama가 아닌 어떤 공급자에도 못 보낸다 (RAG-17)"""
    assert choice.provider == "ollama" or min_tier not in (1, 2), f"tier {min_tier} 프롬프트를 외부({choice.provider})로 보내려 함"
