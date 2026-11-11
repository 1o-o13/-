"""포트폴리오 엑셀 만들기 (11/11): records/의 기록으로 바탕화면 portfolio_6_1.xlsx를 새로 만든다. PC(호스트)에서 실행.
  python scripts/build_portfolio.py
시트: 요약(수식) · 모델·버전 · 시험 기록 · 측정 수치 · 고친 문제 · 면접 기록
- 시험 기록·측정 수치·면접 기록은 records/test_runs.csv · measurements.csv · interviews/*.json에서 (tasks.ps1이 자동으로 쌓음)
- 모델·버전과 고친 문제는 아래 표(MODELS·FIXES)를 고쳐서 늘린다
"""
import csv
import glob
import json
import os
import re
import unicodedata
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REC = os.path.join(ROOT, "records")
OUT = os.path.join(os.path.expanduser("~"), "Desktop", "portfolio_6_1.xlsx")   # 11/11: 바탕화면에 둠
FONT = "Arial"


def lock(name: str, pkg: str) -> str:
    """requirements/*.lock.txt·frontend package.json에서 고정 버전 읽기"""
    p = os.path.join(ROOT, "requirements", name)
    try:
        text = open(p, encoding="utf-8").read()
    except OSError:
        return "-"
    m = re.search(rf'^{re.escape(pkg)}==([^\s]+)', text, re.M) or re.search(rf'"{re.escape(pkg)}":\s*"([^"]+)"', text)
    return m.group(1) if m else "-"


