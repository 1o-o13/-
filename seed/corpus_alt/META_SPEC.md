# (가상) 새벽소프트 문서 메타데이터 규격

6.1 화상면접 개발·시험용 가상 IT 회사 문서. 형식은 `seed/corpus_v3/META_SPEC.md`와 **같다** (`scripts/load_corpus.py`로 그대로 적재).
기존 `seed/corpus_v3`는 다른 파트와 공유하므로 건드리지 않고, 6.1 seed(`tasks.ps1 seed`)만 이 폴더를 쓴다.

## 회사

(가상) 새벽소프트 — 커머스·핀테크·커뮤니케이션·데이터·인프라·산업 IoT 서비스를 만드는 IT 개발 회사.
직무: 백엔드(BE), 프론트엔드(FE), ML 엔지니어(AI), 데이터 엔지니어(DATA), 임베디드(EMB). SRE·플랫폼 업무는 BE에 포함.

## 기술 주제 20개 (topic)

| topic | 프로젝트 | 내용 | 주요 기술 |
| --- | --- | --- | --- |
| PAY | 페이브릿지 | 결제 승인 게이트웨이 | Spring Boot, Kafka, PostgreSQL, Redis |
| SET | 정산온 | 가맹점 정산 배치 | Spring Batch, MySQL, S3, Airflow |
| CHT | 톡허브 | 실시간 채팅 | WebSocket, Redis Pub/Sub, Kafka, ScyllaDB |
| NTF | 알림센터 | 푸시·메일·문자 발송 | Go, SQS, FCM/APNs |
| SRC | 파인드 | 상품 검색 | OpenSearch, nori, BM25 |
| REC | 픽미 | 상품 추천 | Python, 피처 스토어, 협업 필터링 |
| LGS | 로지패스 | 배송 배차·경로 | PostGIS, 다익스트라, OR-Tools |
| INV | 스톡키퍼 | 재고 관리 | Redis, Debezium CDC, PostgreSQL |
| AUT | 원패스 | 통합 인증(SSO) | OAuth2/OIDC, Keycloak, JWT |
| GWY | 게이트키퍼 | API 게이트웨이 | Envoy, 토큰 버킷, 서킷 브레이커 |
| OBS | 와치타워 | 관측·모니터링 | Prometheus, OpenTelemetry, Grafana |
| CID | 쉽잇 | CI/CD 배포 플랫폼 | GitHub Actions, Argo CD, Kubernetes |
| VOD | 플레이온 | 영상 스트리밍 | FFmpeg, HLS, CDN |
| IOT | 팩토리아이 | 공장 설비 센서 | MQTT, TimescaleDB, C++ 엣지 |
| HLP | 헬프데스크 | 고객 상담 | 티켓 라우팅, LLM 요약 |
| ADS | 비드엔진 | 광고 실시간 입찰 | Go, 블룸 필터, 역색인 |
| DWH | 레이크하우스 | 데이터 플랫폼 | Airflow, Spark, Iceberg, dbt |
| FDS | 가디언 | 이상거래 탐지 | Flink, 룰 엔진, Union-Find |
| BKG | 부킹온 | 예약 시스템 | Kotlin, PostgreSQL, 낙관적 락 |
| WIK | 노트허브 | 협업 문서 | CRDT(Yjs), TypeScript |

## 주제마다 들어 있는 문서 (청크 9개 × 20 = 180개)

| 문서 | tier | 쓰임 | 섹션 |
| --- | --- | --- | --- |
| `PRJ-<주제>-3` 3급 프로젝트 | 3 (public) | 본 질문 | s1 하·s2 중·s3 상 (BE), s4 중 (FE·AI·DATA·EMB 중 하나) |
| `PRJ-<주제>-2` 상세 설계 | 2 (abstract) | 꼬리 1 | s1 |
| `INC-<주제>-01` 장애 회고 | 2 (abstract, resolved) | 꼬리 1 | s1 |
| `ISS-<주제>-01` 미해결 과제 | 2 (abstract, unresolved) | 꼬리 1 | s1 |
| `RES-<주제>-01`, `RES-<주제>-02` 연구 | 1 (abstract) | 꼬리 2 | s1 |

## 지킨 규칙

- 3~10번 기술 질문 8개가 모두 다음 주제로 넘어가도 주제가 남도록 주제 20개.
- 주제마다 난이도 상·중·하별 BE 본 질문 섹션이 1개 이상.
- 코딩 약점 알고리즘(BFS, DP, Union-Find, 그리디, 다익스트라, 슬라이딩 윈도우, 우선순위 큐, 정렬, 투 포인터, 해시)이 난이도마다 하나 이상의 BE 섹션 본문에 나온다 → 3번 질문이 약점 주제로 잡힌다.
- tier 2·1 문서에는 내부 시스템 이름·고객사 이름이 있고 `forbid`로 막는다. 본문 첫 20자에는 forbid 단어를 넣지 않는다.
- `related`는 기존 규격처럼 문서 ID로 적는다 (3급 → 2급, 2급 → 1급).
- 회사·프로젝트·고객사·장애 사례는 모두 가상이다.
