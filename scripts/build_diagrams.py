"""워크플로우·DB 관계도 그림 (11/17). SVG를 만들고 Chrome으로 PNG로 바꾼다 → docs/최종/src/fig/*.png
  python scripts/build_diagrams.py
그림은 PDF·Word 문서(scripts/build_project_docs.py, ![설명](fig:이름.png))에 들어간다.
DB 관계는 실제 DB의 외래키를 기준으로 손으로 배치했다 (테이블이 바뀌면 여기 좌표·목록도 고친다).
"""
import html
import os
import subprocess

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FIG = os.path.join(ROOT, "docs", "최종", "src", "fig")
FONT = "'Malgun Gothic', sans-serif"
NAVY, BRAND, DAWN, INK, MUTED, LINE = "#2a2857", "#5f59e0", "#ea6a12", "#1f2937", "#6b7280", "#c9c5e3"
FILL = {"cand": ("#eff6ff", "#60a5fa"), "sys": ("#ecfdf5", "#34d399"), "ai": ("#f5f3ff", "#8b7cf6"), "hr": ("#fff7ed", "#fb923c"),
        "code": ("#f8fafc", "#94a3b8"), "db": ("#f1f5f9", "#64748b")}


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def svg(w: int, h: int, body: list[str]) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}' font-family=\"{FONT}\">"
            "<defs><marker id='a' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
            f"<path d='M0,0 L10,5 L0,10 z' fill='{MUTED}'/></marker>"
            "<marker id='ab' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
            f"<path d='M0,0 L10,5 L0,10 z' fill='{BRAND}'/></marker></defs>"
            f"<rect width='{w}' height='{h}' fill='white'/>" + "".join(body) + "</svg>")


def text(x, y, s, size=13, color=INK, anchor="middle", weight=400):
    return f"<text x='{x}' y='{y}' font-size='{size}' fill='{color}' text-anchor='{anchor}' font-weight='{weight}'>{esc(s)}</text>"


