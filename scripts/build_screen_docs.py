"""화면정의서 PDF · 테스트 화면 PDF (11/12). PC(호스트)에서 실행.
  python scripts/build_screen_docs.py   → 바탕화면 화면정의서_6.1.pdf · 테스트화면_6.1.pdf
- 화면정의서: records/screens.py 내용 + 화면마다 대표 사진(가장 최근 E2E 사진)
- 테스트 화면: 가장 최근 E2E가 찍은 사진(web/e2e/screenshots)을 찍은 순서대로 + 단계 설명, 맨 앞에 시험 결과 요약.
  E2E에 없는 화면은 records/docs/extra/(scripts/capture_extra.mjs)에서
"""
import base64
import csv
import glob
import html
import importlib.util
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SHOTS = os.path.join(ROOT, "web", "e2e", "screenshots")
EXTRA = os.path.join(ROOT, "records", "docs", "extra")
TMP = os.path.join(ROOT, "records", "docs")
DESK = os.path.join(os.path.expanduser("~"), "Desktop")

# 테스트 화면 설명 (사진 이름 → 무엇을 확인했는지)
CAPTION = {
    "home": "채용 홈: 회사 소개·공고 목록 (접수 중·접수 예정·심사 중)",
    "signup-social": "간편 가입 마무리: 제공사 이름·이메일 확인 + 휴대폰",
    "signup": "회원가입: 실제 메일·휴대폰 3-4-4·비밀번호 규칙",
    "signup-login": "가입 뒤 로그인 확인 (1차·코딩 전이라 응시 버튼 없음)",
    "my-info": "내 정보: 수정·간편 로그인 연결·회원 탈퇴",
    "apply-form": "지원서 작성 (팀 4쪽 이력서 양식 순서)",
    "apply-done": "지원서 제출 완료 → 서류 심사 중",
    "apply-edit": "마감 전 지원서 수정",
    "apply-blocked": "진행 중인 지원이 있으면 다른 공고 지원 불가",
    "admin-setting-edit": "관리자: 응시 시작 전 AI 면접 설정 수정",
    "admin-posting": "관리자: 채용 공고 작성 → 게시 → 채용 홈에 보임",
    "applications": "지원자: 지원 현황 → 2차 응시 안내",
    "guide-practice": "연습 면접(11/12): 질문 음성 → 생각 → 녹음 → 인식된 글 (평가·저장 없음)",
    "guide": "2차 응시 안내: 규칙 · AI 활용 안내 · 연습 면접 · 글로 답하기 신청",
    "precheck": "사전 점검·동의 (가짜 카메라·마이크로 자동 시험)",
    "precheck-identity": "본인 확인 일치 + 움직임 확인(라이브니스) 완료",
    "ready": "면접 안내: 1~3번 질문 준비 뒤 시작 버튼 활성",
    "live-q1": "AI 면접 1번: 질문 음성·글, 생각 시간 → 녹음 (녹음해 둔 답변을 가짜 마이크로)",
    "live-review": "답변 인식 글 확인·수정 (원본의 30%까지, 60초)",
    "live-q3": "3번: 인터넷 끊김 → 복구 → 새로고침 뒤 같은 문항에서 이어서 (11/12) · 글자 크기 키움",
    "live-q4": "4번 문항 진행",
    "live-q10": "10번(마지막) 문항",
    "done": "응시 완료 (점수 없음, 발표 예정일)",
    "admin-setting-locked": "관리자: 첫 응시 시작 뒤 설정 잠김",
    "admin-applicants": "관리자: 지원자 현황 (상세 단계·AI 1차 결론·코딩 등급)",
    "admin-list": "관리자: AI 면접 결과 목록",
    "admin-detail": "관리자: 결과 검토 (질문·답변 STT·점수·근거·구간별 리포트)",
    "admin-confirmed": "관리자: 확정 → 2차 종합 점수 생성",
    "admin-final-check": "최종 합격: 체크박스 + '결과 확정' (확정 전)",
    "admin-final": "최종 합격: 결과 확정·알림 완료",
    "coding": "이준서: 코딩 테스트 화면 (예제 실행·제출, 통과 수만)",
    "doc-screened": "1차 서류: AI 1차 검토 뒤 추천 순 (추천은 지원자의 30%)",
    "doc-decided": "1차 서류: 추천자만 체크 (비추천은 체크 불가)",
    "doc-announced": "1차 서류: '결정 확인' 한 번으로 확정·발표 → 지원자 알림",
    "doc-result": "지원자: 1차 결과 발표 화면 (합격 안내)",
    "x-1-admin-login": "관리자 로그인 (아이디·비밀번호 + 2단계 인증)",
    "x-2-admin-resume": "관리자: 이력서 원본 (인적사항은 담당자에게만, AI에는 가려서)",
    "x-3-accommodation": "관리자: 글로 답하기 신청 승인·거절 (11/12)",
    "x-4-guide-accommodation": "지원자: 글로 답하기 신청 상태 (11/12)",
    "x-5-admin-users": "최고관리자: 관리자 가입 승인",
}


