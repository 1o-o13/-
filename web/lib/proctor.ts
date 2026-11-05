// 감독 규칙의 화면 쪽 (순수 로직). 판정(경고·포기·의심 건)은 서버 /proctor가 하고, 화면은 이벤트를 한 번씩만 보낸다.
export type ProctorEvent = { event_type: "tab_leave" | "window_blur" | "face_missing" | "multi_face" | "gaze_away" | "upload_fail"; duration_ms: number };

/** 탭 전환(visibilitychange)·창 이탈(blur)을 한 번의 이탈로 묶는다. 둘이 같이 와도 1번, 돌아올 때 지속 시간과 함께 보낸다 */
export class LeaveTracker {
  count = 0;
  private since = -1;
  private kind: "tab_leave" | "window_blur" = "tab_leave";

  leave(kind: "tab_leave" | "window_blur", t: number): void {
    if (this.since >= 0) {
      if (kind === "tab_leave") this.kind = "tab_leave";   // 창 이탈 중 탭까지 바꾸면 탭 이탈로 기록
      return;
    }
    this.since = t;
    this.kind = kind;
  }

  back(t: number): ProctorEvent | null {
    if (this.since < 0) return null;
    const ev = { event_type: this.kind, duration_ms: Math.round(t - this.since) };
    this.since = -1;
    this.count += 1;
    return ev;
  }
}

export const FACE_MS = 5000;   // 얼굴 없음·시선 이탈이 이만큼 이어지면 보고 (IV-31)

/** 얼굴 감지 결과를 넣으면 보고할 이벤트를 돌려준다. 같은 상황이 이어지는 동안은 한 번만 */
export class FaceWatch {
  private since: Record<"face_missing" | "gaze_away" | "multi_face", number> = { face_missing: -1, gaze_away: -1, multi_face: -1 };
  private sent = { face_missing: false, gaze_away: false, multi_face: false };

  update(faces: number, gazeAway: boolean, t: number): ProctorEvent[] {
    const now = { face_missing: faces === 0, multi_face: faces > 1, gaze_away: faces === 1 && gazeAway };
    const out: ProctorEvent[] = [];
    for (const k of ["face_missing", "multi_face", "gaze_away"] as const) {
      if (!now[k]) {
        this.since[k] = -1;
        this.sent[k] = false;
        continue;
      }
      if (this.since[k] < 0) this.since[k] = t;
      const d = t - this.since[k];
      if (!this.sent[k] && (k === "multi_face" || d >= FACE_MS)) {
        this.sent[k] = true;
        out.push({ event_type: k, duration_ms: Math.round(d) });
      }
    }
    return out;
  }
}
