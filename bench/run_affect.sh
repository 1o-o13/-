#!/usr/bin/env bash
# 얼굴·표정·목소리 비교 전부 차례로 (11/12). 녹음(bench/data/style)·촬영(bench/data/face)을 마친 뒤에
#   bash bench/run_affect.sh
cd "$(dirname "$0")/.." || exit 1
B="$(pwd -W)/bench"; R="$(pwd -W)/records"
export MSYS_NO_PATHCONV=1
echo "===== DeepFace (서비스 얼굴 이미지)"
docker compose run --rm --no-deps -v "$B:/bench" -v "$R:/records" -v bench_models:/bm -e DEEPFACE_HOME=/bm/deepface face python /bench/face_deepface.py || echo "!!!!! 실패 deepface"
echo "===== InsightFace · 위조 감지 · 표정 (bench-vision)"
docker run --rm -v "$B:/bench" -v "$R:/records" -v bench_models:/models bench-vision python /bench/face_vision.py || echo "!!!!! 실패 vision"
echo "===== 목소리: 지금 규칙 · 말 끊김 (stt 이미지)"
for e in rules disfluency; do
  docker compose run --rm --no-deps -v "$B:/bench" -v "$R:/records" stt sh -c "cd /app && python /bench/voice_affect.py --engine $e" || echo "!!!!! 실패 $e"
done
echo "===== 목소리: emotion2vec · SenseVoice (bench-funasr)"
for e in emotion2vec sensevoice; do
  docker run --rm --gpus all -v "$B:/bench" -v "$R:/records" -v bench_models:/models bench-funasr python /bench/voice_affect.py --engine $e || echo "!!!!! 실패 $e"
done
echo "===== 끝"
