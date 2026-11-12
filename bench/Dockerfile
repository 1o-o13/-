# STT·TTS 후보 비교 전용 이미지 (11/12). 서비스 이미지·고정 버전 파일(requirements/*)과 따로 둔다 — 비교가 끝나면 지워도 된다.
# 후보마다 패키지가 서로 충돌해서(torch·transformers 버전) 같은 바탕 위에 후보별 단계(target)를 나눈다.
#   docker build -f bench/Dockerfile --target hf -t bench-hf bench     (whisper-turbo-korean · moonshine-ko)
#   ... --target qwenasr (Qwen3-ASR) · qwentts (Qwen3-TTS) — 둘이 transformers 버전을 다르게 고정해서 따로   --target funasr (SenseVoiceSmall)
#   ... --target melo   (MeloTTS 한국어)          --target cosy   (CosyVoice2-0.5B)
# 설치된 버전은 빌드 뒤 bench/locks/<target>.txt로 남긴다 (pip freeze)
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime AS base
RUN apt-get update && apt-get install -y --no-install-recommends git git-lfs ffmpeg sox libsox-dev build-essential \
    && rm -rf /var/lib/apt/lists/*
ENV HF_HOME=/models MODELSCOPE_CACHE=/models/modelscope PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install soundfile librosa

FROM base AS hf
RUN pip install "transformers==4.57.1" accelerate

FROM base AS qwenasr
RUN pip install qwen-asr

FROM base AS qwentts
RUN pip install qwen-tts

FROM base AS funasr
RUN pip install funasr modelscope

FROM base AS melo
RUN git clone --depth 1 https://github.com/myshell-ai/MeloTTS /opt/melo && pip install -e /opt/melo && python -m unidic download

FROM base AS cosy
RUN git clone --recursive --depth 1 https://github.com/FunAudioLLM/CosyVoice /opt/cosy \
    && grep -v -i -E "^(torch|torchaudio)==" /opt/cosy/requirements.txt > /tmp/req.txt     && echo "setuptools<81" > /tmp/c.txt && PIP_CONSTRAINT=/tmp/c.txt pip install -r /tmp/req.txt   # 옛 setup.py가 pkg_resources를 씀     && pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124   # 요구 목록이 torch 2.3.1로 내려 transformers 가져오기가 실패 → 바탕 이미지 버전으로
# 위 RUN 줄 안의 '#' 뒤는 셸 주석이 되어 torch 2.5.1 설치가 실행되지 않았다 (11/12) → 따로 한 번 더 (위 단계는 캐시를 쓰려고 그대로 둠)
RUN pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
# deepspeed(학습용)가 있으면 transformers가 가져오다 CUDA_HOME이 없다며 멈춤 → 합성만 하니 뺀다
RUN pip uninstall -y deepspeed
ENV PYTHONPATH=/opt/cosy:/opt/cosy/third_party/Matcha-TTS

# 11/12 얼굴·표정 비교 (CPU): InsightFace(buffalo_l) · HSEmotion · MediaPipe(브라우저와 같은 얼굴 계수). DeepFace는 서비스 face 이미지를 그대로 쓴다
FROM python:3.11-slim AS vision
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libglib2.0-0 libgl1 libegl1 libgles2 && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 INSIGHTFACE_HOME=/models/insightface
RUN pip install insightface onnxruntime hsemotion-onnx mediapipe opencv-python-headless
# DeepFace 위조 감지(MiniFASNet)의 ONNX 판만 쓴다: 서비스와 같은 0.0.103을 의존성 없이 (TensorFlow 없이)
RUN pip install deepface==0.0.103 --no-deps && pip install requests gdown tqdm
ENV DEEPFACE_HOME=/models/deepface
