#!/usr/bin/env bash
# 첫 실행에서 설정 문제로 실패·잘림이 난 두 후보 다시 (11/12): whisper-turbo-korean(생성 설정), moonshine-ko(생성 길이)
cd "$(dirname "$0")/.." || exit 1
B="$(pwd -W)/bench"; R="$(pwd -W)/records"
for m in "hf-whisper ghost613/whisper-large-v3-turbo-korean" "moonshine moonshine-ai/moonshine-base-ko"; do
  set -- $m
  echo "===== $1 $2"
  MSYS_NO_PATHCONV=1 docker run --rm --gpus all -v "$B:/bench" -v "$R:/records" -v bench_models:/models bench-hf \
    python /bench/stt_bench.py --engine "$1" --model "$2" --sets mine,tts_supertonic-3 --note "후보 2단계 (설정 고쳐 다시)" || echo "!!!!! 실패: $m"
done
echo "===== 끝"