def img(path: str, cls: str = "shot") -> str:
    data = base64.b64encode(open(path, "rb").read()).decode()
    return f'<img class="{cls}" src="data:image/png;base64,{data}">'


def latest_shots() -> list[tuple[str, str]]:
    """가장 최근 E2E 사진: 이름마다 가장 새 파일, 찍은 순서(번호)대로"""
    best: dict[str, tuple[float, str, int]] = {}
    for p in glob.glob(os.path.join(SHOTS, "*.png")):
        m = re.match(r"(\d+)-(.+)\.png$", os.path.basename(p))
        if m:
            t = os.path.getmtime(p)
            if m.group(2) not in best or t > best[m.group(2)][0]:
                best[m.group(2)] = (t, p, int(m.group(1)))
    newest = max((v[0] for v in best.values()), default=0)
    keep = {k: v for k, v in best.items() if newest - v[0] < 3 * 3600}     # 마지막 실행(3시간 안)에 찍힌 것만
    out = sorted(((v[2], k, v[1]) for k, v in keep.items()))
    for p in sorted(glob.glob(os.path.join(EXTRA, "*.png"))):
        out.append((999, "x-" + os.path.basename(p)[:-4], p))
    return [(k, p) for _, k, p in out]


CSS = """
@page { size: A4; }
body { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; color: #1f2937; font-size: 10.5pt; line-height: 1.55; }
h1 { font-size: 22pt; margin: 0 0 4px; color: #1f3a5f; } h2 { font-size: 14pt; color: #1f3a5f; border-bottom: 2px solid #d9822b; padding-bottom: 3px; margin-top: 18px; }
.sub { color: #6b7280; margin-bottom: 14px; } .cover { page-break-after: always; }
table.meta { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 9.5pt; }
table.meta th { background: #1f3a5f; color: #fff; text-align: left; padding: 4px 8px; width: 92px; vertical-align: top; font-weight: 600; }
table.meta td { border-bottom: 1px solid #e5e7eb; padding: 4px 8px; vertical-align: top; }
table.meta ul { margin: 0; padding-left: 16px; } .screen { page-break-inside: avoid; margin-bottom: 18px; }
.screen h3 { margin: 0 0 2px; font-size: 12.5pt; } .id { color: #d9822b; font-weight: 700; margin-right: 6px; }
.shot { width: 100%; display: block; } .thumb { width: 100%; display: block; }
.crop { max-height: 420px; overflow: hidden; border: 1px solid #d5dce6; border-radius: 4px; margin: 6px 0; }   /* 긴 화면은 윗부분만 읽을 크기로 */
.crop.tall { max-height: 960px; }
.fig { page-break-inside: avoid; margin: 0 0 16px; } .cap { font-size: 9.5pt; color: #374151; margin: 4px 0 0; } .no { color: #d9822b; font-weight: 700; margin-right: 6px; }
table.sum { border-collapse: collapse; width: 100%; font-size: 9.5pt; } table.sum th, table.sum td { border: 1px solid #d5dce6; padding: 4px 8px; text-align: left; }
table.sum th { background: #eaf1fa; } .toc { columns: 2; font-size: 9.5pt; } .toc div { break-inside: avoid; }
"""


def page(title: str, body: str) -> str:
    return f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"


