#!/usr/bin/env bash
# 첫 실행에서 실패한 TTS 후보 2개 다시 (11/12): Qwen3-TTS(fp32로), CosyVoice2(torch 버전 고침) → 기준 STT로 왕복 CER
cd "$(dirname "$0")/.." || exit 1
B="$(pwd -W)/bench"; R="$(pwd -W)/records"
for x in "bench-qwentts qwen-tts" "bench-cosy cosyvoice"; do
  set -- $x
  echo "===== $1 $2"
  MSYS_NO_PATHCONV=1 docker run --rm --gpus all -v "$B:/bench" -v "$R:/records" -v bench_models:/models "$1" \
    python /bench/tts_bench.py --engine "$2" || echo "!!!!! 실패: $x"
done
for s in tts_qwen3-tts-0.6b tts_cosyvoice2-0.5b; do
  [ -f "bench/data/$s/timing.csv" ] || continue
  echo "===== 왕복 $s"
  MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -v "$B:/bench" -v "$R:/records" stt \
    python /bench/stt_bench.py --engine faster-whisper --model large-v3-turbo --sets $s --skip-silence --note "TTS 후보 왕복"
done
echo "===== 끝"
