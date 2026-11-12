#!/usr/bin/env bash
# STT·TTS 후보 전부 차례로 (11/12). GPU 6GB라 한 번에 한 모델. 면접 STT·Ollama는 미리 내려 둔다.
#   bash bench/run_candidates.sh   (프로젝트 폴더에서, Git Bash)
cd "$(dirname "$0")/.." || exit 1
B="$(pwd -W)/bench"; R="$(pwd -W)/records"
SETS="mine,tts_supertonic-3"
run() {   # 이미지 · 명령 (실패해도 다음 후보로)
  local img=$1; shift
  echo "===== $img $*"
  MSYS_NO_PATHCONV=1 docker run --rm --gpus all -v "$B:/bench" -v "$R:/records" -v bench_models:/models "$img" "$@" || echo "!!!!! 실패: $img $*"
}
# ---- STT 후보 ----
run bench-hf     python /bench/stt_bench.py --engine hf-whisper --model ghost613/whisper-large-v3-turbo-korean --sets $SETS --note "후보 2단계"
run bench-hf     python /bench/stt_bench.py --engine moonshine  --model moonshine-ai/moonshine-base-ko        --sets $SETS --note "후보 2단계"
run bench-qwenasr python /bench/stt_bench.py --engine qwen-asr   --model Qwen/Qwen3-ASR-0.6B                    --sets $SETS --note "후보 2단계"
run bench-qwenasr python /bench/stt_bench.py --engine qwen-asr   --model Qwen/Qwen3-ASR-1.7B                    --sets $SETS --note "후보 2단계"
run bench-funasr python /bench/stt_bench.py --engine sensevoice --model FunAudioLLM/SenseVoiceSmall             --sets $SETS --note "후보 2단계"
# ---- TTS 후보: 음성 만들기 ----
run bench-qwentts python /bench/tts_bench.py --engine qwen-tts
run bench-melo python /bench/tts_bench.py --engine melo
run bench-cosy python /bench/tts_bench.py --engine cosyvoice
# ---- TTS 왕복 CER: 기준 STT(large-v3-turbo, 서비스 이미지)로 받아 적기 ----
for s in tts_qwen3-tts-0.6b tts_melotts-kr tts_cosyvoice2-0.5b; do
  [ -f "bench/data/$s/timing.csv" ] || continue
  echo "===== 왕복 $s"
  MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -v "$B:/bench" -v "$R:/records" stt \
    python /bench/stt_bench.py --engine faster-whisper --model large-v3-turbo --sets $s --skip-silence --note "TTS 후보 왕복"
done
echo "===== 끝"