def screen_doc(shots: dict[str, str]) -> str:
    spec = importlib.util.spec_from_file_location("screens", os.path.join(ROOT, "records", "screens.py"))
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    e = html.escape
    toc = "".join(f"<div><b>{e(g)}</b><br>" + "<br>".join(f"<span class='id'>{s[0]}</span>{e(s[1])}" for s in items) + "</div>"
                  for g, items in sc.GROUPS)
    n = sum(len(i) for _, i in sc.GROUPS)
    body = [f"""<div class='cover'><h1>화면정의서 — 6.1 AI 화상면접</h1>
<div class='sub'>새벽소프트 채용 · 실제 구현 기준 {datetime.now():%Y-%m-%d} · 화면 {n}개 · 사진은 가장 최근 자동 시험(E2E) 화면</div>
<table class='sum'><tr><th>범위</th><td>채용 사이트(지원자) · 2차 응시(코딩 테스트·AI 화상면접) · 관리자(공고·1차 서류·면접 결과·최종 합격)</td></tr>
<tr><th>공통 규칙</th><td>지원자 화면에는 점수·판정을 보여 주지 않음 · 영상·얼굴 사진 저장 안 함 · 답변 음성은 STT 직후 삭제 · AI에는 이름·학교·연락처·주소를 가려서 보냄 · 합격 결정은 사람(담당관) · 면접 기록은 최종 발표 후 180일 뒤 파기</td></tr>
<tr><th>11/12 변경</th><td>AI 활용 안내 · 연습 면접 · 글로 답하기(신청·승인) · 라이브니스 · 글자 크기 · 끊김 복구 확인 · 1차: 지원 번호 공고별, 하드 필터·보류 제거, 추천 30% · 다른 목소리 의심 표기 · STT 용어 힌트</td></tr>
<tr><th>11/16 변경</th><td>얼굴 대조 DeepFace ArcFace → InsightFace buffalo_l(본인 웹캠 통과 80% → 100%) · 사내 판정 모델 형식 실패 고침(성공 63% → 100%) · 목소리 표기에서 '작은 목소리' 제거(직접 녹음 비교에서 음량으로 못 가림)</td></tr>
<tr><th>11/17 변경</th><td>화면 디자인을 부드럽게(둥근 모서리·옅은 그림자, 메인 화면 밝은 새벽 하늘 색, 머리글 한 줄) · 합격·불합격·서류 탈락 안내 문구 보강 · 관리자 AI 면접 결과 표기(응시 번호 IV-3, AI 검증 · 검증 완료, 면접 점수) · 채용 공고 11개 → 5개 · 시험용 예시 답변 기능 삭제 · STT 표시 지연 측정(180초 답변 약 19초)</td></tr></table>
<h2>목차</h2><div class='toc'>{toc}</div></div>"""]
    for g, items in sc.GROUPS:
        body.append(f"<h2>{e(g)}</h2>")
        for sid, name, url, user, purpose, parts, rules, api, shot in items:
            li = lambda xs: "<ul>" + "".join(f"<li>{e(x)}</li>" for x in xs) + "</ul>" if xs else "-"   # noqa: E731
            pic = f"<div class='crop'>{img(shots[shot], 'thumb')}</div>" if shot and shot in shots else ""
            body.append(f"""<div class='screen'><h3><span class='id'>{sid}</span>{e(name)}</h3>
<table class='meta'><tr><th>주소</th><td>{e(url)}</td></tr><tr><th>사용자</th><td>{e(user)}</td></tr><tr><th>목적</th><td>{e(purpose)}</td></tr>
<tr><th>구성 요소</th><td>{li(parts)}</td></tr><tr><th>동작·규칙</th><td>{li(rules)}</td></tr><tr><th>관련 API</th><td>{e(api)}</td></tr></table>{pic}</div>""")
    return page("화면정의서 6.1", "".join(body))


def test_doc(shots: list[tuple[str, str]]) -> str:
    runs = list(csv.DictReader(open(os.path.join(ROOT, "records", "test_runs.csv"), encoding="utf-8-sig")))
    last = {}
    for r in runs:
        last[r.get("종류") or r.get("kind") or ""] = r
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(' · '.join(str(v) for kk, v in r.items() if kk not in ('종류', 'kind') and v))}</td></tr>"
                   for k, r in last.items() if k)
    body = [f"""<div class='cover'><h1>테스트 화면 — 6.1 AI 화상면접</h1>
<div class='sub'>자동 시험(Playwright E2E)이 실제 화면을 처음부터 끝까지 누르며 찍은 사진 · {datetime.now():%Y-%m-%d} · 사진 {len(shots)}장</div>
<table class='sum'><tr><th>시험 방법</th><td>PC의 Chrome으로 가입 → 지원 → 관리자 공고 → 2차 응시(연습 면접 · 점검 · 본인 확인 · 라이브니스 · 10문항 · 인식 글 확인 · 끊김 복구) → 관리자 확정 → 최종 합격 → 코딩 테스트 → 1차 서류 결정까지.
카메라·마이크는 가짜 장치(마이크에는 미리 녹음한 한국어 답변), 얼굴 감지는 자동 시험용 가짜 얼굴. 실제 STT·LLM 사용.</td></tr>
{rows}</table><p class='cap'>※ 면접 화면의 카메라 칸이 초록·'얼굴 감지를 쓸 수 없습니다'로 보이는 것은 자동 시험의 가짜 카메라 때문입니다. 'x-'로 시작하는 사진은 E2E 밖에서 같은 날 찍은 보충 화면입니다.</p></div>"""]
    for i, (k, p) in enumerate(shots, 1):
        body.append(f"<div class='fig'><div class='crop tall'>{img(p)}</div><p class='cap'><span class='no'>{i}</span>{html.escape(CAPTION.get(k, k))}</p></div>")
    return page("테스트 화면 6.1", "".join(body))


def main() -> int:
    os.makedirs(TMP, exist_ok=True)
    shots = latest_shots()
    if not shots:
        print("E2E 사진이 없습니다")
        return 1
    by = {k.removeprefix("x-"): p for k, p in shots}
    jobs = [("화면정의서_6.1", screen_doc(by)), ("테스트화면_6.1", test_doc(shots))]
    for name, doc in jobs:
        src = os.path.join(TMP, f"{name}.html")
        open(src, "w", encoding="utf-8").write(doc)
        out = os.path.join(DESK, f"{name}.pdf")
        subprocess.run(["node", "scripts/pdf.mjs", src, out], cwd=os.path.join(ROOT, "web"), check=True)
        print("저장:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
