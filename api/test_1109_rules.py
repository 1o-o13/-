"""활동다이어그램 1109 규칙: LLM 호출 경로(누출 검사·tier 강제·프롬프트 빈 변수), 1차 서류 S0(요건·코드 검증), 검색 RRF"""
import pytest

from api import llm_gate as G
from api import prompt as P
from api import retrieve, screen

# isort: split
import llm
from contracts import CompanyDoc


def test_route_tier_and_consent():
    cloud, local = llm.LLMChoice("anthropic", "claude-sonnet-5-5", "claude-haiku-5-5"), llm.LLMChoice("ollama", "qwen3:4b", "qwen3:1.7b")
    assert llm.route(cloud, local, 3, True) is cloud
    assert llm.route(cloud, local, 0, True) is cloud           # tier 0(공용 기준 문서)은 tier 3과 같이
    assert llm.route(cloud, local, 2, True) is local and llm.route(cloud, local, 1, True) is local
    with pytest.raises(AssertionError):                       # tier 1·2 프롬프트를 외부로 보내려 하면 코드가 멈춤 (RAG-17)
        llm.assert_external_ok(cloud, 2)


def test_leak_scan_masks_pii_and_blocks_secret(monkeypatch):
    monkeypatch.setitem(G._secret, "words", ["비밀코드명"])
    monkeypatch.setitem(G._secret, "bodies", ["사내 장애 상세 본문 앞부분 사십 자를 그대로 넣어 둔 문장입니다 이것은"[:40]])
    assert G.leak_scan("연락처 010-1234-5678, a@b.co") == ["PII:이메일", "PII:전화"]
    assert G.leak_scan(G.mask_pii("연락처 010-1234-5678, a@b.co")) == []
    assert G.leak_scan("질문: 비밀코드명 이전 계획은?") == ["금지어:비밀코드명"]


def test_gate_masks_applicant_words_in_answers(monkeypatch, db_url):
    """면접 답변(STT)에 지원자 이름·학교·주소가 나와도 LLM에는 가려서 보낸다 (CLAUDE.md 0-8, 11/12)"""
    import psycopg
    from psycopg.rows import dict_row
    from api.interview.store import personal_words
    with psycopg.connect(db_url, row_factory=dict_row) as c:
        r = c.execute("""SELECT a.id, a.resume_snapshot AS s FROM application a JOIN candidate c ON c.id = a.candidate_id
                         WHERE c.email = 'cand01@test.local'""").fetchone()
    words = personal_words(r["s"])
    assert {"김하늘", "상계동", "노원구"} <= set(words) and any("한빛대" in w for w in words)   # 학교는 시험 데이터의 줄임말 표기
    assert G._applicant_words(r["id"], None) == words and G._applicant_words(None, None) == []
    sent = {}

    def fake(choice, schema, msgs, **kw):              # 실제 모델 대신 보낸 글만 받아 둔다
        sent["text"] = msgs[-1][1]
        return "eval", None
    monkeypatch.setattr(llm, "judge_with_fallback", fake)
    G.call("fit_judge", dict, "fit_judge", {"question": "협업 경험을 말해 주세요",
                                             "answer": "저는 김하늘이고 한빛대 다닐 때 상계동 스터디에서 010-1234-5678로 연락받았습니다"},
           application_id=r["id"], local_only=True)
    t = sent["text"]
    assert all(w not in t for w in ("김하늘", "한빛대", "상계동", "010-1234-5678")) and t.count("(가림)") >= 4
    assert "협업 경험" in t and "스터디" in t                                     # 나머지 내용은 그대로


def test_prompt_empty_variable_stops_before_call():
    text, version = P.render("eval_check", lines="3번 점수 80")
    assert "3번 점수 80" in text and len(version) == 8
    with pytest.raises(P.PromptError):
        P.render("eval_check", lines="  ")


DESC = "필수: Python 또는 Java로 REST API 개발, SQL 기본. 우대: Redis·Celery·Kafka, Docker, 성능 측정 경험."


