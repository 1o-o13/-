"""무료(Ollama) ↔ 유료(Claude) 전환 시험. 같은 시험을 두 제공사로 똑같이 돌린다.
실제 서버 대신 두 회사의 API 형식(/api/chat, /v1/messages)을 흉내 내는 로컬 서버를 쓴다 (비용·키 없음).
실행: pytest -q app_6_1/
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal

import pytest
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm import LLMChoice, LLMConfigError, chat_model, check_config, judge_with_fallback, ping_models, route, structured  # noqa: E402

ANSWER = {"judgement": "보통", "rationale": "핵심 개념을 맞게 설명함"}


class Judgement(BaseModel):
    judgement: Literal["우수", "보통", "미흡", "무응답"]
    rationale: str


@pytest.fixture(scope="module")
def fake():
    """Ollama와 Anthropic 형식을 둘 다 받는 가짜 서버. slow에 넣은 모델은 늦게 답한다."""
    state = {"slow": set(), "sec": 0.0, "seen": [], "known": {"qwen3:4b", "qwen3:1.7b", "claude-sonnet-5-5", "claude-haiku-5-5"}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["seen"].append((self.path, req.get("model")))
            if req.get("model") not in state["known"]:
                return self.send({"type": "error", "error": {"type": "not_found_error", "message": "model not found"}}, 404)
            if req["model"] in state["slow"]:
                time.sleep(state["sec"])
            if self.path == "/api/chat":                          # Ollama
                content = json.dumps(ANSWER, ensure_ascii=False) if req.get("format") else "보통"
                return self.send({"model": req["model"], "created_at": "2026-11-04T00:00:00Z", "done": True,
                                  "done_reason": "stop", "message": {"role": "assistant", "content": content}})
            if self.path == "/v1/messages":                       # Anthropic
                key = self.headers.get("x-api-key") or (self.headers.get("Authorization") or "").removeprefix("Bearer ")
                if key != "test-key":
                    return self.send({"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}, 401)
                tools = req.get("tools") or []
                schema = req.get("output_format") or req.get("output_config")     # JSON 스키마 방식 (structured()가 씀)
                block = ({"type": "tool_use", "id": "toolu_1", "name": tools[0]["name"], "input": ANSWER} if tools
                         else {"type": "text", "text": json.dumps(ANSWER, ensure_ascii=False) if schema else "보통"})
                return self.send({"id": "msg_1", "type": "message", "role": "assistant", "model": req["model"],
                                  "content": [block], "stop_reason": "tool_use" if tools else "end_turn",
                                  "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}})
            self.send({}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    state["env"] = {"OLLAMA_BASE_URL": url, "ANTHROPIC_BASE_URL": url, "ANTHROPIC_API_KEY": "test-key"}
    yield state
    srv.shutdown()


CHOICES = {
    "무료 Ollama": LLMChoice("ollama", "qwen3:4b", "qwen3:1.7b"),
    "유료 Claude": LLMChoice("anthropic", "claude-sonnet-5-5", "claude-haiku-5-5"),
}


@pytest.mark.parametrize("name", CHOICES)
def test_same_judgement_format_both_providers(fake, name):
    c = CHOICES[name]
    out = structured(chat_model(c, "eval", env=fake["env"]), Judgement).invoke("답변: 인덱스는 B-트리 ...")
    assert out == Judgement(**ANSWER)
    assert chat_model(c, "fast", env=fake["env"]).invoke("q").content == "보통"


@pytest.mark.parametrize("name", CHOICES)
def test_fallback_rule_both_providers(fake, name):
    """30초 대체·60초 오류 규칙이 제공사와 상관없이 같게 동작 (시험은 1/100 축소: 0.3초·0.6초)."""
    c, env = CHOICES[name], fake["env"]
    fake.update(slow=set(), sec=0)
    assert judge_with_fallback(c, Judgement, "q", 0.3, 0.6, env)[0] == "eval"
    fake.update(slow={c.eval_model}, sec=0.5)
    role, out = judge_with_fallback(c, Judgement, "q", 0.3, 0.6, env)
    assert role == "fast" and out.judgement == "보통"
    fake.update(slow={c.eval_model, c.fast_model}, sec=0.5)
    assert judge_with_fallback(c, Judgement, "q", 0.3, 0.6, env) == ("system_error", None)
    fake.update(slow=set(), sec=0)


def test_switch_is_env_only():
    """코드는 그대로, .env만 바꿔서 전환."""
    free = {"LLM_PROVIDER": "ollama", "LLM_EVAL_MODEL": "qwen3:4b", "LLM_FAST_MODEL": "qwen3:1.7b"}
    paid = {"LLM_PROVIDER": "anthropic", "LLM_EVAL_MODEL": "claude-sonnet-5-5", "LLM_FAST_MODEL": "claude-haiku-5-5",
            "ANTHROPIC_API_KEY": "k"}
    assert type(chat_model(check_config(free), "eval", env=free)).__name__ == "ChatOllama"
    assert type(chat_model(check_config(paid), "eval", env=paid)).__name__ == "ChatAnthropic"


def test_running_interview_keeps_its_model():
    """.env를 유료로 바꿔도, 시작할 때 DB에 저장한 값(무료)으로 진행 중인 면접은 그대로."""
    paid_env = {"LLM_PROVIDER": "anthropic", "LLM_EVAL_MODEL": "claude-sonnet-5-5", "LLM_FAST_MODEL": "claude-haiku-5-5",
                "ANTHROPIC_API_KEY": "k"}
    saved_at_start = LLMChoice("ollama", "qwen3:4b", "qwen3:1.7b")      # interview_session에서 읽은 값
    assert type(chat_model(saved_at_start, "eval", env=paid_env)).__name__ == "ChatOllama"


@pytest.mark.parametrize("env, msg", [
    ({"LLM_PROVIDER": "anthropic", "LLM_EVAL_MODEL": "claude-sonnet-5-5", "LLM_FAST_MODEL": "claude-haiku-5-5"}, "ANTHROPIC_API_KEY"),
    ({"LLM_PROVIDER": "claude", "LLM_EVAL_MODEL": "a", "LLM_FAST_MODEL": "b"}, "지원하지 않음"),
    ({"LLM_PROVIDER": "ollama", "LLM_EVAL_MODEL": "qwen3:4b", "LLM_FAST_MODEL": "qwen3:4b"}, "같음"),
    ({"LLM_PROVIDER": "ollama", "LLM_EVAL_MODEL": "qwen3:4b"}, "둘 다 필요"),
])
def test_bad_config_fails_at_startup(env, msg):
    with pytest.raises(LLMConfigError, match=msg):
        check_config(env)


@pytest.mark.parametrize("choice, msg", [
    (LLMChoice("anthropic", "claude-sonet-5-5", "claude-haiku-5-5"), "eval 모델 연결 실패"),      # 이름 오타
    (LLMChoice("ollama", "qwen3:4b", "gemma4:e4"), "fast 모델 연결 실패"),
])
def test_ping_catches_wrong_model_name(fake, choice, msg):
    with pytest.raises(LLMConfigError, match=msg):
        ping_models(choice, fake["env"])
    ping_models(CHOICES["유료 Claude"], fake["env"])                       # 맞는 이름은 통과


def test_ping_catches_wrong_key(fake):
    env = dict(fake["env"], ANTHROPIC_API_KEY="wrong")
    with pytest.raises(LLMConfigError, match="AuthenticationError"):
        ping_models(CHOICES["유료 Claude"], env)


def test_route_keeps_internal_docs_on_premise():
    """tier ≤ 2 근거나 국외 전송 미동의는 외부 API로 가지 않는다 (RAG-17)."""
    ext, local = LLMChoice("anthropic", "claude-sonnet-5-5", "claude-haiku-5-5"), LLMChoice("ollama", "qwen3:4b", "qwen3:1.7b")
    assert route(ext, local, 3, True) is ext
    assert route(ext, local, 2, True) is local      # 꼬리 1 (사내 진행 중 문서)
    assert route(ext, local, 1, True) is local      # 꼬리 2 (연구 문서)
    assert route(ext, local, 3, False) is local     # 동의 없음
    assert route(local, local, 1, True) is local
