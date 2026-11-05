// 브라우저 카메라·마이크. 영상은 브라우저 밖으로 보내지 않는다 (본인 확인 프레임 1장만 예외). 녹음은 음성 트랙만.

export function openMedia(): Promise<MediaStream> {
  // 해상도를 높여 뒤쪽 작은 얼굴도 잡히게 (기본 640×480이면 뒤쪽 사람이 너무 작음)
  return navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: true });
}

/** 마이크 음량(RMS 0~1)을 읽는다 */
export function levelMeter(stream: MediaStream) {
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  return {
    read(): number {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      return Math.sqrt(sum / buf.length);
    },
    /** 새로고침 직후처럼 사용자 조작 전이면 브라우저가 소리 처리를 멈춰 둔다 → 버튼으로 다시 켠다 */
    suspended: () => ctx.state === "suspended",
    resume: () => ctx.resume(),
    close: () => void ctx.close(),
  };
}

/** 음성만 녹음. stop()이 녹음 파일을 돌려준다 */
export function startRecording(stream: MediaStream) {
  const rec = new MediaRecorder(new MediaStream(stream.getAudioTracks()));
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => chunks.push(e.data);
  rec.start();
  return {
    stop: () =>
      new Promise<Blob>((done) => {
        rec.onstop = () => done(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
        rec.stop();
      }),
  };
}

/** 본인 확인용 프레임 1장 (서버는 거리만 남기고 사진은 저장하지 않음) */
export function snapshot(video: HTMLVideoElement): Promise<Blob> {
  const c = document.createElement("canvas");
  c.width = video.videoWidth;
  c.height = video.videoHeight;
  c.getContext("2d")!.drawImage(video, 0, 0);
  return new Promise((done) => c.toBlob((b) => done(b!), "image/jpeg", 0.9));
}
