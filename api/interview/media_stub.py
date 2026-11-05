"""음성·얼굴 처리 가짜 (GPU 없이 돌릴 때). STT_MODE=stub이면 transcribe를(real이면 stt 컨테이너, worker/tasks.py),
FACE_MODE=stub이면 face_distance를 쓴다(real이면 face 컨테이너 InsightFace, api/face.py)."""

STT_MODEL = "stub"
FACE_MODEL = "stub"


SILENT_RATIO = 0.9   # 임시: 녹음의 이만큼 이상이 침묵이면 말을 안 한 것으로 본다 (화면이 잰 3초 이상 침묵 비율)


def transcribe(audio: bytes, key_points: list[str], level: str | None, silence_ratio: float = 0.0) -> str | None:
    """업로드 음성 대신 질문의 key_points를 시험용 수준만큼 넣은 고정 답변. 빈 음성이거나 거의 침묵이면 무응답(None).
    상 = 모두, 중 = 첫 번째만, 하 = 없음 (fake_modules 판정으로 85·55·20점)"""
    if not audio or silence_ratio >= SILENT_RATIO:
        return None
    if level == "상":
        return ". ".join(key_points) + " 순서로 설명하겠습니다."
    if level == "중":
        return key_points[0] + " 위주로 말씀드리겠습니다."
    return "잘 모르겠습니다. 경험이 부족합니다."


def face_distance(frame: bytes, photo_key: str | None) -> float | None:
    """이력서 사진 ↔ 웹캠 프레임 코사인 거리. 가짜는 늘 일치 구간(0.33). 프레임은 저장하지 않는다."""
    return 0.33
