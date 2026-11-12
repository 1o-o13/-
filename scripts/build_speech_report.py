"""팀 공유용 STT·TTS 모델 비교 엑셀 (11/12): 바탕화면 STT_TTS_모델비교.xlsx. PC(호스트)에서 실행.
  python scripts/build_speech_report.py
시트: 결론 · STT 비교 · TTS 비교 · STT 문장별 비교 · 얼굴 비교 · 표정 비교 · 시험 문장 · 후보 조사(공개 자료)
값은 records/speech_bench.csv와 bench/out/stt/*/mine.csv에서 읽는다 (포트폴리오 엑셀과 같은 표·꾸미기를 씀).
"""
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, PatternFill, Side

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench"))
import build_portfolio as bp  # noqa: E402
from sentences import SENTENCES  # noqa: E402

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "STT_TTS_모델비교.xlsx")

# 결론 (측정 결과를 보고 적음. 숫자는 'STT 비교'·'TTS 비교' 시트와 같음)
CONCLUSION = [
    ("측정 환경", "GTX 1660 SUPER 6GB (bf16 없음) · 후보를 한 번에 하나씩, GPU를 비우고 같은 시험 음성으로 · 2026-11-12"),
    ("시험 음성", "면접 답변체 고정 문장 20개(영어 기술 용어 포함) → ① 사람 목소리 녹음 20개 ② Supertonic 목소리 4개 80개 ③ 무음·잡음 3개"),
    ("STT 정확도 1위", "Qwen3-ASR-1.7B — 사람 목소리 CER 4.3%. 단 GPU 4.7GB라 면접 판정 모델(qwen3:4b, 약 4GB)과 6GB GPU에 같이 못 올림"),
    ("STT 이 PC 추천", "지금 모델 large-v3-turbo + 회사·기술 용어 힌트 + 자막류 환각 거르기 — CER 7.4% → 5.8%, 용어 인식 79% → 91%. GPU·속도 그대로, 새 패키지 없음"),
    ("STT 다른 후보", "Qwen3-ASR-0.6B 5.2%(이 PC에서 5배 느림, GPU 합계 6GB 넘음) · large-v3 9.4% · SenseVoice 10.2%(가장 빠름) · Moonshine-ko 18.8% · 한국어 turbo(ghost613) 23.5%"),
    ("더 좋은 서버라면", "GPU 12GB 이상 + bf16 지원(RTX 30·40 이상)이면 Qwen3-ASR-1.7B + 무음 거르기(VAD) + 용어 힌트. 서버에서 bench/로 같은 비교를 다시 돌려 확인"),
    ("TTS 결론", "지금 Supertonic 3 유지 — 가장 또렷함(왕복 CER 5.0%)·CPU로 문장당 3.4초. Qwen3-TTS(36초)·CosyVoice2(14초)는 이 GPU에서 너무 느림, MeloTTS는 빠르지만 한국어 목소리 1종"),
    ("주의할 점", "Whisper 계열은 답변 끝 무음에 '한글자막 by …'·'아멘' 같은 문구를 지어냄 → 거르기 필요. Qwen 등은 VAD 없이 쟀을 때 무음에 '그렇죠.'·'네.'를 지어냄 → VAD 필수"),
    ("한계", "사람 목소리는 1명 20문장 — 실제 지원자(목소리·마이크·말투)는 다를 수 있음. 용어 힌트 목록은 시험 문장보다 넓게 잡았지만 시험 용어도 포함됨"),
    ("얼굴(본인 확인)", "그 전 ArcFace(기준 0.45)는 타인은 확실히 막지만 본인 웹캠 장면 20%를 떨어뜨림. InsightFace가 가장 정확(본인 100%·타인 0·LFW 같은 사람 97%) → 11/16 서비스에 적용(기준 0.55). 사진 비추기는 MiniFASNet이 100% 잡음"),
    ("표정", "지금 규칙(MediaPipe)이 놀람·긴장·시선 아래·무표정을 맞혀 가장 나음. HSEmotion·DeepFace는 엉뚱한 결과가 많고, 당황·자신감은 어느 모델도 구분 못 함 → 점수에 넣지 않고 표기만"),
    ("다시 재는 법", "bench/ 폴더: stt_bench.py(STT) · tts_bench.py(TTS) · Dockerfile(후보별 이미지) · run_candidates.sh(전부 차례로). 결과는 records/speech_bench.csv에 쌓임"),
]


def conclusion_sheet(wb) -> None:
    ws = wb.active
    ws.title = "결론"
    for i, (k, v) in enumerate(CONCLUSION, bp.TOP):
        a = ws.cell(row=i, column=bp.LEFT, value=k)
        b = ws.cell(row=i, column=bp.LEFT + 1, value=v)
        a.font, a.fill = bp.font(11, True, "FFFFFF"), PatternFill("solid", fgColor=bp.NAVY)
        a.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        b.font = bp.font(11, k in ("STT 이 PC 추천", "TTS 결론"), bp.ACCENT if k in ("STT 이 PC 추천", "TTS 결론") else bp.INK)
        b.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
        for c in (a, b):
            c.border = Border(bottom=Side(style="thin", color=bp.LINE))
        ws.row_dimensions[i].height = 18 * bp.lines_for(v, 104) + 12
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 110
    bp.frame(ws, "STT·TTS 모델 비교 결론", "새벽소프트 AI 화상면접(6.1)의 답변 인식(STT)·질문 음성(TTS) 모델을 우리 PC에서 같은 음성으로 비교한 결과 요약. "
             "자세한 숫자는 다음 시트들에 있습니다.", 2)


def sentence_sheet(wb) -> None:
    ws = wb.create_sheet("시험 문장")
    rows = [[sid, {"s": "비기술(경험·강점)", "t": "기술(영어 용어)", "l": "긴 답변(30초 안팎)"}[sid[0]], text,
             " · ".join(t[0] for t in terms) or "-"] for sid, text, terms in SENTENCES]
    bp.table(ws, ["번호", "종류", "정답 문장", "꼭 알아들어야 할 용어"], rows, [8, 18, 80, 40], center={0, 1})
    bp.frame(ws, "시험 문장", "모든 모델에 같은 20문장을 썼습니다 (bench/sentences.py). 용어는 영어로 적어도 맞게 봅니다 (예: '레디스' = 'Redis').", 4)


def main() -> int:
    bench = bp.read_csv("speech_bench.csv")
    if not bench:
        print("records/speech_bench.csv가 없습니다")
        return 1
    wb = Workbook()
    conclusion_sheet(wb)
    bp.speech_sheets(wb, bench)
    af = bp.read_csv("affect_bench.csv")             # 11/12 얼굴·표정(·목소리 톤) 비교
    if af:
        bp.affect_sheets(wb, af)
    sentence_sheet(wb)
    bp.candidate_sheet(wb)
    wb["STT·TTS 후보"].title = "후보 조사(공개 자료)"
    wb.save(OUT)
    print(f"저장: {OUT} (시트 {', '.join(wb.sheetnames)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