def test_requirements():
    reqs = screen.requirements(DESC)
    assert [r["id"] for r in reqs] == ["REQ-1", "REQ-2", "PREF-1", "PREF-2", "PREF-3"]
    assert not hasattr(screen, "qualify")                                     # 하드 필터 없음 (11/12): 자동 탈락 없이 담당관이 고른다


def test_screen_verify_rules():
    reqs = screen.requirements(DESC)
    flat = "Python과 FastAPI로 REST API를 만들고 PostgreSQL 인덱스로 SQL 응답을 줄였습니다"
    lab = lambda i, label, q="": screen.ReqLabel(req_id=i, label=label, quote=q)   # noqa: E731
    good = screen.ScreenOut(labels=[lab("REQ-1", "충족", "FastAPI로 REST API를 만들고"), lab("REQ-2", "충족", "SQL 응답을 줄였습니다"),
                                    lab("PREF-1", "근거 없음"), lab("PREF-2", "근거 없음"), lab("PREF-3", "근거 없음")],
                            awards_opinion="-", work_fit="보통", overall="-", conclusion="추천", conclusion_req_ids=["REQ-1", "REQ-2"],
                            conclusion_quotes=["FastAPI로 REST API를 만들고", "SQL 응답을 줄였습니다"])
    assert screen.verify(good, reqs, flat) == []
    fake_quote = good.model_copy(update={"labels": [lab("REQ-1", "충족", "Kubernetes 운영 3년")] + good.labels[1:]})
    assert any("REQ-1 인용" in e for e in screen.verify(fake_quote, reqs, flat))     # 원문에 없는 인용
    bad_concl = good.model_copy(update={"conclusion": "추천", "conclusion_req_ids": ["REQ-1", "PREF-1"]})
    assert screen.verify(bad_concl, reqs, flat) == ["C: 추천 근거는 '충족' 요건에서만"]   # 결론 검사만 → 결론 빈칸 (보류 없음)
    missing = good.model_copy(update={"labels": good.labels[:2]})
    assert any(e.startswith("요건 빠짐") for e in screen.verify(missing, reqs, flat))


def test_rrf_ranks_bm25_without_vectors():
    docs = [CompanyDoc(chunk_id=f"D#{i}", doc_type="project", tier=3, topic="PAY", body=b)
            for i, b in enumerate(["결제 승인 지연을 캐시로 줄였다", "물류 센서 펌웨어 업데이트", "결제 재시도와 멱등 키 설계"])]
    hits = retrieve.rank("결제 재시도 멱등", docs, vector=False)
    assert hits[0].doc.chunk_id == "D#2" and hits[0].vec_rank is None and hits[-1].doc.chunk_id == "D#1"


def test_local_model_gets_length_capped_schema(monkeypatch):
    """사내 모델(Ollama)에는 글 칸 길이를 박은 형식(JTechLocal)을, 외부 모델에는 원래 형식을 쓴다 (11/16: 출력 제한에 잘리는 문제)"""
    from api.real_modules import JTech, JTechLocal
    used = []
    monkeypatch.setattr(llm, "judge_with_fallback", lambda choice, schema, *a, **k: (used.append((choice.provider, schema)), ("eval", None))[1])
    G.call("judge_tech", JTech, "judge_tech", {"question": "q", "key_points": "k", "evidence": "e", "answer": "a"}, local_only=True)
    assert used[-1] == ("ollama", JTechLocal)
    assert JTechLocal.model_json_schema()["properties"]["rationale"]["maxLength"] == 200
    assert "maxLength" not in JTech.model_json_schema()["properties"]["rationale"]


def test_local_model_gets_length_capped_question_schema():
    """꼬리질문·질문 생성도 사내 모델에는 길이를 박은 형식 (11/16: 근거 칸이 길어 꼬리질문 6번 중 5번 실패)"""
    from api.real_modules import QFollow, QFollowLocal, QOut, QOutLocal
    assert G.LOCAL_SCHEMA[QFollow] is QFollowLocal and G.LOCAL_SCHEMA[QOut] is QOutLocal
    p = QFollowLocal.model_json_schema()["properties"]
    assert p["basis"]["maxLength"] == 100 and p["question_text"]["maxLength"] == 150 and p["key_points"]["maxItems"] == 4
