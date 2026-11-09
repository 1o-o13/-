# (가상) 새벽소프트 문서 메타데이터 규격 v0.3

corpus_v2(모아테크)의 v0.2 규격과 **같은 형식**이다. 같은 로더(`exp/corpus.py`)와 검색기(`exp/search.py`)로 읽는다. 다른 점만 적는다.

## 형식 (v0.2와 같음)

```
# 문서 제목
<!--meta: doc=PRJ-MED-3; doc_type=project; tier=3; topic=MED; disclosure=public; status=done; stages=1차|2차-->

## 섹션 제목
<!--meta: sec=s1; dept=AI|BE; level=신입|주니어; ct_band=하; related=INC-MED-01-->
<!--forbid: 단어1|단어2-->
본문
```

- 청크 1개는 `##` 섹션 1개다. 청크 ID는 `doc#sec`이고, `###`는 위 `##` 청크에 포함된다.
- 임베딩 머리말은 `[새벽소프트 | 문서 제목 | 난이도 | 부서 | 섹션 제목]`이다. `load_corpus(..., company="새벽소프트")`로 읽는다.
- 파일은 문서 종류별로 11개다(01–12, 10과 11은 한 파일). 파일 하나에 `#` 문서가 여러 개 들어 있다.

## v0.3에서 달라진 값

| 필드 | 값 |
| --- | --- |
| topic | MED 루미스캔(흉부 X-ray 판독 보조), DRN 스카이패스(실내 점검 드론), TKT 줄서기(티켓 예매 대기열), COMMON 공통 |
| dept | AI, BE, FE, **EMB**(임베디드), **DATA** |
| tier | 3, 2, 1, **0**(등급 사다리 밖: 단위 코드, 인재상, 기준, 공지. 단계 검색에서 항상 빠짐) |
| doc_type | v0.2의 값에 **unit_code**(코딩 테스트 연계), **criteria**(가산점·직무기술서·루브릭·용어집), **notice**(미끼 잡음)를 더함 |
| doc ID | v0.2에 더해 `TST-`, `UNT-`, `CRT-`, `JD-`, `RUB-`, `GLS-`, `NTC-`. 프로젝트는 `PRJ-<주제>-<등급>` (예: PRJ-MED-3) |

## 단계별 검색 대상: v2 그래프와 다른 점 (불일치, 종합 TRD에서 결정)

| 단계 | v2 (`exp/interview.py`) | LAB #3 (`lab3/stages.py`) |
| --- | --- | --- |
| 본 질문 | tier 3 project + **incident(status=resolved)** | tier 3 project만 |
| 꼬리 1 | tier 2, incident는 **status=unresolved만** | tier 2, incident 전부(장애 회고), open_issue, test_result |
| 꼬리 2 | tier 1, 꼬리 1 근거의 related 우선 | tier 1. F4R은 prev_doc의 양방향 related |
| 레벨 필터 | 본 질문 | 본 질문만 (규칙 A) |

새벽소프트 문서는 사용자 결정("꼬리 1 = 2급 기밀 문서, 장애 회고, 장애 해결 필요 과제")에 따라 해결된 장애 회고도 tier 2에 둔다. 그래서 새벽소프트 문서를 v2 그래프에 그대로 넣으면 꼬리 1에서 장애 회고가 걸러진다. 어느 규칙을 쓸지는 종합 TRD에서 정한다.

## status 값 (v0.2 규칙대로 채움)

| 문서 | status |
| --- | --- |
| 3급 project | done |
| 2급·1급 project, research | ongoing |
| incident | resolved |
| open_issue | unresolved |
| test_result | done |

## 10문항 면접 대비 (2026-11-04)

v2 면접은 10문항이고, 3~10번 8자리가 기술 질문이다. 지원자 한 명이 면접 한 번에 쓰는 3급 섹션이 바닥나지 않도록 다음을 지킨다. `python run_lab3.py check`가 이 규칙을 검사한다(lab3/session.py, T1–T3).

- 부서(AI·BE·FE·EMB)마다 3급 주제가 3개 이상 있다. 그래서 MED·TKT에 EMB 섹션을, TKT에 AI 섹션을 넣었다.
- 주제 × 부서 × 난이도마다 기술 섹션이 3개 이상 있다. 섹션 하나에 부서를 여러 개 붙여도 된다.
- 개요(sec=ov)는 근거가 없을 때 대체용으로만 쓴다. 이 개수에 넣지 않는다.