def box(x, y, w, h, lines, kind="sys", size=13, r=10, bold_first=True):
    fill, stroke = FILL[kind]
    out = [f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{r}' fill='{fill}' stroke='{stroke}' stroke-width='1.5'/>"]
    lh = size + 5
    top = y + h / 2 - (len(lines) - 1) * lh / 2 + size * 0.35
    for i, s in enumerate(lines):
        out.append(text(x + w / 2, top + i * lh, s, size if i == 0 else size - 1.5, INK if i == 0 else MUTED, weight=700 if i == 0 and bold_first else 400))
    return "".join(out)


def arrow(pts, color=MUTED, dash=False, label=None, lx=None, ly=None, marker="a", width=1.6):
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    dash_attr = "stroke-dasharray='5 4'" if dash else ""
    out = f"<path d='{d}' fill='none' stroke='{color}' stroke-width='{width}' {dash_attr} marker-end='url(#{marker})'/>"
    if label:
        out += text(lx, ly, label, 11.5, color if color != MUTED else MUTED)
    return out


def legend(x, y, items):
    out = []
    for i, (kind, s) in enumerate(items):
        fill, stroke = FILL[kind]
        out.append(f"<rect x='{x + i * 150}' y='{y}' width='16' height='16' rx='4' fill='{fill}' stroke='{stroke}'/>")
        out.append(text(x + i * 150 + 24, y + 13, s, 12, MUTED, "start"))
    return "".join(out)


# ---------- 1. 전체 흐름 (지원자 · 시스템/AI · 담당자) ----------
def wf_overall():
    W, H, X0, CW, LH, TOP = 1500, 640, 130, 228, 165, 70
    cols = ["① 지원 · 1차 서류", "② 1차 발표 · 2차 안내", "③ 점검 · 코딩 테스트", "④ AI 화상면접", "⑤ 평가 · 확정", "⑥ 최종 결정 · 발표"]
    lanes = [("지원자", "cand"), ("시스템 · AI", "ai"), ("채용 담당자", "hr")]
    cells = {
        (0, 0): ["공고 보고 지원", "지원서 · 증명사진 · 동의"], (1, 0): ["AI 1차 검토", "요건별 근거 · 추천 30%", "(점수 없음)"],
        (2, 0): ["합격자 체크", "'결정 확인' 한 번 → 발표"],
        (0, 1): ["1차 결과 확인", "2차 안내 · AI 활용 고지", "연습 면접 · 글로 답하기 신청"], (1, 1): ["질문 미리 만들기", "1·2번 + 본 질문 후보", "검증 통과분만 출제"],
        (2, 1): ["글로 답하기 승인", "(신청한 지원자만)"],
        (0, 2): ["사전 점검 · 동의", "본인 확인 · 움직임 확인", "→ 코딩 테스트"], (1, 2): ["얼굴 대조 (InsightFace)", "코딩 채점 → 등급", "→ 3번 질문 생성"],
        (0, 3): ["10문항 응시", "듣기 → 생각 → 답변", "→ 인식 글 확인"], (1, 3): ["STT → 판정 → next_action", "꼬리·재질문 생성", "감독 → 의심 건"],
        (0, 4): ["응시 완료", "점수는 보이지 않음"], (1, 4): ["최종 평가 + 5검사", "실패하면 재평가 1번"], (2, 4): ["리포트 검토 → 확정", "의심 건 처리 · 재응시"],
        (0, 5): ["최종 결과 확인", "합격 축하 · 불합격 감사 인사"], (1, 5): ["2차 종합", "면접 60 + 코딩 40", "과락 · AI 추천"], (2, 5): ["합격자 체크", "'결과 확정' → 모두에게 알림"],
    }
    b = [text(W / 2, 32, "전체 업무 흐름 — 누가 무엇을 하는가", 20, NAVY, weight=700)]
    for i, c in enumerate(cols):
        b.append(text(X0 + i * CW + CW / 2, TOP - 12, c, 14, NAVY, weight=700))
    for li, (name, kind) in enumerate(lanes):
        y = TOP + li * LH
        b.append(f"<rect x='10' y='{y}' width='{W - 20}' height='{LH - 8}' rx='12' fill='{FILL[kind][0]}' opacity='.45'/>")
        b.append(text(65, y + LH / 2, name, 15, NAVY, weight=700))
    BW, BH = CW - 26, LH - 34
    pos = {}
    for (lane, col), lines in cells.items():
        x, y = X0 + col * CW + 13, TOP + lane * LH + 13
        pos[(lane, col)] = (x, y)
        b.append(box(x, y, BW, BH, lines, lanes[lane][1], 13))
    # 같은 줄 흐름
    for lane in range(3):
        cs = sorted(c for l, c in pos if l == lane)
        for a, c in zip(cs, cs[1:]):
            (x1, y1), (x2, _) = pos[(lane, a)], pos[(lane, c)]
            b.append(arrow([(x1 + BW, y1 + BH / 2), (x2, y1 + BH / 2)], LINE if c - a > 1 else MUTED, dash=c - a > 1))
    # 줄 사이 넘겨주기 (세로)
    for (l1, l2, col, lab) in [(0, 1, 0, "제출"), (1, 2, 0, "AI 추천"), (1, 1, 1, ""), (0, 1, 2, "프레임 1장"), (0, 1, 3, "답변 음성"),
                               (1, 2, 4, "검증 통과본"), (1, 2, 5, "순위·추천")]:
        if l1 == l2:
            continue
        x, y = pos[(l1, col)]
        _, y2 = pos[(l2, col)]
        b.append(arrow([(x + BW / 2, y + BH), (x + BW / 2, y2)], BRAND, label=lab, lx=x + BW / 2 + 34, ly=(y + BH + y2) / 2 + 4, marker="ab"))
    x, y = pos[(2, 0)]
    x2, y2 = pos[(0, 1)]
    b.append(arrow([(x + BW, y + BH * 0.25), (x + BW + 7, y + BH * 0.25), (x + BW + 7, y2 + BH * 0.8), (x2, y2 + BH * 0.8)], DAWN, width=2))
    b.append(f"<rect x='{x + BW - 30}' y='{y2 + LH + 18}' width='74' height='20' rx='6' fill='white'/>")
    b.append(text(x + BW + 7, y2 + LH + 32, "1차 발표", 12, DAWN, weight=700))
    b.append(legend(140, H - 30, [("cand", "지원자가 하는 일"), ("ai", "시스템·AI가 하는 일"), ("hr", "사람(담당자)이 정하는 일")]))
    b.append(text(W - 20, H - 17, "합격·불합격은 언제나 담당자가 정합니다. AI 결과는 근거가 붙은 참고값입니다.", 12, MUTED, "end"))
    return svg(W, H, b)


# ---------- 2. 면접 그래프 ----------
def wf_graph():
    W, H = 1500, 560
    b = [text(W / 2, 32, "AI 화상면접 그래프 (LangGraph, 응시 1회 = thread 1개)", 20, NAVY, weight=700)]
    row1 = [("setup", ["setup", "응시 정보·모델 고정"], "code"), ("generate", ["generate", "질문 꺼내기·만들기"], "ai"),
            ("guard", ["guard", "금지어·NLI 모순 검사", "질문 저장·표시"], "ai"), ("ask", ["ask  ⏸", "지원자 답변 대기", "(interrupt)"], "cand"),
            ("evaluate", ["evaluate", "STT 글 판정", "점수·루브릭·인용"], "ai"), ("save", ["save", "판정·관련성 기록"], "code"),
            ("decide", ["decide", "next_action", "꼬리·재질문·다음 주제·종료"], "code")]
    x, y, BW, BH, GAP = 30, 150, 178, 92, 30
    P = {}
    for i, (k, lines, kind) in enumerate(row1):
        P[k] = (x + i * (BW + GAP), y)
        b.append(box(*P[k], BW, BH, lines, kind, 14))
        if i:
            px = P[row1[i - 1][0]][0] + BW
            b.append(arrow([(px, y + BH / 2), (P[k][0], y + BH / 2)]))
    gx, dx = P["generate"][0], P["decide"][0]
    b.append(arrow([(dx + BW / 2, y), (dx + BW / 2, y - 55), (gx + BW / 2, y - 55), (gx + BW / 2, y)], BRAND, label="다음 질문 (10문항이 될 때까지 반복)",
                   lx=(dx + gx + BW) / 2, ly=y - 63, marker="ab"))
    row2 = [("finish", ["finish", "면접 종료 처리"], "code"), ("ctx", ["context · load", "문항·판정 모으기"], "code"),
            ("checks", ["report", "최종 평가 v1 + 5검사", "실패 → 재평가 v2"], "ai"), ("hr", ["hr_decide  ⏸", "담당자 확정 대기", "(interrupt)"], "hr"),
            ("end", ["끝", "2차 종합 점수 반영"], "code")]
    y2 = 360
    for i, (k, lines, kind) in enumerate(row2):
        P[k] = (x + (i + 2) * (BW + GAP), y2)
        b.append(box(*P[k], BW, BH, lines, kind, 14))
        if i:
            px = P[row2[i - 1][0]][0] + BW
            b.append(arrow([(px, y2 + BH / 2), (P[k][0], y2 + BH / 2)]))
    fx = P["finish"][0]
    b.append(arrow([(dx + BW / 2, y + BH), (dx + BW / 2, y + BH + 50), (fx + BW / 2, y + BH + 50), (fx + BW / 2, y2)], DAWN, label="10문항 끝",
                   lx=(dx + fx + BW) / 2, ly=y + BH + 42))
    b.append(box(30, y2, 2 * (BW + GAP) - GAP, BH, ["오류가 나도 멈추지 않음", "판정 실패 → 점수 보류 + 다음 주제", "STT 실패 → no_stt + 다음 주제"], "db", 13))
    b.append(text(W / 2, 505, "멈춘 자리(⏸)에서 사람의 입력을 기다렸다가 같은 thread로 이어 갑니다. 진행 상태는 PostgreSQL 체크포인트에 저장해 서버를 다시 켜도 이어집니다.", 12.5, MUTED))
    b.append(legend(250, 525, [("ai", "LLM이 글을 씀"), ("code", "코드가 정함"), ("cand", "지원자 입력"), ("hr", "담당자 결정"), ("db", "예외 처리")]))
    return svg(W, H, b)


# ---------- 3. 한 문항 처리 순서 ----------
def wf_question():
    actors = ["지원자 브라우저", "api (FastAPI)", "worker (Celery)", "stt (Whisper)", "LLM 관문 · 모델", "PostgreSQL"]
    kinds = ["cand", "sys", "sys", "sys", "ai", "db"]
    W, X0, DX, TOP = 1500, 120, 252, 80
    msgs = [  # (from, to, 글, 색)
        (0, 1, "① 답변 음성 업로드 (최대 3분, '답변 끝')", INK), (1, 2, "② 답변 처리 작업 넣기", INK), (2, 3, "③ 인식 요청 (+ 질문 핵심어 힌트)", INK),
        (3, 2, "④ 인식 글 + 목소리 구간", INK), (2, 5, "⑤ 인식 원본 저장 · 음성 즉시 삭제", INK), (1, 0, "⑥ SSE: 인식 글 확인 요청", BRAND),
        (0, 1, "⑦ 틀린 곳만 고쳐 '완료' (30%·60초)", INK), (2, 4, "⑧ 판정 요청 (개인정보 가림 · tier 경로)", INK), (4, 2, "⑨ 점수 · 루브릭 · 인용", INK),
        (2, 2, "⑩ next_action → 꼬리·재질문 생성 또는 미리 만든 본 질문", DAWN), (2, 5, "⑪ 판정 · 다음 질문 저장", INK), (1, 0, "⑫ SSE: 다음 질문 + 음성", BRAND),
    ]
    STEP = 46
    H = TOP + 70 + len(msgs) * STEP + 60
    b = [text(W / 2, 32, "한 문항 처리 순서 — 답변 제출부터 다음 질문까지", 20, NAVY, weight=700)]
    for i, (a, k) in enumerate(zip(actors, kinds)):
        cx = X0 + i * DX
        b.append(box(cx - 100, TOP, 200, 44, [a], k, 14))
        b.append(f"<line x1='{cx}' y1='{TOP + 44}' x2='{cx}' y2='{H - 50}' stroke='{LINE}' stroke-width='1.5' stroke-dasharray='4 4'/>")
    y = TOP + 80
    for f, t, s, c in msgs:
        x1, x2 = X0 + f * DX, X0 + t * DX
        if f == t:
            b.append(f"<path d='M{x1},{y - 6} h40 v18 h-36' fill='none' stroke='{c}' stroke-width='1.6' marker-end='url(#a)'/>")
            b.append(text(x1 + 50, y + 8, s, 12.5, c, "start", 600))
        else:
            b.append(arrow([(x1, y), (x2 + (-6 if x2 > x1 else 6), y)], c if c != INK else MUTED, marker="ab" if c == BRAND else "a"))
            b.append(text((x1 + x2) / 2, y - 7, s, 12.5, c, weight=600 if c != INK else 400))
        y += STEP
    b.append(text(W / 2, H - 20, "실측: 답변 180초도 ④까지 약 19초, 사내 판정 1회 약 8초. 판정이 30초를 넘으면 대체 모델, 60초면 점수 보류 후 다음 주제.", 12.5, MUTED))
    return svg(W, H, b)


# ---------- 4. 지원 건 단계 ----------
def wf_stages():
    W, H = 1500, 470
    b = [text(W / 2, 32, "지원 건 상세 단계 (11종) — 허용된 이동만 DB 트리거가 통과시킴", 20, NAVY, weight=700)]
    main = [("submitted", "서류 접수"), ("screen_passed", "1차 합격"), ("coding_waiting", "합격 후 단계 끝"), ("scheduled", "응시 안내 발송"),
            ("coding", "코딩 테스트"), ("interview", "화상 면접")]
    BW, BH, y, x0, gap = 170, 66, 170, 30, 34
    P = {}
    for i, (k, s) in enumerate(main):
        P[k] = (x0 + i * (BW + gap), y)
        b.append(box(*P[k], BW, BH, [s, k], "sys" if k != "interview" else "ai", 14))
        if i:
            b.append(arrow([(P[main[i - 1][0]][0] + BW, y + BH / 2), (P[k][0], y + BH / 2)]))
    ix = P["interview"][0]
    for k, s, yy, kind in [("final_pass", "최종 합격", 100, "cand"), ("final_fail", "최종 불합격", 250, "hr")]:
        P[k] = (ix + BW + 70, yy)
        b.append(box(*P[k], BW, BH, [s, k], kind, 14))
        b.append(arrow([(ix + BW, y + BH / 2), (ix + BW + 35, y + BH / 2), (ix + BW + 35, yy + BH / 2), (ix + BW + 70, yy + BH / 2)]))
    sx, cx = P["scheduled"][0], P["coding"][0]
    b.append(arrow([(sx + BW / 2, y), (sx + BW / 2, y - 45), (ix + BW / 2, y - 45), (ix + BW / 2, y)], BRAND, label="코딩 없는 직군은 바로 면접",
                   lx=(sx + ix + BW) / 2, ly=y - 53, marker="ab"))
    yb = 350
    sub_x, pas_x = P["submitted"][0], P["screen_passed"][0]
    P["screen_failed"] = (sub_x, yb)
    b.append(box(sub_x, yb, 150, BH, ["서류 탈락", "screen_failed"], "db", 14))
    P["screen_rejected"] = (pas_x, yb)
    b.append(box(pas_x, yb, BW, BH, ["1차 불합격", "screen_rejected"], "db", 14))
    b.append(arrow([(sub_x + 60, y + BH), (sub_x + 60, yb)]))
    b.append(arrow([(sub_x + 160, y + BH), (sub_x + 160, yb + BH / 2), (pas_x, yb + BH / 2)]))
    b.append(arrow([(pas_x + BW / 2, y + BH), (pas_x + BW / 2, yb)], DAWN, label="부정행위 (사유 필수)", lx=pas_x + BW / 2 + 70, ly=y + BH + 50))
    # 지원 취소: 합격 후 단계부터 화상 면접까지 어디서든
    bus = y + BH + 30
    keys = ("coding_waiting", "scheduled", "coding", "interview")
    for k in keys:
        px = P[k][0] + BW / 2
        b.append(f"<path d='M{px},{y + BH} V{bus}' stroke='{MUTED}' stroke-width='1.3' stroke-dasharray='4 4' fill='none'/>")
    b.append(f"<path d='M{P[keys[0]][0] + BW / 2},{bus} H{P[keys[-1]][0] + BW / 2}' stroke='{MUTED}' stroke-width='1.3' stroke-dasharray='4 4' fill='none'/>")
    wx = P["scheduled"][0] + BW + gap / 2 - 100
    P["withdrawn"] = (wx, yb)
    b.append(box(wx, yb, 200, BH, ["지원 취소", "withdrawn"], "db", 14))
    b.append(arrow([(wx + 100, bus), (wx + 100, yb)], MUTED, dash=True, label="최종 전에는 어디서든", lx=wx + 175, ly=bus + 30))
    b.append(text(W / 2, H - 18, "단계 이동은 api/stage.py가 하고 이동 기록은 application_stage_log에 남습니다. 서류 탈락(screen_failed)은 예전 하드 필터용으로 남은 단계입니다(11/12 하드 필터 제거).", 12.5, MUTED))
    return svg(W, H, b)


# ---------- DB: 영역 지도 ----------
def erd_overview():
    W, H = 1500, 990
    b = [text(W / 2, 32, "DB 영역 지도 — 테이블 61개, 외래키 84개 (application이 중심)", 20, NAVY, weight=700)]
    groups = [
        ("채용·공고 (공통)", "hr", 30, 70, 440, 230, ["department", "admin_user", "hiring_request", "job_posting", "posting_assignee", "posting_review",
                                                      "posting_history", "announcement", "notification", "policy_setting"]),
        ("지원자·계정 (공통)", "cand", 530, 70, 440, 230, ["candidate", "resume", "candidate_consent", "consent_document", "candidate_social_account",
                                                       "notification_pref", "login_history", "data_request", "inquiry"]),
        ("1차 서류 (임시)", "sys", 1030, 70, 440, 230, ["document_criteria", "document_evaluation", "document_review", "stage_result", "dept_opinion"]),
        ("코딩 테스트 (임시)", "sys", 30, 590, 420, 330, ["coding_setting", "coding_session", "coding_problem", "coding_case", "coding_attempt",
                                                     "coding_submission", "coding_review", "coding_result"]),
        ("2차 AI 화상면접 (6.1)", "ai", 520, 590, 440, 330, ["interview_setting", "interview_session", "interview_question", "interview_answer",
                                                         "answer_judgement", "answer_signal", "interview_evaluation", "evaluation_check", "ai_error_alert",
                                                         "identity_check", "proctor_event", "suspicion_case", "interview_incident", "interview_note",
                                                         "answer_accommodation"]),
        ("질문·근거·LLM (6.1)", "ai", 1030, 390, 440, 170, ["question_bank", "prepared_question", "company_doc_chunk (pgvector)", "llm_call",
                                                         "checkpoints (그래프 4개)"]),
        ("단계·결과", "hr", 1030, 620, 440, 300, ["application_stage", "application_stage_log", "stage_transition", "stage2_score", "stage2_exception",
                                                "audit_log", "ai_usage_log"]),
    ]
    for name, kind, x, y, w, h, tables in groups:
        fill, stroke = FILL[kind]
        b.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='14' fill='{fill}' stroke='{stroke}' stroke-width='1.6'/>")
        b.append(text(x + 18, y + 28, name, 15, NAVY, "start", 700))
        cx, cy = x + 18, y + 48
        for t in tables:
            tw = 8.2 * len(t) + 20
            if cx + tw > x + w - 12:
                cx, cy = x + 18, cy + 34
            b.append(f"<rect x='{cx}' y='{cy}' width='{tw}' height='26' rx='13' fill='white' stroke='{stroke}'/>")
            b.append(text(cx + tw / 2, cy + 18, t, 12, INK))
            cx += tw + 8
    # 중심: application
    ax, ay, aw, ah = 590, 380, 320, 96
    b.append(f"<rect x='{ax}' y='{ay}' width='{aw}' height='{ah}' rx='16' fill='{NAVY}'/>")
    b.append(text(ax + aw / 2, ay + 40, "application (지원 건)", 19, "white", weight=700))
    b.append(text(ax + aw / 2, ay + 68, "candidate_id · posting_id · 이력서 스냅숏 · 증명사진", 12.5, "#d9d6fb"))
    links = [((250, 300), (ax + 40, ay), "posting_id"), ((750, 300), (ax + aw / 2, ay), "candidate_id"), ((1250, 300), (ax + aw - 40, ay), "application_id"),
             ((250, 590), (ax + 40, ay + ah), "coding_session.application_id"), ((740, 590), (ax + aw / 2, ay + ah), "interview_session.application_id"),
             ((1030, 470), (ax + aw, ay + ah / 2), "질문·LLM 기록"), ((1030, 650), (ax + aw - 20, ay + ah), "단계·2차 종합")]
    for (x1, y1), (x2, y2), lab in links:
        b.append(f"<path d='M{x1},{y1} L{x2},{y2}' stroke='{BRAND}' stroke-width='2.2' fill='none' marker-end='url(#ab)'/>")
        mx, my = x1 + (x2 - x1) * 0.45, y1 + (y2 - y1) * 0.45
        lw = sum(12 if ord(ch) > 0x3000 else 6.9 for ch in lab) + 16
        b.append(f"<rect x='{mx - lw / 2}' y='{my - 13}' width='{lw}' height='22' rx='6' fill='white' stroke='#e4e2fd'/>")
        b.append(text(mx, my + 3, lab, 11.5, BRAND, weight=600))
    b.append(f"<path d='M450,780 L520,780' stroke='{BRAND}' stroke-width='2.2' marker-end='url(#ab)'/>")
    b.append(text(485, 754, "coding_", 11, BRAND, weight=600))
    b.append(text(485, 768, "session_id", 11, BRAND, weight=600))
    b.append(text(W / 2, H - 22, "공통 스키마(common_schema.sql)는 다른 파트 소유라 바꾸지 않고, 6.1은 interview_schema.sql의 21개 테이블을 씁니다. company_doc_chunk는 외래키 없이 청크 id(doc#sec)로 참조합니다.", 12.5, MUTED))
    return svg(W, H, b)


# ---------- DB: SQL 도구처럼 그린 관계도 (칼럼·자료형·PK/FK, 외래키 칼럼 → 기본키 칼럼) ----------
TYPE = {"int8": "bigint", "int4": "int", "int2": "smallint", "bool": "boolean", "_text": "text[]", "timestamptz": "timestamptz",
        "jsonb": "jsonb", "text": "text", "numeric": "numeric", "vector": "vector", "bytea": "bytea", "inet": "inet", "cidr": "cidr"}
_SCHEMA = None


def schema() -> dict:
    """실제 DB에서 칼럼·자료형·NULL 여부·PK·FK를 읽는다 (postgres 컨테이너). {테이블: [(칼럼, 자료형, null, pk, fk테이블)]}"""
    global _SCHEMA
    if _SCHEMA is None:
        import json
        q = """select json_agg(row_to_json(x)) from (
          select c.table_name tb, c.column_name col, c.udt_name ty, c.is_nullable = 'YES' nul, c.ordinal_position pos,
            exists(select 1 from information_schema.table_constraints tc join information_schema.key_column_usage k
                   on k.constraint_name = tc.constraint_name and k.table_name = tc.table_name
                   where tc.constraint_type = 'PRIMARY KEY' and tc.table_name = c.table_name and k.column_name = c.column_name) pk,
            (select ccu.table_name from information_schema.table_constraints tc join information_schema.key_column_usage k
                    on k.constraint_name = tc.constraint_name and k.table_name = tc.table_name
                    join information_schema.constraint_column_usage ccu on ccu.constraint_name = tc.constraint_name
             where tc.constraint_type = 'FOREIGN KEY' and tc.table_name = c.table_name and k.column_name = c.column_name
             order by (ccu.table_name = c.table_name) limit 1) fk
          from information_schema.columns c where c.table_schema = 'public' order by 1, 5) x"""
        out = subprocess.run(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "recruit", "-d", "recruit", "-At", "-c", q],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
        _SCHEMA = {}
        for r in json.loads(out):
            _SCHEMA.setdefault(r["tb"], []).append((r["col"], TYPE.get(r["ty"], r["ty"]), r["nul"], r["pk"], r["fk"]))
    return _SCHEMA


RH, HEAD = 17, 28   # 칼럼 한 줄 높이, 머리 높이


class SqlErd:
    def __init__(self, b):
        self.b, self.T = b, {}

    def table(self, name, x, y, w=262, kind="ai", only=None, title=None):
        cols = schema()[name]
        if only:
            cols = [c for c in cols if c[0] in only] + ([("…", f"칼럼 {len(cols) - len(only)}개 더", True, False, None)] if len(cols) > len(only) else [])
        fill, stroke = FILL[kind]
        h = HEAD + RH * len(cols) + 6
        b = self.b
        b.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='4' fill='white' stroke='{stroke}' stroke-width='1.4'/>")
        b.append(f"<rect x='{x}' y='{y}' width='{w}' height='{HEAD}' rx='4' fill='{stroke}'/>")
        b.append(f"<rect x='{x}' y='{y + HEAD - 4}' width='{w}' height='4' fill='{stroke}'/>")
        b.append(f"<svg x='{x + 8}' y='{y + 7}' width='14' height='14' viewBox='0 0 14 14'><rect x='1' y='1' width='12' height='12' rx='2' fill='none' stroke='white' stroke-width='1.3'/>"
                 "<line x1='1' y1='5' x2='13' y2='5' stroke='white' stroke-width='1.3'/><line x1='5' y1='5' x2='5' y2='13' stroke='white' stroke-width='1.3'/></svg>")
        b.append(text(x + 28, y + 19, title or name, 13, "white", "start", 700))
        rows = {}
        for i, (c, ty, nul, pk, fk) in enumerate(cols):
            cy = y + HEAD + RH * i + RH - 4
            rows[c] = cy - 4.5
            if i % 2:
                b.append(f"<rect x='{x + 1}' y='{cy - 12.5}' width='{w - 2}' height='{RH}' fill='#fafafe'/>")
            if pk:
                b.append(f"<text x='{x + 9}' y='{cy}' font-size='11' fill='#d97706'>🔑</text>")
            elif fk:
                b.append(f"<text x='{x + 9}' y='{cy}' font-size='11' fill='{BRAND}'>🔗</text>")
            b.append(text(x + 27, cy, c, 11.5, INK if (pk or fk) else "#374151", "start", 700 if pk else 400))
            b.append(text(x + w - 8, cy, ty + ("" if nul or pk else " ·NN"), 10.5, MUTED, "end"))
        self.T[name] = (x, y, w, h, rows)

    def _row(self, name, col):
        x, y, w, h, rows = self.T[name]
        return rows.get(col, y + HEAD / 2)

    def fk(self, child, col, parent, trunk, pcol="id", cside="l", pside="r", label=None):
        """child.col → parent.pcol. 부모 변(pside)에서 나와 trunk 세로선을 타고 자식 변(cside)의 그 칼럼 줄로 들어간다"""
        px, py, pw, ph, _ = self.T[parent]
        cx, cy, cw, ch, _ = self.T[child]
        y1, y2 = self._row(parent, pcol), self._row(child, col)
        x1 = px + pw if pside == "r" else px
        x2 = cx if cside == "l" else cx + cw
        self.b.append(f"<path d='M{x1},{y1} H{trunk} V{y2} H{x2}' stroke='{BRAND}' stroke-width='1.4' fill='none' opacity='.9'/>")
        d1 = 1 if pside == "r" else -1
        self.b.append(f"<line x1='{x1 + d1 * 7}' y1='{y1 - 5}' x2='{x1 + d1 * 7}' y2='{y1 + 5}' stroke='{BRAND}' stroke-width='1.4'/>")
        d2 = 1 if cside == "l" else -1     # 까마귀발: 자식 변 바깥에서 벌어짐
        self.b.append(f"<path d='M{x2 - d2 * 9},{y2} L{x2},{y2 - 5} M{x2 - d2 * 9},{y2} L{x2},{y2 + 5}' stroke='{BRAND}' stroke-width='1.4' fill='none'/>")
        if label:
            self.b.append(text(trunk + 4, min(y1, y2) - 4, label, 10, BRAND, "start"))

    def note(self, x, y, w, lines):
        h = 18 * len(lines) + 18
        self.b.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='8' fill='#f8f7fc' stroke='#e4e2fd'/>")
        for i, s in enumerate(lines):
            head = s and not s.startswith(("·", " "))
            self.b.append(text(x + 14, y + 24 + i * 18, s, 12 if head else 11.5, NAVY if head else MUTED, "start", 700 if head else 400))


def _bottom(e, *names):
    return max(e.T[n][1] + e.T[n][3] for n in names)


def erd_interview():
    """응시 → 질문 → 답변 → 판정, 응시 → 평가 → 검사·알림"""
    W = 1500
    b = []
    e = SqlErd(b)
    C0, C1, C2, C3, C4 = 20, 318, 616, 914, 1212
    e.table("application", C0, 70, kind="cand", only=["id", "posting_id", "candidate_id", "resume_snapshot", "photo_object_key", "status"])
    e.table("interview_setting", C0, e.T["application"][1] + e.T["application"][3] + 60, kind="hr")
    e.table("interview_session", C1, 70)
    e.table("interview_question", C2, 70)
    e.table("interview_evaluation", C2, e.T["interview_question"][1] + e.T["interview_question"][3] + 40)
    e.table("interview_answer", C3, 70)
    ey = e.T["interview_evaluation"][1]
    e.table("evaluation_check", C3, ey)
    e.table("ai_error_alert", C3, ey + e.T["evaluation_check"][3] + 30, kind="hr")
    e.table("answer_judgement", C4, 70, w=270)
    e.table("answer_signal", C4, 70 + e.T["answer_judgement"][3] + 30, w=270, kind="db")
    e.fk("interview_session", "application_id", "application", C1 - 18)
    e.fk("interview_question", "session_id", "interview_session", C2 - 22)
    e.fk("interview_evaluation", "session_id", "interview_session", C2 - 22)
    e.fk("interview_answer", "question_id", "interview_question", C3 - 26)
    e.fk("evaluation_check", "evaluation_id", "interview_evaluation", C3 - 18)
    e.fk("ai_error_alert", "interview_evaluation_id", "interview_evaluation", C3 - 18)
    e.fk("answer_judgement", "answer_id", "interview_answer", C4 - 22)
    e.fk("answer_signal", "answer_id", "interview_answer", C4 - 22)
    # 자기 참조: 꼬리·재질문 → 원래 질문
    qx, qy, qw, qh, _ = e.T["interview_question"]
    y1, y2 = e._row("interview_question", "id"), e._row("interview_question", "parent_question_id")
    b.append(f"<path d='M{qx},{y1} H{qx - 10} V{y2} H{qx}' stroke='{DAWN}' stroke-width='1.4' fill='none'/>")
    b.append(f"<path d='M{qx - 9},{y2} L{qx},{y2 - 5} M{qx - 9},{y2} L{qx},{y2 + 5}' stroke='{DAWN}' stroke-width='1.4' fill='none'/>")
    sx = e.T["interview_setting"]
    b.append(text(sx[0] + 4, sx[1] - 8, "🔗 posting_id → job_posting.id (공고별 설정 1 : 1)", 10.5, BRAND, "start"))
    lines = ["읽는 법", "· 🔑 기본키  🔗 외래키", "· ·NN = NOT NULL", "· 선: 외래키 칼럼 → 상대 기본키", "· 막대 쪽 1, 갈라진 쪽 여럿",
             "· 주황 선: 꼬리·재질문 → 원래 질문", "", "DB가 막는 규칙", "· 번호 중복, 1·2번 기술 질문", "· 비기술 답변에 점수",
             "· 재질문 2번, 점수 0~100 밖", "· 검증 전 확정", "", "그림에 없는 선", "· ai_error_alert.application_id", "  → application.id",
             "· confirmed_by·handled_by", "  → admin_user.id"]
    ny = e.T["answer_signal"][1] + e.T["answer_signal"][3] + 30
    e.note(C4, ny, 270, lines)
    bot = max(_bottom(e, "interview_setting", "interview_session", "interview_evaluation", "ai_error_alert", "answer_signal"), ny + 18 * len(lines) + 18)
    H = bot + 40
    b.insert(0, text(W / 2, 34, "면접 테이블 관계도 ① 응시 · 질문 · 답변 · 판정 · 평가 (interview_schema.sql)", 19, NAVY, weight=700))
    return svg(W, H, b)


def erd_interview2():
    """본인 확인 · 감독 · 의심 건 · 장애 · 메모 · 응시 편의"""
    W = 1500
    b = []
    e = SqlErd(b)
    C0, C1, C2, C3 = 20, 360, 720, 1110
    e.table("application", C0, 70, kind="cand", only=["id", "posting_id", "candidate_id", "status"])
    e.table("answer_accommodation", C0, e.T["application"][1] + e.T["application"][3] + 50, kind="hr")
    e.table("interview_session", C1, 70, only=["id", "application_id", "attempt_no", "exam_code", "status", "identity_status", "extra_time_sec"])
    y = 70
    for k, kind in [("identity_check", "sys"), ("proctor_event", "sys"), ("interview_incident", "sys"), ("interview_note", "hr")]:
        e.table(k, C2, y, kind=kind)
        y += e.T[k][3] + 28
    e.table("suspicion_case", C1, e.T["interview_session"][1] + e.T["interview_session"][3] + 70, kind="hr")
    e.table("interview_question", C3, e.T["proctor_event"][1] - 10, only=["id", "session_id", "ask_order", "question_text"])
    e.table("admin_user", C3, 70, kind="hr", only=["id", "login_id", "name", "role"])
    e.fk("interview_session", "application_id", "application", C1 - 30)
    e.fk("answer_accommodation", "application_id", "application", C0 - 12, cside="l", pside="l")
    for k in ("identity_check", "proctor_event", "interview_incident", "interview_note"):
        e.fk(k, "session_id", "interview_session", C2 - 26)
    e.fk("suspicion_case", "interview_session_id", "interview_session", C1 - 14, cside="l", pside="l")
    e.fk("suspicion_case", "application_id", "application", C1 - 46)
    e.fk("proctor_event", "question_id", "interview_question", C3 - 24, cside="r", pside="l")
    e.fk("interview_note", "author_id", "admin_user", C3 - 40, cside="r", pside="l")
    bot = _bottom(e, "answer_accommodation", "suspicion_case", "interview_note", "interview_question")
    e.note(C3, e.T["interview_question"][1] + e.T["interview_question"][3] + 40, 360,
           ["이 테이블들의 쓰임", "· identity_check: 본인 확인 거리·구간, 60초 재확인, 라이브니스", "· proctor_event: 탭 이탈·얼굴 없음 등 감독 이벤트",
            "· suspicion_case: 의심 건 → 담당자 결정 (자동 불합격 없음)", "· interview_incident: 장애 원인·추가 시간", "· interview_note: 담당자 메모",
            "· answer_accommodation: 글로 답하기 신청·승인", "", "decided_by·handled_by 등 담당자 칼럼은", "모두 admin_user.id를 가리킵니다"])
    H = max(bot, e.T["interview_question"][1] + e.T["interview_question"][3] + 260) + 40
    b.insert(0, text(W / 2, 34, "면접 테이블 관계도 ② 본인 확인 · 감독 · 의심 건 · 장애 · 메모 · 응시 편의", 19, NAVY, weight=700))
    return svg(W, H, b)


def erd_support():
    """지원 건 중심: 공고·지원자 → 지원 건 → 1차·코딩·질문·LLM·단계·2차 종합"""
    W = 1500
    b = []
    e = SqlErd(b)
    C0, C1, C2, C3 = 20, 360, 720, 1130
    e.table("candidate", C0, 70, kind="cand", only=["id", "email", "name", "phone", "status", "rejoin_blocked_until"])
    e.table("job_posting", C0, e.T["candidate"][1] + e.T["candidate"][3] + 30, kind="hr",
            only=["id", "title", "job_role", "career_level", "headcount", "status", "apply_end", "final_announce_at"])
    e.table("stage2_score", C0, e.T["job_posting"][1] + e.T["job_posting"][3] + 50, kind="hr")
    e.table("stage_result", C0, e.T["stage2_score"][1] + e.T["stage2_score"][3] + 30, kind="hr")
    e.table("application", C1, 120, kind="cand")
    e.table("application_stage", C1, e.T["application"][1] + e.T["application"][3] + 60, kind="sys")
    e.table("application_stage_log", C1, e.T["application_stage"][1] + e.T["application_stage"][3] + 30, kind="sys")
    e.table("stage_transition", C1, e.T["application_stage_log"][1] + e.T["application_stage_log"][3] + 50, kind="db")
    y = 70
    for k, kind, only in [("document_evaluation", "sys", ["id", "application_id", "version_no", "criteria_scores", "handoff", "model", "status"]),
                          ("coding_session", "sys", None), ("prepared_question", "ai", None), ("llm_call", "ai", None)]:
        e.table(k, C2, y, w=300, kind=kind, only=only)
        y += e.T[k][3] + 28
    e.table("coding_result", C3, e.T["coding_session"][1] - 20, w=300, kind="sys",
            only=["session_id", "q3_tier", "q3_converted", "weakness_summary"])
    e.table("question_bank", C3, e.T["prepared_question"][1] - 10, w=300, kind="ai")
    e.table("company_doc_chunk", C3, e.T["question_bank"][1] + e.T["question_bank"][3] + 40, w=300, kind="ai")
    e.fk("application", "candidate_id", "candidate", C1 - 34)
    e.fk("application", "posting_id", "job_posting", C1 - 22)
    for k in ("document_evaluation", "coding_session", "prepared_question", "llm_call"):
        e.fk(k, "application_id", "application", C2 - 30)
    e.fk("stage2_score", "application_id", "application", C1 - 46, cside="r", pside="l")
    e.fk("stage_result", "application_id", "application", C1 - 58, cside="r", pside="l")
    e.fk("application_stage", "application_id", "application", C1 - 12, cside="l", pside="l")
    e.fk("application_stage_log", "application_id", "application", C1 - 12, cside="l", pside="l")
    e.fk("coding_result", "session_id", "coding_session", C3 - 30)
    e.fk("prepared_question", "bank_id", "question_bank", C3 - 30, cside="r", pside="l")
    # 값 참조 (외래키 아님)
    qx, qy, qw, qh, _ = e.T["question_bank"]
    dx, dy, dw, dh, _ = e.T["company_doc_chunk"]
    b.append(f"<path d='M{qx + qw / 2},{qy + qh} V{dy}' stroke='{MUTED}' stroke-width='1.3' stroke-dasharray='5 4' fill='none' marker-end='url(#a)'/>")
    b.append(text(qx + qw / 2 + 8, (qy + qh + dy) / 2 + 4, "chunk_id = doc#sec (값으로 참조)", 10.5, MUTED, "start"))
    tx, ty_, tw, th, _ = e.T["stage_transition"]
    b.append(text(tx + tw / 2, ty_ - 10, "↑ 단계를 바꿀 때 DB 트리거가 (from, to)를 이 표에서 확인", 10.5, MUTED))
    bot = _bottom(e, "stage_result", "stage_transition", "llm_call", "company_doc_chunk")
    H = bot + 50
    b.append(text(W / 2, H - 16, "llm_call.session_id → interview_session.id 도 있음 (앞 그림). 공고·지원자 테이블은 공통 스키마라 주요 칼럼만 보였습니다.", 12, MUTED))
    b.insert(0, text(W / 2, 34, "지원 건 중심 테이블 관계도 — 공고·지원자 → 지원 건 → 1차·코딩·질문·LLM·단계·2차 종합", 19, NAVY, weight=700))
    return svg(W, H, b)


# ---------- DB: 조회 경로 (어느 칼럼을 통해 들어가는지) ----------
def path_fig(title, steps, sub=None):
    """steps: [(테이블, 종류, [보여 줄 칼럼], 설명, 다음으로 가는 조인 글 or None)] 위에서 아래로"""
    W, CW, CH, GAP, X = 1500, 860, 74, 70, 60
    H = 90 + len(steps) * CH + (len(steps) - 1) * GAP + 40
    b = [text(W / 2, 34, title, 19, NAVY, weight=700)]
    if sub:
        b.append(text(W / 2, 58, sub, 12.5, MUTED))
    y = 80
    for i, (t, kind, cols, desc, join) in enumerate(steps):
        fill, stroke = FILL[kind]
        b.append(f"<rect x='{X}' y='{y}' width='{CW}' height='{CH}' rx='8' fill='white' stroke='{stroke}' stroke-width='1.6'/>")
        b.append(f"<rect x='{X}' y='{y}' width='230' height='{CH}' rx='8' fill='{stroke}'/>")
        b.append(f"<rect x='{X + 222}' y='{y}' width='8' height='{CH}' fill='{stroke}'/>")
        b.append(text(X + 115, y + CH / 2 + 6, t, 15, "white", weight=700))
        cx = X + 246
        for c in cols:
            tag = "🔑" if c.startswith("*") else "🔗" if c.startswith("+") else ""
            name = c.lstrip("*+")
            w = 7.6 * len(name) + (36 if tag else 18)
            col = "#fde68a" if tag == "🔑" else "#e0e7ff" if tag == "🔗" else "#f1f5f9"
            b.append(f"<rect x='{cx}' y='{y + 22}' width='{w}' height='30' rx='15' fill='{col}'/>")
            b.append(text(cx + (26 if tag else 9), y + 42, name, 13, INK, "start", weight=600 if tag else 400))
            if tag:
                b.append(f"<text x='{cx + 9}' y='{y + 42}' font-size='11'>{tag}</text>")
            cx += w + 8
        b.append(text(X + CW + 24, y + CH / 2 + 5, desc, 13, MUTED, "start"))
        if join:
            y2 = y + CH + GAP
            b.append(f"<path d='M{X + 115},{y + CH} V{y2}' stroke='{BRAND}' stroke-width='2' fill='none' marker-end='url(#ab)'/>")
            b.append(f"<rect x='{X + 135}' y='{y + CH + 20}' width='{min(1300, 9 * len(join) + 30)}' height='30' rx='6' fill='#f1f0fe'/>")
            b.append(f"<text x='{X + 150}' y='{y + CH + 40}' font-size='13' fill='{NAVY}' font-family='Consolas, monospace' font-weight='600'>{esc(join)}</text>")
        y += CH + GAP
    return svg(W, H, b)


def path_candidate_answer():
    return path_fig("조회 경로 ① 지원자 → 지원 건 → 응시 → 질문 → 답변 → 판정", [
        ("candidate", "cand", ["*id", "email", "name"], "지원자 계정", "JOIN application a ON a.candidate_id = candidate.id   (1 : N)"),
        ("application", "cand", ["*id", "+candidate_id", "+posting_id", "status"], "지원 건 — 공고마다 하나", "JOIN interview_session s ON s.application_id = a.id   (1 : N, 최대 3차)"),
        ("interview_session", "ai", ["*id", "+application_id", "attempt_no", "status"], "응시 1회", "JOIN interview_question q ON q.session_id = s.id   (1 : N, 10문항)"),
        ("interview_question", "ai", ["*id", "+session_id", "ask_order", "+parent_question_id"], "물어본 질문 (번호 = 순서)", "JOIN interview_answer ans ON ans.question_id = q.id   (1 : 1)"),
        ("interview_answer", "ai", ["*id", "+question_id", "stt_text", "stt_edit_ratio"], "답변 글 (음성은 STT 뒤 삭제)", "JOIN answer_judgement j ON j.answer_id = ans.id AND j.is_current   (현재 판정 1개)"),
        ("answer_judgement", "ai", ["*id", "+answer_id", "score", "rubric", "quotes"], "판정 점수·루브릭·인용", None)],
        "지원자 한 명의 면접 문항별 답변과 점수를 찾을 때 지나는 길")


def path_posting_setting():
    return path_fig("조회 경로 ② 공고 → 면접 설정 / 공고 → 지원 건 → 2차 종합", [
        ("job_posting", "hr", ["*id", "title", "headcount"], "채용 공고", "JOIN interview_setting st ON st.posting_id = job_posting.id   (1 : 1)"),
        ("interview_setting", "hr", ["*+posting_id", "follow_score", "retry_score", "locked_at"], "공고별 면접 설정 (첫 응시 후 잠김)", None)],
        "공고의 면접 규칙과 합격 판단 재료")


def path_score():
    return path_fig("조회 경로 ③ 응시 → 최종 평가 → 5검사 / 지원 건 → 2차 종합 점수", [
        ("application", "cand", ["*id", "+posting_id"], "지원 건", "JOIN interview_session s ON s.application_id = application.id"),
        ("interview_session", "ai", ["*id", "+application_id"], "응시", "JOIN interview_evaluation e ON e.session_id = s.id   (버전 1·2)"),
        ("interview_evaluation", "ai", ["*id", "+session_id", "version_no", "total_score", "status"], "최종 평가 (검증 통과만 확정)", "JOIN evaluation_check c ON c.evaluation_id = e.id   (5개)"),
        ("evaluation_check", "ai", ["*id", "+evaluation_id", "check_no", "passed"], "5검사 결과", None),
        ("stage2_score", "hr", ["*+application_id", "interview_score", "coding_score", "total_score", "ai_rank"], "확정하면 생김: stage2_score.application_id = application.id (1 : 1)", None)],
        "면접 점수가 2차 종합 점수가 되기까지")


def path_coding():
    return path_fig("조회 경로 ④ 코딩 테스트 → 면접 3번 질문", [
        ("application", "cand", ["*id"], "지원 건", "JOIN coding_session cs ON cs.application_id = application.id"),
        ("coding_session", "sys", ["*id", "+application_id", "status"], "코딩 응시", "JOIN coding_result cr ON cr.session_id = cs.id   (1 : 1)"),
        ("coding_result", "sys", ["*+session_id", "q3_tier", "weakness_summary"], "등급·약점 요약", "interview_session.coding_session_id = cs.id  (+ 시작 때 weakness_summary를 coding_weakness로 복사)"),
        ("interview_session", "ai", ["*id", "+coding_session_id", "coding_weakness", "ct_band"], "3번 질문 입력, 난이도 대역 고정", None)],
        "외래키로 연결하고, 면접 도중 바뀌지 않게 값도 복사합니다")


def path_question_source():
    return path_fig("조회 경로 ⑤ 질문 은행 → 미리 만든 질문 → 실제 질문 → 근거 문서", [
        ("question_bank", "ai", ["*id", "job_role", "topic", "chunk_id"], "직무별 본 질문 은행", "JOIN prepared_question p ON p.bank_id = question_bank.id   (1 : N)"),
        ("prepared_question", "ai", ["*id", "+application_id", "+bank_id", "slot", "status"], "지원 건마다 미리 만든 질문 (검증 통과분)", "면접 때 꺼내 interview_question에 새 행으로 (값 복사)"),
        ("interview_question", "ai", ["*id", "source_doc_ids", "min_tier"], "실제로 물어본 질문", "source_doc_ids의 'doc#sec' = company_doc_chunk (doc, sec)   (외래키 없음, 값으로 참조)"),
        ("company_doc_chunk", "ai", ["*doc", "*sec", "tier", "topic", "forbid"], "회사 문서 청크 (임베딩 1024)", None)],
        "질문의 근거를 거꾸로 따라가는 길")


def path_proctor():
    return path_fig("조회 경로 ⑥ 응시 → 감독 이벤트 → 의심 건 → 담당자 결정", [
        ("interview_session", "ai", ["*id", "+application_id"], "응시", "JOIN proctor_event pe ON pe.session_id = s.id   (pe.question_id 로 문항까지)"),
        ("proctor_event", "sys", ["*id", "+session_id", "+question_id", "event_type"], "탭 이탈·얼굴 없음 등", "JOIN suspicion_case sc ON sc.interview_session_id = s.id"),
        ("suspicion_case", "hr", ["*id", "+interview_session_id", "+application_id", "+decided_by", "status"], "의심 건 (자동 불합격 없음)", "JOIN admin_user u ON u.id = sc.decided_by"),
        ("admin_user", "hr", ["*id", "login_id", "name", "role"], "결정한 담당자", None)],
        "감독 기록에서 담당자 결정까지")


# ---------- 워크플로우 안쪽 흐름 ----------
def flow(title, rows, sub=None, H=None):
    """rows: [[(종류, [글], 아래 갈래 (라벨, 종류, [글]) or None), ...], ...] 줄마다 왼쪽 → 오른쪽, 줄 끝에서 다음 줄 처음으로"""
    W, BW, BH, GX, X0 = 1500, 230, 96, 48, 40
    rowh = 300
    H = H or 100 + len(rows) * rowh
    b = [text(W / 2, 34, title, 19, NAVY, weight=700)]
    if sub:
        b.append(text(W / 2, 58, sub, 12.5, MUTED))
    prev = None
    for r, row in enumerate(rows):
        y = 90 + r * rowh
        for i, (kind, lines, br) in enumerate(row):
            x = X0 + i * (BW + GX)
            b.append(box(x, y, BW, BH, lines, kind, 13.5))
            if prev:
                px, py = prev
                if py == y:
                    b.append(arrow([(px + BW, y + BH / 2), (x, y + BH / 2)]))
                else:
                    lane = py + rowh - 28   # 갈래 상자 아래로 돌아서 다음 줄로
                    b.append(arrow([(px + BW, py + BH / 2), (px + BW + 22, py + BH / 2), (px + BW + 22, lane), (x + BW / 2, lane), (x + BW / 2, y)], MUTED))
            if br:
                lab, k2, l2 = br
                by = y + BH + 70
                b.append(box(x + 10, by, BW - 20, 84, l2, k2, 12.5))
                b.append(arrow([(x + BW / 2, y + BH), (x + BW / 2, by)], DAWN if k2 in ("hr", "db") else BRAND, marker="a" if k2 in ("hr", "db") else "ab"))
                b.append(f"<rect x='{x + BW / 2 + 6}' y='{y + BH + 22}' width='{12 * len(lab) + 10}' height='20' rx='5' fill='white'/>")
                b.append(text(x + BW / 2 + 10, y + BH + 37, lab, 11.5, DAWN if k2 in ("hr", "db") else BRAND, "start", 600))
            prev = (x, y)
    b.append(legend(380, H - 30, [("cand", "지원자"), ("ai", "AI·LLM"), ("code", "코드"), ("hr", "담당자"), ("db", "예외·다른 길")]))
    return svg(W, H, b)


def wf_doc():
    return flow("안쪽 흐름 ① 1차 서류 — AI는 근거만, 결정은 담당자", [[
        ("cand", ["지원서 제출", "이력서 스냅숏 저장"], None),
        ("code", ["평가 기준", "공고의 필수·우대 요건"], None),
        ("ai", ["비교 문서 검색", "요건별 이력서 문장 찾기"], None),
        ("ai", ["AI 의견", "요건별 라벨 + 원문 인용"], None),
        ("code", ["코드 검증", "인용이 원문에 있나 · 결론 규칙"], ("검증 실패", "db", ["결론 칸 비움", "(빈칸 = 담당자 판단)"])),
    ], [
        ("code", ["추천 정하기", "지원자의 30%까지 '추천'"], None),
        ("hr", ["담당자 검토", "근거·의견 보고 합격 체크", "(비추천은 체크 불가)"], None),
        ("hr", ["'결정 확인' 한 번", "체크 = 합격, 나머지 불합격"], None),
        ("code", ["발표 · 알림", "메일·문자·홈페이지", "단계 이동 · 인계 데이터"], ("합격이면", "ai", ["질문 미리 만들기", "1·2번 + 본 질문 후보"])),
    ]], "점수·하드 필터 없음 (11/12). 발표 뒤 합격 취소는 부정행위일 때만, 사유 필수", H=720)


def wf_qgen():
    return flow("안쪽 흐름 ② 질문 만들기 — 미리 만들기 + 면접 중 꼬리·재질문", [[
        ("code", ["1차 합격 즉시", "질문 은행에서 직무·이력서", "경험과 겹치는 주제 고르기"], None),
        ("ai", ["질문 쓰기 (LLM 관문)", "tier 3 근거 · 외부 모델"], None),
        ("code", ["검증 7가지", "길이·베끼기·금지어·개인정보", "문서 번호·근거·중복"], ("떨어지면", "db", ["1번 다시 → 또 떨어지면", "은행의 기본 질문"])),
        ("code", ["prepared_question 저장", "1·2번 + 본 질문 후보"], None),
        ("code", ["코딩이 끝나면", "약점 요약으로 3번 질문", "(같은 검증)"], None),
    ], [
        ("code", ["면접 중 decide", "70점↑ 깊이<2 → 꼬리", "본 질문 40점↓ → 재질문"], None),
        ("ai", ["꼬리질문 근거 검색", "직전 답변 원문으로", "깊이1 tier 2 · 깊이2 tier 1"], None),
        ("ai", ["꼬리질문 쓰기", "사내 모델 (tier 1·2)", "글 칸 길이 고정"], None),
        ("code", ["guard", "금지어 · NLI 모순 검사"], ("탈락하면", "db", ["1번 고쳐 쓰기 → 또 탈락", "'신뢰도 낮음' 표시"])),
        ("cand", ["화면에 표시", "질문 음성(TTS) + 글"], None),
    ]], "본 질문은 미리, 꼬리·재질문은 답변을 봐야 해서 면접 중에 만듭니다", H=720)


def wf_judge():
    return flow("안쪽 흐름 ③ 답변 판정과 LLM 호출 관문", [[
        ("cand", ["인식 글 확인", "틀린 곳만 고침 (30%·60초)"], None),
        ("code", ["프롬프트 조립", "api/prompts/*.md", "빈 변수면 멈춤"], None),
        ("code", ["개인정보 가림", "이름·학교·주소·연락처", "답변 속까지"], None),
        ("code", ["경로 정하기", "근거에 tier 1·2 → 사내", "tier 3만 → 외부"], ("외부면", "db", ["누출 검사", "걸리면 가리고 다시 →", "또 걸리면 사내로"])),
        ("ai", ["판정 호출", "루브릭 30·30·25·15", "이유 먼저, 점수 나중"], None),
    ], [
        ("code", ["시간 확인", "30초 → 대체 모델", "60초 → 점수 보류"], None),
        ("code", ["형식 확인", "틀리면 오류를 붙여 1번 더"], ("또 틀리면", "db", ["parse_error", "점수 보류 · 다음 주제"])),
        ("code", ["인용 확인", "답변 원문에 있는 것만"], None),
        ("ai", ["관련성 (CE)", "점수엔 안 더함", "0.4 미만이면 재질문"], None),
        ("code", ["기록", "answer_judgement", "llm_call (본문 없이)"], None),
    ]], "모든 LLM 호출은 api/llm_gate.call() 한 곳을 지납니다", H=720)


def wf_final():
    return flow("안쪽 흐름 ④ 최종 평가 → 확정 → 2차 종합 → 최종 결정", [[
        ("code", ["10문항 끝", "주제별로 묶기"], None),
        ("code", ["주제 점수", "깊이(0·30·60)", "+ 40 × 평균 / 100"], None),
        ("code", ["최종 평가 v1", "내용 60 · 언어 30 · 비언어 10"], None),
        ("ai", ["5검사", "1~4 코드 · 5 사내 모델", "(근거–점수 정합)"], ("실패", "db", ["재평가 v2 →", "또 실패면 담당자 알림", "(확정 불가)"])),
        ("hr", ["담당자 리포트 검토", "의심 건 처리 · 메모"], None),
    ], [
        ("hr", ["'평가 확정'", "검증 통과 버전만"], None),
        ("code", ["2차 종합", "면접 60% + 코딩 40%", "면접<50·코딩<40 과락"], None),
        ("code", ["AI 순위·추천", "과락 아닌 사람 중", "모집 인원 × 2까지"], None),
        ("hr", ["최종 합격 체크", "과락·미결 의심 건은 불가"], None),
        ("hr", ["'결과 확정' 한 번", "합격·불합격 + 알림", "(바꿀 수 없음)"], ("발표 뒤", "cand", ["지원자 화면", "축하 · 감사 인사"])),
    ]], "AI는 점수와 추천까지, 확정과 합격 결정은 담당자", H=720)


ALL = {"wf_overall": wf_overall, "wf_graph": wf_graph, "wf_question": wf_question, "wf_stages": wf_stages,
       "erd_overview": erd_overview, "erd_interview": erd_interview, "erd_interview2": erd_interview2, "erd_support": erd_support,
       "path_1": path_candidate_answer, "path_2": path_posting_setting, "path_3": path_score, "path_4": path_coding,
       "path_5": path_question_source, "path_6": path_proctor,
       "wf_doc": wf_doc, "wf_qgen": wf_qgen, "wf_judge": wf_judge, "wf_final": wf_final}

if __name__ == "__main__":
    os.makedirs(FIG, exist_ok=True)
    for name, f in ALL.items():
        open(os.path.join(FIG, f"{name}.svg"), "w", encoding="utf-8").write(f())
    subprocess.run(["node", "scripts/svg2png.mjs", os.path.abspath(FIG)], cwd=os.path.join(ROOT, "web"), check=True, shell=os.name == "nt")
    print("저장:", FIG)
