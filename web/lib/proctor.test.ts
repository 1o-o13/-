import { describe, expect, it } from "vitest";
import { FaceWatch, LeaveTracker } from "./proctor";

describe("탭 이탈 카운트", () => {
  it("탭 전환과 창 이탈이 같이 와도 한 번으로 센다", () => {
    const t = new LeaveTracker();
    t.leave("tab_leave", 0);
    t.leave("window_blur", 10); // visibilitychange 뒤 blur
    expect(t.back(3000)).toEqual({ event_type: "tab_leave", duration_ms: 3000 });
    expect(t.back(3010)).toBeNull(); // visible 뒤 focus
    expect(t.count).toBe(1);
  });

  it("창 이탈 중 탭을 바꾸면 탭 이탈로 기록", () => {
    const t = new LeaveTracker();
    t.leave("window_blur", 0);
    t.leave("tab_leave", 500);
    expect(t.back(2000)?.event_type).toBe("tab_leave");
  });

  it("돌아올 때마다 횟수가 늘고 지속 시간을 보낸다", () => {
    const t = new LeaveTracker();
    t.leave("window_blur", 0);
    t.back(1000);
    t.leave("tab_leave", 5000);
    expect(t.back(17000)).toEqual({ event_type: "tab_leave", duration_ms: 12000 }); // 10초 이상 → 서버가 포기 처리
    expect(t.count).toBe(2);
  });

  it("떠나지 않았으면 돌아와도 보내지 않음", () => {
    expect(new LeaveTracker().back(100)).toBeNull();
  });
});

describe("얼굴 감지", () => {
  it("얼굴 없음은 5초 이어져야 한 번 보낸다", () => {
    const f = new FaceWatch();
    expect(f.update(0, false, 0)).toEqual([]);
    expect(f.update(0, false, 4900)).toEqual([]);
    expect(f.update(0, false, 5000)).toEqual([{ event_type: "face_missing", duration_ms: 5000 }]);
    expect(f.update(0, false, 8000)).toEqual([]); // 같은 상황이 이어지는 동안은 한 번만
    f.update(1, false, 9000);
    f.update(0, false, 10000);
    expect(f.update(0, false, 15000)).toHaveLength(1); // 다시 생기면 다시 보냄
  });

  it("여러 명은 바로 보낸다", () => {
    expect(new FaceWatch().update(2, false, 0)).toEqual([{ event_type: "multi_face", duration_ms: 0 }]);
  });

  it("시선 이탈도 5초", () => {
    const f = new FaceWatch();
    f.update(1, true, 0);
    expect(f.update(1, true, 3000)).toEqual([]);
    expect(f.update(1, true, 5200)).toEqual([{ event_type: "gaze_away", duration_ms: 5200 }]);
  });
});
