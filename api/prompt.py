"""프롬프트 조립 (활동다이어그램 1109 5쪽). 프롬프트 글은 api/prompts/*.md 파일에 두고 {{변수}}에 값을 끼운다.
- 빈 변수가 하나라도 있으면 호출 전에 멈춘다 (PromptError). 비어도 되는 칸은 부르는 쪽이 '(없음)'을 넣는다
- prompt_version = 파일 내용 해시 8자리 → 호출 기록(llm_call)에 남긴다
"""
import hashlib
import os
import re

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
VAR = re.compile(r"\{\{(\w+)\}\}")
_cache: dict[str, tuple[str, str]] = {}


class PromptError(ValueError):
    pass


def load(name: str) -> tuple[str, str]:
    """(본문, 버전 8자리)"""
    if name not in _cache:
        with open(os.path.join(DIR, name + ".md"), encoding="utf-8") as f:
            text = f.read().strip()
        _cache[name] = (text, hashlib.sha256(text.encode()).hexdigest()[:8])
    return _cache[name]


def render(name: str, **values) -> tuple[str, str]:
    text, version = load(name)
    need = set(VAR.findall(text))
    empty = sorted(k for k in need if not str(values.get(k, "")).strip())
    if empty:
        raise PromptError(f"프롬프트 {name}: 빈 변수 {', '.join(empty)} — 호출하지 않음")
    return VAR.sub(lambda m: str(values[m.group(1)]), text), version