# (구분, 용도, 모델, 버전·설정, 실행 위치, 비고)
MODELS = [
    ("언어 모델", "1차 서류 검토 · 질문 생성·검증 · 답변 판정 · 최종 평가", "claude-sonnet-5-5", "Anthropic API", "외부", "tier 3 문서·국외 전송 동의 시"),
    ("언어 모델", "대체 판정(30초 초과) · 짧은 검사 · 채용 홈 챗봇", "claude-haiku-5-5", "Anthropic API", "외부", "60초 넘으면 점수 보류 + 다음 주제"),
    ("언어 모델", "사내 보안 문서(tier 1·2) 근거 처리", "qwen3:4b", "Ollama", "이 PC (GPU 6GB)", "코드에서 외부 전송 차단 (RAG-17)"),
    ("언어 모델", "사내 모델 빠른 작업", "qwen3:1.7b", "Ollama", "이 PC", ""),
    ("언어 모델", "코딩 테스트 문제 만들기·검사", "claude-sonnet-5-5", "Anthropic API", "외부", ""),
    ("검색", "회사 문서·인재상 벡터 검색", "bge-m3", "1024차원 · pgvector " + "0.8.7-pg17", "Ollama + Postgres", "HyDE 결핍 가치 유사도에도 사용"),
    ("검색", "키워드 검색", "BM25", f"rank-bm25 {lock('api.lock.txt', 'rank-bm25')} + kiwipiepy {lock('api.lock.txt', 'kiwipiepy')}", "api", "벡터 검색과 RRF(k=60)로 합침"),
    ("검색", "검색 결과 재정렬", "BAAI/bge-reranker-v2-m3", "CrossEncoder", "nli 컨테이너 (CPU)", ""),
    ("검증", "근거 일치 검사 (NLI)", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7", "모순 ≥0.3 실패 · 일치 ≥0.6 통과", "nli 컨테이너 (CPU)", "그 사이는 사내 모델 판단"),
    ("음성", "답변 음성 → 글 (STT) + 목소리 톤", "faster-whisper large-v3-turbo", f"faster-whisper {lock('stt.lock.txt', 'faster-whisper')} · int8_float16", "stt 컨테이너 (GPU)", "음성은 STT 뒤 삭제"),
    ("음성", "질문 읽어 주기 (TTS)", "Supertonic 3", f"supertonic {lock('tts.lock.txt', 'supertonic')}", "tts 컨테이너 (CPU)", ""),
    ("얼굴", "본인 확인 얼굴 대조", "InsightFace buffalo_l (11/16, 그 전 DeepFace ArcFace)", f"insightface {lock('face.extra.lock.txt', 'insightface')} · onnxruntime {lock('face.lock.txt', 'onnxruntime')} · 거리 ≤0.55 본인 · ≤0.75 재촬영", "face 컨테이너 (CPU)", "사진·프레임 저장 안 함. 비교: 엑셀 '얼굴 비교'"),
    ("얼굴", "얼굴 찾기 (감지)", "YuNet", "OpenCV", "face 컨테이너", "Haar는 사진에서 얼굴을 못 찾아 교체"),
    ("얼굴", "면접 중 감독 · 표정", "MediaPipe FaceLandmarker", f"@mediapipe/tasks-vision {lock('frontend.package.json', '@mediapipe/tasks-vision')}", "지원자 브라우저", "영상은 브라우저 밖으로 안 보냄"),
    ("구조", "진행 흐름 (지원 건 1개 = 그래프 1개, 면접 S2·S3)", "LangGraph", f"langgraph {lock('api.lock.txt', 'langgraph')} · checkpoint-postgres {lock('api.lock.txt', 'langgraph-checkpoint-postgres')}", "api · worker", "오류가 나도 면접은 멈추지 않음"),
    ("구조", "비동기 작업 (1차 검토·질문 미리 생성·STT 뒤 처리·얼굴 대조)", "Celery", f"celery {lock('api.lock.txt', 'celery')} · threads 16", "worker", ""),
    ("구조", "API · 웹", "FastAPI · Next.js", f"fastapi {lock('api.lock.txt', 'fastapi')} · next {lock('frontend.package.json', 'next')}", "api · web", "웹은 운영 서버 + 무중단 자동 반영"),
]

# (날짜, 분류, 문제, 원인, 고친 방법, 확인)
FIXES = [
    ("2026-11-09", "본인 확인", "다른 사람 얼굴로 본인 확인 통과", "다시 찍어도 처음 저장된 결과를 돌려줌", "촬영할 때마다 다시 대조, 결과를 바로 보여 주고 일치해야만 다음으로", "본인 0.28 통과 · 다른 사람 0.61 막힘"),
    ("2026-11-10", "본인 확인", "증명사진 얼굴 감지 실패", "Haar 감지기가 사진에서 얼굴을 못 찾음", "YuNet 감지기로 교체 + 작업자 시작 때 모델 미리 불러오기", "실제 사진으로 대조 성공"),
    ("2026-11-10", "본인 확인", "일치 기준이 느슨함 (0.55)", "다른 사람 0.61과 간격이 좁음", "기준 0.45로 (본인 최대 0.35)", "측정 표 참고"),
    ("2026-11-10", "성능", "동시 접속 때 DB 연결 고갈·멈춤", "SSE가 연결을 계속 잡고, 연결 안에서 또 연결을 엶", "응답 전에 연결 반납 · 그래프 동시 실행 제한(8) · 연결 수 조정", "동시 100명 오류 0"),
    ("2026-11-10", "자원", "서버 작업 프로세스가 죽음", "worker가 메모리 6.5GB 사용 (16GB PC)", "Celery를 threads 방식(16개)으로", "6.5GB → 0.6GB"),
    ("2026-11-10", "운영", "화면을 고칠 때마다 손으로 재시작", "개발 서버는 느리고 운영 서버는 다시 빌드가 필요", "운영 서버 + 뒤에서 빌드 → 준비되면 전환 (실패하면 옛 화면 유지)", "부하 중 693건 모두 200"),
    ("2026-11-10", "운영", "재부팅 뒤 프록시 오류", "컨테이너 자동 재시작 설정 없음", "모든 컨테이너 restart 정책", ""),
    ("2026-11-10", "LLM", "1차 서류 검토 결과가 중간에 잘림", "응답 길이 1024 토큰 제한", "용도별 max_tokens (서류 3000)", ""),
    ("2026-11-10", "상태", "상세 단계가 잘못 읽힘", "공통 상태를 먼저 바꿔 단계를 다시 읽어 냄", "상태를 바꾸기 전에 단계를 먼저 고정", "pytest"),
    ("2026-11-10", "성능", "1차 '합격' 클릭이 5초 넘게 걸림", "클릭 때마다 결핍 가치 계산(LLM 2번)을 기다림", "합격 뒤 작업을 백그라운드 작업으로", "E2E"),
    ("2026-11-10", "로그인", "관리자·지원자 동시 로그인 불가", "쿠키 하나를 같이 씀", "지원자·관리자 쿠키 분리", "pytest"),
    ("2026-11-11", "운영", "Docker 재시작 뒤 2~3분 접속 불가", "켜질 때마다 패키지 재설치 + 전체 빌드", "지난 빌드 바로 띄우기 + lock이 바뀔 때만 설치", "2초"),
    ("2026-11-11", "면접", "답변이 5초 만에 넘어감", "5초 침묵 자동 제출", "자동 제출 없앰 ('답변 끝' 또는 최대 3분)", "E2E"),
    ("2026-11-11", "채용 홈", "접수 전 공고가 '전형 진행 중'으로 숨겨짐", "접수 예정 상태가 없음", "'접수 예정 · 시작일' 상태 추가", "E2E"),
    ("2026-11-11", "STT", "인식 오류가 그대로 판정에 들어감", "지원자가 인식 글을 볼 수 없음", "답변 뒤 인식 글 확인·수정(30%까지, 60초) → 완료 → 다음 질문. 원본·수정본 모두 보관", "pytest · E2E"),
    ("11-16", "판정", "사내 판정 모델(qwen3:4b)이 판정 형식을 자주 못 지켜 점수 보류·재시도(판정 시간 증가)",
     "작은 모델이 '두세 문장' 안내를 무시하고 판정 이유를 길게 써서 출력 제한(700토큰)에 글이 잘림 — 형식 오류가 아니라 잘림 (30번 중 11번)",
     "사내 모델에 보낼 때만 글 칸 최대 길이(이유 200자 등)를 형식(JSON 스키마)에 박음. Ollama가 생성 단계에서 길이를 강제 → 점수 칸까지 반드시 채움. 외부 모델 형식은 그대로",
     "형식 성공 63% → 100%, 판정 10.2초 → 7.8초, 좋음 93·보통 53·약함 8점으로 구분 유지, pytest 151"),
]

# STT·TTS 후보 비교 (11/11 조사). 한국어 CER = FLEURS 한국어 test, Q8_0 양자화 (models.handy.computer/languages/ko, 2026-11 확인).
# 속도 = 실시간 대비 배수 (Ryzen 4750U, GPU Vulkan / CPU). 우리 PC(GPU 6GB)에서 직접 잰 값이 아님 → 녹음 음성 시험으로 다시 잴 것
# (구분, 모델, 강한 언어, 지원 언어, 한국어 CER(%), 크기·속도, 라이선스, 우리 환경 메모, 출처)
SPEECH = [
    ("STT", "faster-whisper large-v3-turbo (지금 사용)", "영어 최강 · 다국어 고르게", "99개 언어", 5.24, "0.8GB · GPU 3.1× / CPU 1.4×", "MIT", "지금 stt 컨테이너(GPU int8_float16). 침묵에서 문장을 지어내는 문제가 있어 침묵은 STT 전에 거름", "models.handy.computer"),
    ("STT", "Whisper large-v3", "영어 · 다국어", "99개 언어", 4.89, "1.6GB · GPU 2.0× / CPU 1.0×", "MIT", "turbo보다 조금 정확, 약 1.5배 느림. 6GB GPU에 qwen3와 같이 올리면 빠듯", "models.handy.computer"),
    ("STT", "Qwen3-ASR-1.7B", "중국어(방언) · 영어 · 한국어 상위", "30개 언어 + 중국 방언 22개", 4.60, "2.0GB · GPU 4.1× / CPU 2.5×", "Apache-2.0", "한국어 정확도 1위. faster-whisper가 아니라 새 런타임 필요 (설치 전 승인)", "models.handy.computer · github.com/QwenLM/Qwen3-ASR"),
    ("STT", "Qwen3-ASR-0.6B", "중국어 · 영어", "30개 언어", 5.82, "0.8GB · GPU 9.7× / CPU 5.3×", "Apache-2.0", "turbo 수준 정확도에 3배 빠름. CPU로도 실시간 넘음", "models.handy.computer"),
    ("STT", "Fun-ASR-MLT-Nano-2512", "중국어 · 다국어", "다국어(31)", 5.20, "0.8GB · GPU 8.8× / CPU 5.5×", "FunASR 모델 라이선스", "정확도·속도 균형 최고(비교 사이트 추천). 상업 이용 조건 확인 필요", "models.handy.computer"),
    ("STT", "SenseVoiceSmall", "중국어 · 광둥어 · 영어 · 일본어 · 한국어", "50개+ (주력 5개)", 8.27, "0.24GB · GPU 27.7× / CPU 19.7×", "FunASR 모델 라이선스", "매우 빠름 + 감정·소리 사건 태그를 함께 냄 (목소리 톤 표기에 쓸 수 있음). 정확도는 낮음", "models.handy.computer · FunAudioLLM 논문"),
    ("STT", "Moonshine base-ko", "한국어 전용", "한국어", 8.12, "0.07GB · GPU 17.5× / CPU 11.2×", "MIT", "아주 작음. CPU만으로 빠르게 돌릴 때 후보", "models.handy.computer"),
    ("STT", "★ whisper-large-v3-turbo-korean (ghost613)", "한국어 특화 (Zeroth-Korean 추가 학습)", "한국어", "2.06 (Zeroth 시험셋)", "turbo와 같음 (0.8GB)", "모델 카드에 표기 없음 (원본 MIT)",
     "지금 쓰는 turbo를 한국어로 더 학습한 것 → 같은 faster-whisper로 바꿔 끼우기 가장 쉬움(CTranslate2 변환 필요). 학습 전 같은 시험셋 7.58%. FLEURS와 시험셋이 달라 직접 비교 금지", "huggingface.co/ghost613/whisper-large-v3-turbo-korean"),
    ("STT", "★ Qwen3-ASR-1.7B (한국어 공개 비교 1위)", "한국어 · 중국어 · 영어", "30개 언어", 4.60, "2.0GB", "Apache-2.0", "위 행과 같은 모델. 한국어 정확도만 보면 첫 후보", "models.handy.computer"),
    ("STT", "★ KRAFTON Raon-Speech-9B", "한국어 · 영어 (2개 언어 음성 LLM)", "한국어 · 영어", "자체 발표: 한국어 ASR 전 항목 최고", "9B · GPU 다수 필요", "모델 카드 확인 필요", "6GB GPU에서는 못 돌림. 한국어 최고 성능 참고용. 정규화 방식에 따라 CER이 크게 달라진다는 지적 있음", "arxiv.org/abs/2605.23912 · huggingface.co/KRAFTON"),
    ("STT", "★ NAVER CLOVA Speech (클라우드)", "한국어 상용 서비스", "한국어 중심 (그 밖 언어는 확인 필요)", "공개 비교 없음", "외부 API", "유료", "음성이 외부로 나감 → 국외·외부 전송 동의와 비용 검토 필요. 비교 기준선으로만", "-"),
    ("STT", "Whisper medium / small", "영어 · 다국어", "99개 언어", "5.46 / 7.70", "0.77 / 0.25GB", "MIT", "GPU가 모자랄 때 낮춰 쓰는 후보", "models.handy.computer"),
    ("STT", "NVIDIA Parakeet", "영어 · 유럽어", "유럽어 중심", "지원 안 함", "-", "CC-BY-4.0", "한국어(CJK) 미지원 → 제외", "soniqo.audio"),
    ("TTS", "Supertonic 3 (지금 사용)", "영어 · 한국어 · 일본어", "31개 언어", "-", "99M · CPU 실시간 이상 · 44.1kHz", "OpenRAIL-M (코드 MIT)", "지금 tts 컨테이너(CPU). 미러 공지에 따르면 2026-08-31 뒤 공식 개발·지원 중단 → 대체 후보 필요", "huggingface.co/lnkiai/supertonic-3-mirror · supertone.ai"),
    ("TTS", "MeloTTS (KR)", "영어(억양 4종) · 중국어 · 한국어", "영·스·프·중·일·한", "-", "CPU 실시간", "MIT", "한국어 전용 모델이 따로 있음. CPU로 가볍게 대체 가능", "웹 정리 글 (모델 카드 확인 필요)"),
    ("TTS", "Qwen3-TTS 0.6B / 1.7B", "중국어 · 영어", "10개 언어 (한국어 포함)", "-", "GPU 권장", "Apache-2.0", "목소리 설계(1.7B)·복제. GPU를 qwen3:4b와 나눠 써야 함", "scriptbyai.com · 모델 카드"),
    ("TTS", "CosyVoice 2 (0.5B)", "중국어(방언) · 영어", "중·영·일·한·광둥어", "-", "GPU 권장", "Apache-2.0", "3초 음성으로 목소리 복제. 면접관 목소리를 정해 둘 때 후보", "웹 정리 글"),
    ("TTS", "XTTS-v2 (Coqui)", "다국어 목소리 복제", "17개 언어 (한국어 포함)", "-", "GPU 권장", "CPML (비상업)", "회사(Coqui) 종료 · 비상업 라이선스라 채용 서비스에는 부적합", "웹 정리 글"),
    ("TTS", "Kokoro-82M", "영어 최상급", "8개 언어 (한국어 없음)", "-", "82M · CPU 빠름", "Apache-2.0", "한국어 미지원 → 제외", "soniqo.audio 등"),
    ("TTS", "브라우저 음성 (speechSynthesis)", "OS 음성에 따름", "OS별", "-", "지원자 PC", "-", "지금 TTS 실패 때 대체로 씀. PC마다 목소리가 다름", "-"),
]

# ---------- 꾸미기 ----------
NAVY, INK, GRAY, LINE, BAND, CARD = "1F3A5F", "1F2937", "6B7280", "D5DCE6", "F4F7FB", "EAF1FA"
ACCENT = "D9822B"
TOP = 5          # 표 머리줄 행 (1행 여백 · 2행 제목 · 3행 설명 · 4행 여백)
LEFT = 2         # B열부터 (A열은 왼쪽 여백)


def dw(v) -> int:
    """화면 폭 (한글·전각 2칸)"""
    return round(sum(1.8 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(v if v is not None else "")))


def font(size=10, bold=False, color=INK) -> Font:
    return Font(name=FONT, size=size, bold=bold, color=color)


def lines_for(text, width: float) -> int:
    """폭 width(문자 칸)에 줄 내림했을 때 줄 수"""
    room = max(4, int(width) - 2)
    return sum(max(1, -(-dw(x) // room)) for x in str(text).split("\n"))


def frame(ws, title: str, desc: str, ncols: int) -> None:
    """시트 공통: 왼쪽·위 여백, 제목·설명, 격자선 끄기, 인쇄 설정 (표·칸 폭을 정한 뒤에 부른다)"""
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.row_dimensions[1].height = 14
    ws.row_dimensions[4].height = 8
    last = get_column_letter(LEFT + ncols - 1)
    ws.cell(row=2, column=LEFT, value=title).font = font(16, True, NAVY)
    ws.row_dimensions[2].height = 30
    for k in range(ncols):                        # 제목 아래 강조선
        ws.cell(row=2, column=LEFT + k).border = Border(bottom=Side(style="medium", color=ACCENT))
    ws.merge_cells(f"B3:{last}3")
    c = ws.cell(row=3, column=LEFT, value=desc)
    c.font, c.alignment = font(10, color=GRAY), Alignment(wrap_text=True, vertical="center")
    total = sum(ws.column_dimensions[get_column_letter(LEFT + k)].width or 10 for k in range(ncols))
    ws.row_dimensions[3].height = 15 * lines_for(desc, total) + 8
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True


def table(ws, headers: list[str], rows: list[list], caps: list[int], *, fmt: dict[int, str] | None = None,
          center: set[int] = frozenset(), top: int = TOP, filt: bool = True) -> int:
    """B열·TOP행부터 표: 칸 폭은 내용 길이에 맞추고(최대 caps), 넘치면 줄 내림 + 행 높이를 줄 수에 맞춤. 마지막 행 번호를 돌려준다"""
    fmt = fmt or {}
    widths = []
    for k, h in enumerate(headers):
        longest = dw(h) + 4
        for r in rows:
            v = r[k] if k < len(r) else None
            if v is not None and not isinstance(v, datetime):
                longest = max(longest, max(dw(x) for x in str(v).split("\n")) + 3)
        if "yy" in fmt.get(k, ""):
            longest = max(longest, 18)
        widths.append(max(8, min(caps[k], longest)))
        ws.column_dimensions[get_column_letter(LEFT + k)].width = widths[-1]
    for k, h in enumerate(headers):
        c = ws.cell(row=top, column=LEFT + k, value=h)
        c.font, c.fill = font(10, True, "FFFFFF"), PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[top].height = 26
    for i, r in enumerate(rows, top + 1):
        n = 1
        for k, v in enumerate(r):
            c = ws.cell(row=i, column=LEFT + k, value=v)
            c.font = font(10)
            c.alignment = Alignment(vertical="center", wrap_text=True, horizontal="center" if k in center else "left",
                                    indent=0 if k in center else 1)
            c.border = Border(bottom=Side(style="thin", color=LINE))
            if (i - top) % 2 == 0:
                c.fill = PatternFill("solid", fgColor=BAND)
            if k in fmt:
                c.number_format = fmt[k]
            if isinstance(v, str):
                n = max(n, lines_for(v, widths[k]))
        ws.row_dimensions[i].height = max(22, 15 * n + 7)
    last = top + len(rows)
    if filt and rows:
        ws.auto_filter.ref = f"{get_column_letter(LEFT)}{top}:{get_column_letter(LEFT + len(headers) - 1)}{last}"
    ws.freeze_panes = ws.cell(row=top + 1, column=LEFT)
    return last



# ---------- STT·TTS 비교 (11/12) ----------
BENCH_NOTE = {   # 모델마다 한 줄 평가 (결과를 보고 적음). 이름은 speech_bench.csv의 model 값
    "faster-whisper large-v3-turbo": "지금 서비스. 가장 빠른 축(RTF 0.2)에 GPU 1.3GB. '새벽소프트→새벽 서포트', 'API→에이 비아' 같은 영어 약어가 약하고, 답변 끝 무음에 '한글자막 by …'를 지어냄(1건)",
    "faster-whisper-hint large-v3-turbo": "지금 모델에 회사·기술 용어 힌트(약 50개)와 자막류 문구 거르기만 더함. GPU·속도 그대로에 정확도는 Qwen3-ASR-0.6B와 거의 같고 사람 목소리 용어 인식은 1위(91%). 이 PC(6GB)에서 추천",
    "faster-whisper large-v3": "TTS 음성은 turbo보다 낫지만 실제 목소리는 더 나쁨(9.4%). 두 배 느리고 GPU 2.3GB. 같은 자막 환각 있음 → 바꿀 이유 없음",
    "qwen-asr Qwen/Qwen3-ASR-1.7B": "정확도 1위(내 목소리 4.3%, TTS 3.1%), 'Redis'·'API'·'P95'를 영어로 바르게 적음. 단 GPU 4.7GB라 qwen3:4b(약 4GB)와 6GB GPU에 같이 못 올림, turbo보다 3.5배 느림. 무음에 '그렇죠.' 같은 짧은 말을 지어냄(VAD 없이 잰 값)",
    "qwen-asr Qwen/Qwen3-ASR-0.6B": "정확도 2위(5.2%)로 turbo보다 좋고 GPU 2GB. 다만 이 PC에서는 turbo보다 5배 느림(RTF 0.96 — fp16, 배치 1). 무음에 '네.'·'아.'를 지어냄 → 앞에 VAD(무음 거르기)를 붙이면 가장 현실적인 교체 후보",
    "sensevoice FunAudioLLM/SenseVoiceSmall": "압도적으로 빠름(RTF 0.03)·GPU 1.1GB·무음 환각 0. 정확도는 10%로 낮고 영어 용어가 약함. 감정·소리 태그를 함께 내서 목소리 톤 참고용으로는 쓸모",
    "moonshine moonshine-ai/moonshine-base-ko": "아주 작음(0.25GB). TTS 음성은 6.4%로 괜찮지만 실제 목소리는 18.8%로 약함. 무음에서 '배 배 배…' 반복을 지어냄 → 부적합",
    "hf-whisper ghost613/whisper-large-v3-turbo-korean": "한국어 추가 학습판이지만 가장 나쁨(23.5%). 읽기 음성(Zeroth)으로만 학습해 영어 용어를 못 적고, 모델 카드에도 '학습이 덜 됨'. 무음에서 뉴스 문장을 반복해 지어냄 → 부적합",
    "supertonic-3": "지금 서비스(CPU). 왕복 CER 5.0%로 가장 또렷하고 목소리 10종. 2026-08 뒤 공식 지원 중단 공지가 있어 대체 후보는 필요",
    "qwen3-tts-0.6b": "또렷함은 Supertonic과 같은 수준(5.0%)이고 한국어 목소리(Sohee)가 자연스러움. 하지만 이 GPU는 bf16이 없어 fp32로 돌려 문장 하나에 평균 36초(RTF 3.6) → 면접 질문 음성으로는 너무 느림",
    "cosyvoice2-0.5b": "짧은 견본 음성(Supertonic F1·M1)으로 목소리를 따라 함. 또렷함 5.5%로 나쁘지 않지만 'JWT'를 '망팡탐팡팡'처럼 영어 약어를 뭉갬. 문장당 14초(RTF 1.35)라 실시간 질문 음성으로는 느림. 설치가 가장 까다로움(torch·deepspeed 충돌)",
    "melotts-kr": "CPU급으로 가볍고 가장 빠름(합성 RTF 0.08). 또렷함 5.6%로 Supertonic과 비슷하지만 한국어 목소리가 1종뿐이고 영어 용어 발음이 약함(76%)",
}
SIZE = {   # 내려받은 크기(대략)
    "faster-whisper large-v3-turbo": "0.8GB", "faster-whisper-hint large-v3-turbo": "0.8GB", "faster-whisper large-v3": "3.1GB", "qwen-asr Qwen/Qwen3-ASR-0.6B": "1.9GB",
    "qwen-asr Qwen/Qwen3-ASR-1.7B": "4.7GB", "sensevoice FunAudioLLM/SenseVoiceSmall": "0.9GB",
    "moonshine moonshine-ai/moonshine-base-ko": "0.25GB", "hf-whisper ghost613/whisper-large-v3-turbo-korean": "3.2GB",
    "supertonic-3": "0.4GB", "melotts-kr": "0.2GB", "qwen3-tts-0.6b": "2.5GB", "cosyvoice2-0.5b": "1.7GB",
}
SHORT = {"faster-whisper-hint large-v3-turbo": "large-v3-turbo + 용어 힌트·환각 거르기", "faster-whisper ": "", "qwen-asr Qwen/": "", "sensevoice FunAudioLLM/": "", "moonshine moonshine-ai/": "", "hf-whisper ghost613/": ""}


def short(m: str) -> str:
    for k, v in SHORT.items():
        m = m.replace(k, v)
    return m


def speech_sheets(wb, bench: list[dict]) -> None:
    """'STT·TTS 비교': 모델별 요약(같은 모델·시험 음성은 마지막 측정만) + 'STT 문장별 비교': 내 목소리 20문장을 모델마다 받아 적은 글"""
    last = {}
    for r in bench:                                   # 같은 모델·시험 음성은 마지막 측정 (설정을 고쳐 다시 잰 것 반영)
        last[(r["kind"], r["model"], r["set"])] = r
    f = lambda v: num(v) if v not in ("", None) else None   # noqa: E731
    stt_models = list(dict.fromkeys(m for k, m, _ in last if k == "stt"))
    rows = []
    for m in stt_models:
        mine, tts, sil = last.get(("stt", m, "mine")), last.get(("stt", m, "tts_supertonic-3")), last.get(("stt", m, "silence"))
        if not mine:
            continue
        rows.append([None, short(m), f(mine["cer"]), f(tts["cer"]) if tts else None, f(mine["term_rate"]), f(tts["term_rate"]) if tts else None,
                     f(sil["hallucinated"]) if sil else None, f(tts["rtf"]) if tts else f(mine["rtf"]), f(mine["gpu_mb"]),
                     SIZE.get(m, ""), mine["detail"], BENCH_NOTE.get(m, "")])
    rows.sort(key=lambda r: r[2])
    for k, r in enumerate(rows, 1):
        r[0] = k
    ws = wb.create_sheet("STT 비교")
    last_row = table(ws, ["순위", "STT 모델", "내 목소리 CER", "TTS 음성 CER", "용어 인식 (내 목소리)", "용어 인식 (TTS)", "무음 환각 (3개 중)",
                          "속도 RTF", "GPU MB", "크기", "설정", "한 줄 평가"], rows,
                     [6, 30, 11, 11, 11, 11, 10, 9, 9, 8, 18, 50],
                     fmt={2: "0.0%", 3: "0.0%", 4: "0%", 5: "0%", 7: "0.00"}, center={0, 2, 3, 4, 5, 6, 7, 8, 9}, filt=False)
    for k, wdt in {2: 12, 3: 12, 4: 12, 5: 12, 6: 11}.items():
        ws.column_dimensions[get_column_letter(LEFT + k)].width = wdt
    for i, r in enumerate(rows, TOP + 1):
        ws.cell(row=i, column=LEFT + 1).font = font(10, True, ACCENT if r[1].startswith("large-v3-turbo") else NAVY)
        ws.cell(row=i, column=LEFT + 2).font = font(10, True, "1E7B34" if r[2] is not None and r[2] < 0.074 else INK)
    # TTS 표 (따로 시트)
    trows = []
    for (k, m, st), r in last.items():
        if k != "tts":
            continue
        tm = os.path.join(os.path.dirname(REC), "bench", "data", f"tts_{m}", "timing.csv")
        voices = sorted({x["voice"] for x in csv.DictReader(open(tm, encoding="utf-8"))}) if os.path.exists(tm) else []
        trows.append([None, m, ", ".join(voices), f(r["n"]), f(r["cer"]), f(r["term_rate"]), f(r["rtf"]), f(r["avg_sec"]), SIZE.get(m, ""),
                      BENCH_NOTE.get(m, "")])
    trows.sort(key=lambda r: r[4])
    for k, r in enumerate(trows, 1):
        r[0] = k
    wt = wb.create_sheet("TTS 비교")
    table(wt, ["순위", "TTS 모델", "목소리", "음성 수", "왕복 CER", "용어 인식", "합성 RTF", "문장당 초", "크기", "한 줄 평가"], trows,
          [6, 22, 14, 8, 11, 11, 9, 9, 8, 60], fmt={4: "0.0%", 5: "0%", 6: "0.00", 7: "0.0"}, center={0, 3, 4, 5, 6, 7, 8}, filt=False)
    for i, r in enumerate(trows, TOP + 1):
        wt.cell(row=i, column=LEFT + 1).font = font(10, True, ACCENT if r[1] == "supertonic-3" else NAVY)
    frame(wt, "TTS 비교", "같은 고정 문장 20개를 후보마다 읽힌 뒤, 만든 음성을 기준 STT(large-v3-turbo)로 다시 받아 적어 정답과 비교 (왕복 CER, 낮을수록 또렷함). "
          "합성 RTF = 합성 시간 ÷ 음성 길이 (1보다 크면 말하는 속도보다 느리게 만듦). 문장당 초 = 한 문장 만드는 데 걸린 평균 시간. "
          "Supertonic은 CPU, 나머지는 GPU(GTX 1660 SUPER, bf16 없음). CosyVoice는 목소리 견본으로 Supertonic 음성을 씀(내 녹음은 쓰지 않음). 주황 = 지금 서비스.", 10)
    frame(ws, "STT 비교", "우리 PC(GTX 1660 SUPER 6GB)에서 후보를 한 번에 하나씩 GPU를 비우고 같은 시험 음성으로 잰 값 (11/12). "
          "시험 음성: 면접 답변체 고정 문장 20개(영어 기술 용어 포함)를 ① 내 목소리로 녹음 20개 ② Supertonic 목소리 4개로 만든 80개, 무음·잡음 3개. "
          "CER = 글자 오류율(띄어쓰기·문장부호 뺌, 'React'처럼 용어를 영어로 적어도 맞게 봄, 낮을수록 좋음). 용어 인식 = 꼭 알아들어야 할 기술 용어 중 맞힌 비율. "
          "RTF = 처리 시간 ÷ 음성 길이(작을수록 빠름). 무음 환각 = 소리 없는 음성에서 글을 지어낸 수. 순위는 내 목소리 CER 순, 주황 = 지금 서비스 모델(보완 포함), 초록 = 지금보다 나음. "
          "같은 모델을 여러 번 쟀으면 마지막 값 (전체 기록은 records/speech_bench.csv).", 12)

    # ---- 문장별: 내 목소리 20개를 모델마다 ----
    root = os.path.join(os.path.dirname(REC), "bench", "out", "stt")
    if not os.path.isdir(root):
        return
    order = {short(m): n for n, m in enumerate(r[1] for r in rows)}
    per = {}
    for d in os.listdir(root):
        fp = os.path.join(root, d, "mine.csv")
        if os.path.exists(fp):
            name = short(d.replace("_", " ", 1).replace("Qwen-", "Qwen/").replace("FunAudioLLM-", "FunAudioLLM/")
                         .replace("moonshine-ai-", "moonshine-ai/").replace("ghost613-", "ghost613/"))
            per[name] = {x["file"]: x for x in csv.DictReader(open(fp, encoding="utf-8-sig"))}
    names = sorted(per, key=lambda n: order.get(n, 99))
    srows = []
    for fname in sorted(next(iter(per.values()))):
        ref = next((v[fname].get("ref") for v in per.values() if fname in v), "")
        first = True
        for n in names:
            x = per[n].get(fname)
            if x:                                     # 정답은 문장마다 첫 줄에만 (반복하면 읽기 어려움)
                srows.append([fname[3:6] if first else None, ref if first else None, n, x["hyp"],
                              int(x["char_err"]) / max(1, int(x["chars"])) if x.get("chars") else None])
                first = False
    w2 = wb.create_sheet("STT 문장별 비교")
    table(w2, ["문장", "정답", "모델", "받아 적은 글", "CER"], srows, [7, 46, 26, 60, 9], fmt={4: "0.0%"}, center={0, 4})
    for i, r in enumerate(srows, TOP + 1):
        if r[0] is not None and i > TOP + 1:          # 문장이 바뀌는 줄 위에 굵은 선
            for k in range(5):
                w2.cell(row=i - 1, column=LEFT + k).border = Border(bottom=Side(style="medium", color=NAVY))
        if r[0] is not None:
            w2.cell(row=i, column=LEFT).font = font(10, True, NAVY)
        if r[4] is not None:
            w2.cell(row=i, column=LEFT + 4).font = font(10, True, "1E7B34" if r[4] == 0 else "B0322A" if r[4] > 0.15 else INK)
    frame(w2, "STT 문장별 비교", "내 목소리로 녹음한 같은 20문장을 모델마다 어떻게 받아 적었는지 (정답과 나란히). CER 0% 초록, 15% 넘음 빨강. "
          "필터로 모델 하나만 골라 그 모델이 받아 적은 글만 볼 수 있습니다.", 5)


def candidate_sheet(wb) -> None:
    """'STT·TTS 후보': 11/11 공개 자료 조사 (우리 PC 측정 전)"""
    wsp = wb.create_sheet("STT·TTS 후보")
    table(wsp, ["구분", "모델", "강한 언어", "지원 언어", "한국어 CER(%)", "크기·속도", "라이선스", "우리 환경 메모", "출처"],
          [list(x) for x in SPEECH], [8, 30, 26, 20, 12, 24, 16, 44, 26], center={0, 4}, fmt={4: "0.00"})
    for i, x in enumerate(SPEECH, TOP + 1):
        c = wsp.cell(row=i, column=LEFT + 1)
        c.font = font(10, True, ACCENT if "지금 사용" in x[1] else NAVY)
        if isinstance(x[4], float):
            wsp.cell(row=i, column=LEFT + 4).font = font(10, True, "1E7B34" if x[4] < 5 else INK)
    frame(wsp, "STT·TTS 후보", "한국어 CER = FLEURS 한국어 시험셋 글자 오류율(낮을수록 좋음), Q8_0 양자화, 공개 비교표(models.handy.computer, 2026-11 확인). "
          "속도 = 실시간 대비 배수(다른 PC 기준). 우리 PC(GPU 6GB)에서는 녹음해 둔 음성으로 다시 재야 합니다. 주황 = 지금 사용 중.", 9)


def check_sheets(wb) -> None:
    """11/12 점검: '판정 일관성'(scripts/judge_consistency.py) · '집단별 점검'(scripts/fairness_check.py)"""
    jc = read_csv("judge_consistency.csv")
    if jc:
        by: dict[str, dict] = {}
        for r in jc:
            d = by.setdefault(r["answer_id"], {"수준": r.get("level", ""), "외부": [], "사내": [], "모델": {}})
            d[r["side"]].append(num(r["score"]) if r["score"] not in ("", "None") else None)
            d["모델"][r["side"]] = r["model"] if r["model"] != "rule" else d["모델"].get(r["side"], "")
        rows = []
        for k, d in by.items():
            ok_e, ok_l = [x for x in d["외부"] if x is not None], [x for x in d["사내"] if x is not None]
            rows.append([k, d["수준"], " / ".join("-" if x is None else f"{x:g}" for x in d["외부"]),
                         (max(ok_e) - min(ok_e)) if ok_e else None, " / ".join("실패" if x is None else f"{x:g}" for x in d["사내"]),
                         (max(ok_l) - min(ok_l)) if ok_l else None, d["사내"].count(None)])
        ws = wb.create_sheet("판정 일관성")
        table(ws, ["답변", "수준", "외부 모델 점수 (3번)", "외부 흔들림", "사내 모델 점수 (3번)", "사내 흔들림", "사내 형식 실패"], rows,
              [12, 8, 22, 11, 22, 11, 11], center={0, 1, 2, 3, 4, 5, 6})
        frame(ws, "판정 일관성", "같은 답변을 같은 모델로 3번, 외부(Claude)·사내(qwen3:4b) 모델로 각각 판정한 점수 (100점 만점). 흔들림 = 최고 - 최저. "
              "답변은 시험용으로 만든 고정 세트(질문 10개 × 좋음·보통·약함, bench/answers.json)로 실제 지원자 답변이 아닙니다. "
              "사내 형식 실패 = 사내 모델이 판정 형식을 지키지 못해 점수 보류(면접은 계속, 담당관 확인)된 횟수. 요약 수치는 '측정 수치' 시트.", 7)
    af = read_csv("affect_bench.csv")                   # 11/12 얼굴·표정·목소리 비교 (bench/run_affect.sh)
    if af:
        affect_sheets(wb, af)
    fr = read_csv("fairness.csv")
    if fr:
        ws = wb.create_sheet("집단별 점검")
        keys = list(fr[0])
        table(ws, keys, [[num(r[k]) if r[k] not in ("",) and k not in ("기준", "집단", "4/5 규칙") else r[k] for k in keys] for r in fr],
              [10, 18, 9, 11, 14, 12, 12, 18], fmt={4: "0%"}, center={2, 3, 4, 5, 6})
        frame(ws, "집단별 점검", "성별·나이대별 1차 AI 추천 비율과 2차 면접 평균 (scripts/fairness_check.py). AI에는 성별·나이를 가려서 보내지만 경력·말투 차이로 "
              "결과가 달라질 수 있어 확인한다. 4/5 규칙: 가장 낮은 집단 비율 ÷ 가장 높은 집단 비율이 0.8보다 작으면 원인을 살펴볼 것. "
              "지금은 시험용 가상 지원자라 숫자 자체는 의미가 없고, 실제 지원자 기록이 쌓이면 같은 방법으로 본다.", len(keys))


# ---------- 얼굴·표정·목소리 비교 (11/12, bench/run_affect.sh → records/affect_bench.csv) ----------
FACE_NOTE = {
    "DeepFace ArcFace (지금 서비스)": "11/16까지 서비스(지금은 InsightFace로 바꿈). 다른 사람은 확실히 막지만 기준(0.45)이 엄격해 시선·표정이 다른 본인 장면 5장 중 1장을 떨어뜨림",
    "DeepFace Facenet512": "지금 DeepFace 그대로 모델 이름·기준값만 바꾸면 됨(새 패키지 없음). 본인 100%·타인 0 — 가장 쉬운 개선",
    "DeepFace SFace": "본인은 거의 통과하지만 가장 닮은 타인과의 차이가 0.04로 빠듯함",
    "DeepFace GhostFaceNet": "다른 사람 4명을 본인으로 잘못 통과시킴 → 부적합",
    "InsightFace buffalo_l": "가장 정확: 본인 100%·타인 0·여유 가장 큼·LFW 같은 사람 97% → 11/16 서비스에 적용 (기준 0.55, 한 번 약 0.4초)",
}
FACE_KO = {"neutral": "무표정", "smile": "미소", "surprise": "놀람", "tense": "긴장", "flustered": "당황", "confident": "자신감",
           "gaze_down": "시선 아래", "spoof": "사진 비추기"}
EMO_KO = {"neutral": "무표정", "happy": "기쁨", "surprise": "놀람", "angry": "화남", "sad": "슬픔", "fear": "두려움", "disgust": "혐오",
          "Neutral": "무표정", "Happiness": "기쁨", "Surprise": "놀람", "Anger": "화남", "Sadness": "슬픔", "Fear": "두려움",
          "Disgust": "혐오", "Contempt": "경멸"}
EXPECT = {"neutral": {"무표정"}, "smile": {"미소", "기쁨"}, "surprise": {"놀람"}, "tense": {"긴장"}, "gaze_down": {"시선 아래"}}


def affect_sheets(wb, af: list[dict]) -> None:
    """'얼굴 비교'(본인 대조 + 사진 비추기 감지) · '표정 비교' · '목소리 톤 비교'(녹음이 있으면). 같은 모델·시험·지표는 마지막 측정만"""
    last = {}
    for r in af:
        last[(r["area"], r["model"], r["test"], r["metric"])] = r
    get = lambda a, m, t, k: next((num(r["value"]) for (aa, mm, tt, kk), r in last.items()   # noqa: E731
                                   if aa == a and mm == m and tt == t and kk.startswith(k)), None)
    models = list(dict.fromkeys(m for (a, m, _, _) in last if a == "본인 대조"))
    if models:
        thr = {m: next((kk.split("기준 ")[1].rstrip(")") for (a, mm, t, kk) in last if mm == m and "기준" in kk), "") for m in models}
        rows = []
        for m in models:
            a = "본인 대조"
            shown = m.replace(" (지금 서비스)", " (11/16까지 서비스)") + (" (지금 서비스)" if m.startswith("InsightFace") else "")
            rows.append([shown, num(thr[m]) if thr[m] else None, get(a, m, "본인 사진 vs 본인 웹캠", "통과율"), get(a, m, "본인 사진 vs 본인 웹캠", "평균"),
                         get(a, m, "본인 사진 vs 본인 웹캠", "최대"), get(a, m, "타인(LFW) vs 본인 사진", "최소"), get(a, m, "타인(LFW) vs 본인 사진", "오통과"),
                         get(a, m, "분리 여유", "타인"), get(a, m, "LFW 같은 사람 쌍", "통과율"), get(a, m, "LFW 다른 사람 쌍", "오통과율"),
                         get(a, m, "속도", "장당"), FACE_NOTE.get(m, "")])
        rows.sort(key=lambda r: -(r[7] if isinstance(r[7], (int, float)) else -9))
        ws = wb.create_sheet("얼굴 비교")
        last_row = table(ws, ["본인 대조 모델", "기준 거리", "본인 웹캠 통과율", "본인 평균 거리", "본인 최대 거리", "타인 최소 거리", "타인 오통과 (120장 중)",
                              "분리 여유", "LFW 같은 사람 통과율", "LFW 다른 사람 오통과율", "장당 초(CPU)", "한 줄 평가"], rows,
                         [26, 9, 11, 10, 10, 10, 11, 9, 12, 12, 9, 52],
                         fmt={1: "0.00", 2: "0%", 3: "0.000", 4: "0.000", 5: "0.000", 7: "0.000", 8: "0%", 9: "0%", 10: "0.00"},
                         center=set(range(1, 11)), filt=False)
        for i, r in enumerate(rows, TOP + 1):
            ws.cell(row=i, column=LEFT).font = font(10, True, ACCENT if "(지금 서비스)" in r[0] else NAVY)
            if isinstance(r[2], (int, float)):
                ws.cell(row=i, column=LEFT + 2).font = font(10, True, "1E7B34" if r[2] >= 0.999 else "B0322A" if r[2] < 0.9 else INK)
            if isinstance(r[6], (int, float)) and r[6] > 0:
                ws.cell(row=i, column=LEFT + 6).font = font(10, True, "B0322A")
            if isinstance(r[7], (int, float)):
                ws.cell(row=i, column=LEFT + 7).font = font(10, True, "1E7B34" if r[7] > 0.2 else "B0322A" if r[7] < 0 else INK)
        sp = [(t, get("대리 응시 감지", m, t, "")) for (a, m, t, _) in last if a == "대리 응시 감지"]
        if sp:
            t0 = last_row + 3
            ws.cell(row=t0 - 1, column=LEFT, value="사진 비추기(대리 응시) 감지 — DeepFace MiniFASNet (ONNX)").font = font(12, True, NAVY)
            keep = {k: ws.column_dimensions[get_column_letter(LEFT + k)].width for k in range(2)}
            table(ws, ["시험", "결과"], [["실제 얼굴 → 진짜로 본 비율" if "실제" in t else "휴대폰 화면 속 사진 → 가짜로 잡은 비율", v] for t, v in sp],
                  [26, 9], fmt={1: "0%"}, center={1}, top=t0, filt=False)
            for k, w in keep.items():                    # 위 표의 칸 너비는 그대로
                ws.column_dimensions[get_column_letter(LEFT + k)].width = max(w or 0, ws.column_dimensions[get_column_letter(LEFT + k)].width or 0)
        ws.freeze_panes = ws.cell(row=TOP + 1, column=LEFT + 1)
        frame(ws, "얼굴 비교 (본인 확인)", "증명사진(본인)과 웹캠 장면 35장(무표정·미소·놀람·긴장·당황·자신감·시선 아래), 다른 사람 사진 LFW 60명 × 2장으로 비교 (11/12). "
              "거리 = 코사인 거리(작을수록 같은 사람). 기준 거리 이하면 통과: ArcFace는 서비스 값 0.45, 나머지는 각 모델 기본값. "
              "분리 여유 = 타인 최소 거리 - 본인 최대 거리 (0보다 크면 기준값 하나로 본인·타인이 완전히 나뉨, 클수록 안전). "
              "LFW 쌍 = 다른 사람들에게도 통하는지(같은 사람 60쌍·다른 사람 59쌍). 얼굴 찾기: DeepFace는 서비스와 같은 YuNet, InsightFace는 자체 SCRFD. "
              "주황 = 지금 서비스(11/16부터 InsightFace, 기준 0.55로 운영), 초록 = 좋음, 빨강 = 문제.", 12)

    ex_models = list(dict.fromkeys(m for (a, m, _, _) in last if a == "표정"))
    if ex_models:
        labels = list(dict.fromkeys(t for (a, _, t, _) in last if a == "표정"))
        order = [k for k in FACE_KO if k in labels]
        rows = []
        for t in order:
            row = [FACE_KO[t]]
            for m in ex_models:
                r = next((r for (a, mm, tt, _), r in last.items() if a == "표정" and mm == m and tt == t), None)
                v = EMO_KO.get(r["value"], r["value"]) if r else ""
                dist = " · ".join(f"{EMO_KO.get(x.rsplit(' ', 1)[0], x.rsplit(' ', 1)[0])} {x.rsplit(' ', 1)[1]}" for x in r["note"].split(" · ")) if r and r["note"] else ""
                ok = "✓ " if v in EXPECT.get(t, set()) else ""
                row += [ok + v, dist]
            rows.append(row)
        heads = ["지은 표정"]
        for m in ex_models:
            heads += [m.split(" (")[0], "5장 결과"]
        ws = wb.create_sheet("표정 비교")
        table(ws, heads, rows, [12] + [16, 26] * len(ex_models), center={0} | {1 + 2 * k for k in range(len(ex_models))}, filt=False)
        for i, r in enumerate(rows, TOP + 1):
            for k in range(len(ex_models)):
                c = ws.cell(row=i, column=LEFT + 1 + 2 * k)
                c.font = font(10, True, "1E7B34" if str(r[1 + 2 * k]).startswith("✓") else INK)
        frame(ws, "표정 비교", "같은 사람이 일부러 지은 표정을 5장씩 찍어 모델마다 무엇으로 읽는지 비교 (11/12). ✓ = 맞게 읽음 (무표정·미소·놀람·긴장·시선 아래만 정답이 있음). "
              "당황·자신감은 어느 모델도 직접 내는 결과가 아니라 무엇으로 읽는지만 본다. 지금 규칙 = 면접 화면이 쓰는 MediaPipe 얼굴 계수 기준(web/lib/face.ts). "
              "HSEmotion 8가지·DeepFace 7가지는 영문 감정 이름을 한국어로 옮김. 표정은 점수에 넣지 않고 관리자 리포트에 표기만 한다.", len(heads))

    vo = [(k, r) for k, r in last.items() if k[0] in ("목소리 톤", "말 끊김·더듬음")]
    if vo:
        rows = [[a, m, t, num(r["n"]) if r["n"] else None, kk, r["value"], r["note"]] for (a, m, t, kk), r in vo]
        ws = wb.create_sheet("목소리 톤 비교")
        table(ws, ["분야", "모델", "말투", "개수", "지표", "결과", "자세히"], rows, [12, 30, 10, 7, 20, 18, 50], center={2, 3})
        frame(ws, "목소리 톤 비교", "같은 문장 5개를 보통·작게·자신 있게·망설이며·더듬으며로 녹음한 25개를 모델마다 어떻게 읽는지 (11/12). 목소리 톤은 점수에 넣지 않는다.", 7)

def read_csv(name: str) -> list[dict]:
    p = os.path.join(REC, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return float(v) if "." in str(v) else int(v)
    except (TypeError, ValueError):
        return v


def when(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def main() -> int:
    wb = Workbook()
    runs, meas = read_csv("test_runs.csv"), read_csv("measurements.csv")

    # ---- 시험 기록 ----
    ws = wb.active
    ws.title = "시험 기록"
    rows = [[when(r["일시"]), r["종류"], r["범위"], num(r["통과"]), num(r["실패"]), num(r["소요_초"]) if r["소요_초"] else None,
             r["모드"] or "-", r["모델"] or "-", r["비고"]] for r in runs]
    last_run = table(ws, ["일시", "종류", "범위", "통과", "실패", "소요(초)", "모드", "모델", "비고"], rows,
                     [18, 9, 8, 8, 8, 10, 28, 30, 22], fmt={0: "yyyy-mm-dd hh:mm", 5: "0.0"}, center={1, 2, 3, 4, 5})
    for i in range(TOP + 1, last_run + 1):           # 실패가 있는 줄은 실패 칸을 빨갛게
        c = ws.cell(row=i, column=LEFT + 4)
        if isinstance(c.value, int) and c.value > 0:
            c.font = font(10, True, "C0392B")
    frame(ws, "시험 기록", "tasks.ps1 test·e2e를 돌릴 때마다 자동으로 한 줄씩 쌓입니다. 11/4~11/11은 대화 기록의 시험 출력에서 복원했습니다. "
          "범위: 전체 = 그때 있던 시험을 모두 돌린 실행, 일부 = 고친 부분만 돌린 실행. 빨간 실패 숫자는 고치기 전 실행입니다.", 9)

    # ---- 모델·버전 ----
    wm = wb.create_sheet("모델·버전")
    table(wm, ["구분", "용도", "모델", "버전·설정", "실행 위치", "비고"], [list(m) for m in MODELS], [11, 38, 30, 36, 18, 32], center={0})
    for i in range(TOP + 1, TOP + 1 + len(MODELS)):
        wm.cell(row=i, column=LEFT + 2).font = font(10, True, NAVY)
    frame(wm, "모델·버전", "실제 모드(MODULE·STT·TTS·FACE = real)에서 쓰는 모델과 도구. 버전은 고정 파일(requirements)에서 읽습니다.", 6)

    # ---- 측정 수치 ----
    wq = wb.create_sheet("측정 수치")
    table(wq, ["일시", "종류", "항목", "값", "비고"], [[when(r["일시"]), r["종류"], r["항목"], num(r["값"]), r["비고"]] for r in meas],
          [18, 12, 30, 22, 52], fmt={0: "yyyy-mm-dd hh:mm"}, center={1, 3})
    for i in range(TOP + 1, TOP + 1 + len(meas)):
        wq.cell(row=i, column=LEFT + 3).font = font(10, True, NAVY)
    frame(wq, "측정 수치", "부하 시험·무중단 반영·얼굴 대조·자원 사용량 등 직접 잰 값. 추가: python scripts/record_run.py note 종류 항목 값 비고", 5)

    # ---- 고친 문제 ----
    wf = wb.create_sheet("고친 문제")
    table(wf, ["날짜", "분류", "문제", "원인", "고친 방법", "확인"], [list(f) for f in FIXES], [12, 10, 36, 44, 50, 30], center={0, 1})
    for i in range(TOP + 1, TOP + 1 + len(FIXES)):
        wf.cell(row=i, column=LEFT + 2).font = font(10, True, INK)
    frame(wf, "고친 문제", "시험·직접 확인 중 찾은 문제와 원인, 고친 방법, 확인 결과.", 6)

    # ---- 날짜별 진행 (records/worklog.py) ----
    import importlib.util
    spec = importlib.util.spec_from_file_location("worklog", os.path.join(REC, "worklog.py"))
    wl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wl)
    wd = wb.create_sheet("날짜별 진행", 1)
    log_rows = [[datetime.strptime(d, "%Y-%m-%d"), *rest] for d, *rest in wl.WORKLOG]
    table(wd, ["날짜", "분야", "진행한 일", "결과", "추가한 것", "빼거나 바꾼 것"], log_rows,
          [12, 11, 52, 28, 34, 30], fmt={0: "mm-dd (aaa)"}, center={0, 1}, filt=True)
    prev = None
    for i, r in enumerate(log_rows, TOP + 1):
        day_cell = wd.cell(row=i, column=LEFT)
        if r[0] == prev:                              # 같은 날은 날짜를 한 번만 (읽기 쉽게)
            day_cell.font = font(10, color=GRAY)
            day_cell.number_format = ";;;"
        else:
            day_cell.font = font(10, True, NAVY)
            if prev is not None:                      # 날짜가 바뀌는 줄 위에 굵은 선
                for k in range(6):
                    c = wd.cell(row=i - 1, column=LEFT + k)
                    c.border = Border(bottom=Side(style="medium", color=NAVY))
        prev = r[0]
        if r[5]:
            wd.cell(row=i, column=LEFT + 5).font = font(10, color="A3410C")
        if r[4]:
            wd.cell(row=i, column=LEFT + 4).font = font(10, color="1E6B34")
    frame(wd, "날짜별 진행", "날짜마다 무엇을 했고 결과가 어땠는지, 무엇을 더하고(초록) 빼거나 바꿨는지(주황). 11/4~11/11은 대화 기록에서 정리. "
          "새 진행은 records/worklog.py에 한 줄씩 더하고 엑셀을 다시 만듭니다.", 6)

    candidate_sheet(wb)
    check_sheets(wb)

    # ---- STT·TTS 비교 (bench/: 같은 고정 문장으로 후보를 하나씩, records/speech_bench.csv, 11/12) ----
    bench = read_csv("speech_bench.csv")
    if bench:
        speech_sheets(wb, bench)

    # ---- 면접 기록 ----
    wi = wb.create_sheet("면접 기록")
    irows = []
    for path in sorted(glob.glob(os.path.join(REC, "interviews", "*.json"))):
        for s in json.load(open(path, encoding="utf-8")):
            total = (s.get("evaluation") or {}).get("total_score")
            for q in s["questions"]:
                irows.append([os.path.basename(path)[:13], s["id"], s["llm_eval_model"], q["ask_order"], "기술" if q["kind"] == "tech" else "비기술",
                              q["question_text"], q["stt_text"] or "(무응답)", num(q["answer_sec"]) if q["answer_sec"] is not None else None,
                              num(q["score"]) if q["score"] is not None else None, q["latency_ms"], num(total) if total is not None else None])
    head = ["저장", "응시", "판정 모델", "번호", "종류", "질문", "STT 인식 글", "답변(초)", "점수", "판정(ms)", "총점"]
    caps = [14, 7, 18, 7, 8, 46, 46, 9, 7, 9, 7]
    if irows:
        table(wi, head, irows, caps, center={1, 3, 4, 7, 8, 9, 10})
    else:
        table(wi, head, [], [max(c, dw(h) + 4) for c, h in zip([14, 7, 18, 7, 8, 30, 30, 9, 7, 9, 7], head)], filt=False)
        wi.merge_cells(start_row=TOP + 1, start_column=LEFT, end_row=TOP + 1, end_column=LEFT + len(head) - 1)
        c = wi.cell(row=TOP + 1, column=LEFT, value="아직 없음 — DB 초기화(tasks.ps1 seed) 전에 직접 응시한 면접이 records/interviews/에 자동 저장되고, 엑셀을 다시 만들면 여기에 들어옵니다.")
        c.font, c.alignment = font(10, color=GRAY), Alignment(horizontal="center", vertical="center")
        wi.row_dimensions[TOP + 1].height = 34
    frame(wi, "면접 기록", "직접 응시한 AI 화상면접: 물어본 순서대로 질문·STT 인식 글·점수·판정 지연. 이름은 담지 않습니다.", len(head))

    # ---- 요약 ----
    w = wb.create_sheet("요약", 0)
    wb.move_sheet("날짜별 진행", offset=1 - wb.sheetnames.index("날짜별 진행"))   # 요약 바로 다음
    cols = 7
    for k, wd in enumerate([17, 17, 17, 17, 17, 17, 56]):
        w.column_dimensions[get_column_letter(LEFT + k)].width = wd
    frame(w, "6.1 실시간 AI 화상면접 — 개발·시험 기록",
          "가상 회사 '새벽소프트' 채용 시스템: 채용 공고 → 지원 → 1차 서류(AI 추천) → 코딩 테스트 → AI 화상면접 10문항 → 관리자 확정 → 최종 합격 발표", cols)
    n = TOP + len(runs)
    D, R, S, P, F = (f"'시험 기록'!${c}${TOP + 1}:${c}${n}" for c in "BCDEF")
    last_of = lambda k: f'IFERROR(LOOKUP(2,1/(({R}="{k}")*({S}="전체")),{P}),"-")'   # noqa: E731
    cards = [("시험 실행", f"=COUNTA({D})", "회"), ("백엔드 시험 · 최근", "=" + last_of("pytest"), "개 통과"),
             ("화면 흐름 E2E · 최근", "=" + last_of("e2e"), "개 통과"), ("화면 단위 시험 · 최근", "=" + last_of("vitest"), "개 통과"),
             ("모델·도구", f"=COUNTA('모델·버전'!D{TOP + 1}:D{TOP + len(MODELS)})", "개"),
             ("고친 문제", f"=COUNTA('고친 문제'!D{TOP + 1}:D{TOP + len(FIXES)})", "건"),
             ("기록 기간", f"=TEXT(MIN({D}),\"yyyy-mm-dd\")&\"  ~  \"&TEXT(MAX({D}),\"mm-dd\")", "시험 기록 시트의 첫·마지막 실행")]
    side = Side(style="thin", color=LINE)
    for k, (label, f, unit) in enumerate(cards):
        col = LEFT + k
        for r, (v, ft, h) in enumerate([(label, font(9, True, GRAY), 22), (f, font(20 if k < 6 else 15, True, NAVY), 36), (unit, font(9, color=GRAY), 20)], 6):
            c = w.cell(row=r, column=col, value=v)
            c.font, c.fill, c.alignment = ft, PatternFill("solid", fgColor=CARD), Alignment(horizontal="center", vertical="center")
            c.border = Border(left=side, right=side, top=side if r == 6 else None, bottom=side if r == 8 else None)
            w.row_dimensions[r].height = h

    def section(row: int, text: str) -> None:
        w.cell(row=row, column=LEFT, value=text).font = font(12, True, NAVY)
        for k in range(cols):
            w.cell(row=row, column=LEFT + k).border = Border(bottom=Side(style="thin", color=ACCENT))
        w.row_dimensions[row].height = 26
        w.row_dimensions[row - 1].height = 12

    section(10, "시험 종류별 결과")
    kinds = [("pytest", "백엔드·DB 규칙 (API, 면접 흐름, 1차·최종 결정, 권한)"),
             ("vitest", "화면 로직 단위 (침묵·타이머·탭 이탈·얼굴 신호)"),
             ("e2e", "Playwright 화면 전체 흐름 (가입 → 응시 → 10문항 → 확정 → 발표)")]
    hdr = ["시험", "실행 수", "전체 실행 수", "최근 전체 통과", "최고 통과 수", "실패 0 비율", "무엇을 확인하나"]
    for k, h in enumerate(hdr):
        c = w.cell(row=11, column=LEFT + k, value=h)
        c.font, c.fill, c.alignment = font(10, True, "FFFFFF"), PatternFill("solid", fgColor=NAVY), Alignment(horizontal="center", vertical="center")
    w.row_dimensions[11].height = 24
    for i, (kname, desc) in enumerate(kinds, 12):
        a = f"{get_column_letter(LEFT)}{i}"
        cnt = f"{get_column_letter(LEFT + 2)}{i}"
        vals = [kname, f"=COUNTIF({R},{a})", f'=COUNTIFS({R},{a},{S},"전체")', "=" + last_of(kname),
                f'=IFERROR(_xlfn.MAXIFS({P},{R},{a}),"-")', f'=IF({cnt}=0,"-",COUNTIFS({R},{a},{S},"전체",{F},0)/{cnt})', desc]
        for k, v in enumerate(vals):
            c = w.cell(row=i, column=LEFT + k, value=v)
            c.font = font(10, k == 0, NAVY if k == 0 else INK)
            c.alignment = Alignment(horizontal="left" if k == 6 else "center", vertical="center", wrap_text=True, indent=1 if k == 6 else 0)
            c.border = Border(bottom=Side(style="thin", color=LINE))
            if i % 2:
                c.fill = PatternFill("solid", fgColor=BAND)
        w.cell(row=i, column=LEFT + 5).number_format = "0%"
        w.row_dimensions[i].height = 26

    section(16, "주요 측정")
    pick: dict[str, dict] = {}
    for m in meas:                                    # 항목마다 가장 최근 값 하나 (순서는 처음 나온 순)
        if m["종류"] in ("부하 시험", "무중단 반영", "얼굴 대조", "자원", "복구"):
            pick[m["항목"]] = m
    hl = list(pick.values())
    for i, m in enumerate(hl, 17):
        w.merge_cells(start_row=i, start_column=LEFT + 1, end_row=i, end_column=LEFT + 2)
        w.merge_cells(start_row=i, start_column=LEFT + 3, end_row=i, end_column=LEFT + 4)
        w.merge_cells(start_row=i, start_column=LEFT + 5, end_row=i, end_column=LEFT + 6)
        for k, (v, ft) in {0: (m["종류"], font(10, True, GRAY)), 1: (m["항목"], font(10)), 3: (m["값"], font(11, True, NAVY)),
                           5: (m["비고"], font(9, color=GRAY))}.items():
            c = w.cell(row=i, column=LEFT + k, value=num(v) if k == 3 else v)
            c.font = ft
            if k == 3 and isinstance(c.value, float):
                c.number_format = "0.00"
        for k in range(cols):
            c = w.cell(row=i, column=LEFT + k)
            c.alignment = Alignment(vertical="center", wrap_text=True, indent=1, horizontal="center" if k in (3, 4) else "left")
            c.border = Border(bottom=Side(style="thin", color=LINE))
        w.row_dimensions[i].height = max(24, 15 * max(lines_for(m["항목"], 34), lines_for(m["비고"], 63 * 1.1)) + 8)
    r0 = 17 + len(hl) + 1
    section(r0, "읽는 법")
    notes = ["시험 기록은 tasks.ps1 test·e2e를 돌릴 때마다 자동으로 쌓이고, 11/4~11/11은 대화 기록에서 복원했습니다.",
             "실패가 있는 실행은 고치기 전입니다. 원인을 고친 뒤 같은 시험을 다시 통과시켰습니다 (고친 문제 시트).",
             "부하 시험은 가짜 모듈로 서버·DB·작업자 처리량만 쟀습니다. 실제 50명이면 GPU(6GB)와 Claude 사용 한도가 병목이 될 수 있습니다.",
             "엑셀 다시 만들기: python scripts/build_portfolio.py  (열 때 수식이 다시 계산됩니다)"]
    for j, t in enumerate(notes, r0 + 1):
        w.merge_cells(start_row=j, start_column=LEFT, end_row=j, end_column=LEFT + cols - 1)
        c = w.cell(row=j, column=LEFT, value="•  " + t)
        c.font, c.alignment = font(10), Alignment(vertical="center", wrap_text=True, indent=1)
        w.row_dimensions[j].height = 24
    w.sheet_view.zoomScale = 100

    wb.calculation.fullCalcOnLoad = True        # 열 때 수식 다시 계산
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    wb.save(OUT)
    print(f"저장: {OUT} (시험 {len(runs)}건 · 측정 {len(meas)}건 · 고친 문제 {len(FIXES)}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
