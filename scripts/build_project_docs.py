"""최종 문서 PDF·Word (11/17, 실제 구현 기준 v1.0). PC(호스트)에서 실행.
  python scripts/build_project_docs.py            → docs/최종/ 에 PRD·TRD·화면정의서·테스트 결과서 (.pdf + .docx)
  python scripts/build_project_docs.py PRD        → 한 문서만

- 글은 docs/최종/src/*.md (아래 '쓰는 법'의 작은 마크다운), 화면정의서는 records/screens.py에서 만든다.
- PDF: HTML → Chrome 인쇄(web/scripts/pdf.mjs). Word: python-docx (PC 파이썬에만 설치, 프로젝트 버전 고정과 무관)
- 사진은 가장 최근 E2E가 찍은 web/e2e/screenshots, E2E에 없는 화면은 records/docs/extra

쓰는 법 (src/*.md)
  # 제목            문서 안 큰 장 (목차에 들어감)       ## 소제목            ### 작은 제목
  - 항목            글머리 목록                         1. 항목              번호 목록
  | a | b |         표 (첫 줄이 머리, 둘째 줄 |---| 는 생략 가능)
  > 글              알림 상자 (설계에서 바뀐 이유 등)
  ![설명](shot:27-admin-detail.png)  사진 (shot: = e2e/screenshots, extra: = records/docs/extra)
  {변경 11/12} {신규 11/12} {삭제 11/16}  색 표시 (원본 설계 11/4 대비)
  **굵게**  `코드`
  ---               쪽 나눔
  첫 줄 메타: @title 문서 제목 / @code 문서 번호 / @summary 한 줄 요약
"""
import html
import importlib.util
import os
import re
import struct
import subprocess
import sys
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "최종")
SRC = os.path.join(OUT, "src")
SHOTS = os.path.join(ROOT, "web", "e2e", "screenshots")
EXTRA = os.path.join(ROOT, "records", "docs", "extra")
FIG = os.path.join(SRC, "fig")   # scripts/build_diagrams.py가 만든 그림 (워크플로우·DB 관계도)
VERSION = "v1.0"
TODAY = date(2026, 11, 17)
PROJECT = "6.1 실시간 AI 화상면접 · 가상 회사 새벽소프트"
HISTORY = [("v0.1", "2026-11-04", "설계 (PRD·TRD·화면정의서 원본, 구현 전)"),
           ("v0.5", "2026-11-09", "활동다이어그램 1109 반영 (LangGraph 구조, LLM 호출 관문, 국외 전송 동의 필수)"),
           ("v0.8", "2026-11-12", "AI 활용 고지, 연습 면접, 글로 답하기, 라이브니스, 기록 180일 파기, 1차 하드 필터 제거"),
           ("v1.0", "2026-11-17", "실제 구현 기준으로 다시 씀 (얼굴 대조 InsightFace, 사내 모델 형식 고정, 측정 결과, 화면 정리)")]
DOCS = {  # 키: (원본 파일, 문서 번호)
    "PRD": "화상면접_PRD_6.1", "TRD": "화상면접_TRD_6.1", "화면정의서": "화상면접_화면정의서_6.1", "테스트결과서": "화상면접_테스트결과서_6.1",
    "워크플로우": "화상면접_워크플로우_6.1", "DB설계서": "화상면접_DB설계서_6.1",
}
TAG = {"변경": ("#b45309", "#fef3c7"), "신규": ("#047857", "#d1fae5"), "삭제": ("#b91c1c", "#fee2e2")}


# ---------- 읽기: 작은 마크다운 → 블록 ----------
def parse(text: str) -> tuple[dict, list[tuple]]:
    meta, blocks, para, lines = {}, [], [], text.splitlines()

    def flush():
        if para:
            blocks.append(("p", " ".join(para)))
            para.clear()
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.startswith("@"):
            k, _, v = ln[1:].partition(" ")
            meta[k] = v.strip()
        elif not ln.strip():
            flush()
        elif ln.startswith("```"):   # 코드 블록 (SQL 예시 등)
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append(("code", "\n".join(code)))
        elif ln.strip() == "---":
            flush()
            blocks.append(("break",))
        elif m := re.match(r"^(#{1,3}) (.+)", ln):
            flush()
            blocks.append((f"h{len(m.group(1))}", m.group(2)))
        elif ln.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
            continue
        elif re.match(r"^(- |\d+\. )", ln):
            flush()
            ordered, items = bool(re.match(r"^\d+\. ", ln)), []
            while i < len(lines) and re.match(r"^(- |\d+\. |  \S)", lines[i]):
                s = lines[i]
                if s.startswith("  ") and items:
                    items[-1] += " " + s.strip()
                else:
                    items.append(re.sub(r"^(- |\d+\. )", "", s))
                i += 1
            blocks.append(("ol" if ordered else "ul", items))
            continue
        elif ln.startswith("> "):
            flush()
            box = []
            while i < len(lines) and lines[i].startswith(">"):
                box.append(lines[i][1:].strip())
                i += 1
            blocks.append(("note", " ".join(box)))
            continue
        elif m := re.match(r"^!\[(.*)\]\((shot|extra|fig):(.+)\)$", ln.strip()):
            flush()
            blocks.append(("img", os.path.join({"shot": SHOTS, "extra": EXTRA, "fig": FIG}[m.group(2)], m.group(3)), m.group(1)))
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return meta, blocks


# 줄 안 꾸밈: {변경 11/12} · **굵게** · `코드`
INLINE = re.compile(r"\{(변경|신규|삭제)([^}]*)\}|\*\*(.+?)\*\*|`(.+?)`")


def runs(text: str):
    """[(종류, 글)] 종류: t 글 · b 굵게 · c 코드 · 변경/신규/삭제"""
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append(("t", text[pos:m.start()]))
        if m.group(1):
            out.append((m.group(1), (m.group(1) + m.group(2)).strip()))
        elif m.group(3):
            out.append(("b", m.group(3)))
        else:
            out.append(("c", m.group(4)))
        pos = m.end()
    if pos < len(text):
        out.append(("t", text[pos:]))
    return out


# ---------- HTML (→ PDF) ----------
CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; color: #1f2937; font-size: 10.5pt; line-height: 1.6; margin: 0; word-break: keep-all; }
.cover { height: 255mm; display: flex; flex-direction: column; justify-content: space-between; padding: 30mm 6mm 6mm; page-break-after: always; }
.cover .kicker { color: #5f59e0; font-weight: 700; letter-spacing: .04em; font-size: 11pt; }
.cover h1 { font-size: 28pt; margin: 6mm 0 3mm; color: #2a2857; line-height: 1.25; }
.cover .sum { font-size: 12pt; color: #4b5563; max-width: 150mm; }
.cover table { width: 100%; }
h1.sec { font-size: 16pt; color: #2a2857; border-bottom: 2px solid #5f59e0; padding-bottom: 2mm; margin: 9mm 0 4mm; page-break-after: avoid; }
h2 { font-size: 12.5pt; color: #2a2857; margin: 6mm 0 2mm; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 4mm 0 1.5mm; page-break-after: avoid; }
p { margin: 0 0 2.5mm; }
ul, ol { margin: 0 0 3mm; padding-left: 6mm; } li { margin-bottom: 1mm; }
table { border-collapse: collapse; width: 100%; margin: 1mm 0 4mm; font-size: 9.5pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #dcd9ea; padding: 1.6mm 2.2mm; text-align: left; vertical-align: top; }
th { background: #f1f0fe; color: #2a2857; font-weight: 700; }
.note { background: #f8f7fc; border-left: 3px solid #5f59e0; padding: 2.5mm 4mm; margin: 2mm 0 4mm; border-radius: 0 6px 6px 0; font-size: 10pt; }
.tag { display: inline-block; font-size: 8pt; font-weight: 700; padding: 0 1.8mm; border-radius: 99px; margin: 0 .8mm; white-space: nowrap; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f1f0f8; padding: 0 1mm; border-radius: 3px; }
figure { margin: 2mm 0 5mm; page-break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 120mm; border: 1px solid #dcd9ea; border-radius: 6px; }
figcaption { font-size: 9pt; color: #6b7280; margin-top: 1mm; }
.toc { page-break-after: always; } .toc h1 { font-size: 16pt; color: #2a2857; } .toc ol { font-size: 11pt; line-height: 2; }
.brk { page-break-after: always; }
pre.code { background: #1f2340; color: #e6e8f5; font-family: Consolas, monospace; font-size: 9pt; line-height: 1.5; padding: 3mm 4mm; border-radius: 6px; white-space: pre-wrap; page-break-inside: avoid; margin: 1mm 0 4mm; }
thead { display: table-header-group; }
.hist td:first-child, .hist td:nth-child(2) { white-space: nowrap; }
"""


def inline_html(text: str) -> str:
    out = []
    for k, t in runs(text):
        if k == "t":
            out.append(html.escape(t))
        elif k == "b":
            out.append(f"<b>{html.escape(t)}</b>")
        elif k == "c":
            out.append(f"<code>{html.escape(t)}</code>")
        else:
            fg, bg = TAG[k]
            out.append(f"<span class='tag' style='color:{fg};background:{bg}'>{html.escape(t)}</span>")
    return "".join(out)


def cover_rows(meta: dict, code: str) -> list[list[str]]:
    return [["문서 번호", code], ["버전", f"{VERSION} (실제 구현 기준)"], ["작성일", TODAY.isoformat()], ["프로젝트", PROJECT],
            ["원본", "v0.1 설계 문서 (2026-11-04). 원본 목차를 따르고, 바뀐 곳에 {변경}·{신규}·{삭제} 표시"]]


def to_html(meta: dict, blocks: list[tuple], code: str, wide: bool = False) -> str:
    title = meta.get("title", code)
    cov = "".join(f"<tr><th style='width:32mm'>{html.escape(k)}</th><td>{inline_html(v)}</td></tr>" for k, v in cover_rows(meta, code))
    hist = "".join(f"<tr><td>{v}</td><td>{d}</td><td>{html.escape(n)}</td></tr>" for v, d, n in HISTORY)
    secs = [b[1] for b in blocks if b[0] == "h1"]
    body = [f"""<section class='cover'><div><div class='kicker'>{html.escape(PROJECT)}</div><h1>{html.escape(title)}</h1>
<p class='sum'>{inline_html(meta.get('summary', ''))}</p></div>
<div><table>{cov}</table><h3>개정 이력</h3><table class='hist'><tr><th>버전</th><th>날짜</th><th>내용</th></tr>{hist}</table></div></section>"""]
    if len(secs) > 3:
        items = "".join("<li>" + inline_html(re.sub(r"^\d+\.\s*", "", t)) + "</li>" for t in secs)
        body.append(f"<section class='toc'><h1>목차</h1><ol>{items}</ol></section>")
    for b in blocks:
        k = b[0]
        if k == "h1":
            body.append(f"<h1 class='sec'>{inline_html(b[1])}</h1>")
        elif k in ("h2", "h3"):
            body.append(f"<{k}>{inline_html(b[1])}</{k}>")
        elif k == "p":
            body.append(f"<p>{inline_html(b[1])}</p>")
        elif k in ("ul", "ol"):
            body.append(f"<{k}>" + "".join(f"<li>{inline_html(x)}</li>" for x in b[1]) + f"</{k}>")
        elif k == "note":
            body.append(f"<div class='note'>{inline_html(b[1])}</div>")
        elif k == "table":
            head, *rows = b[1]
            body.append("<table><thead><tr>" + "".join(f"<th>{inline_html(c)}</th>" for c in head) + "</tr></thead>"
                        + "".join("<tr>" + "".join(f"<td{' style=white-space:nowrap' if len(c) <= 8 else ''}>{inline_html(c)}</td>" for c in r) + "</tr>"
                                  for r in rows) + "</table>")   # 짧은 칸(ID·번호·날짜)은 줄바꿈하지 않음
        elif k == "img":
            if os.path.exists(b[1]):
                body.append(f"<figure><img src='file:///{b[1].replace(os.sep, '/')}'><figcaption>{inline_html(b[2])}</figcaption></figure>")
        elif k == "code":
            body.append(f"<pre class='code'>{html.escape(b[1])}</pre>")
        elif k == "break":
            body.append("<div class='brk'></div>")
    css = CSS + ("@page { size: A4 landscape; } .cover { height: auto; padding: 10mm 6mm 0; justify-content: flex-start; gap: 8mm; } .cover h1 { margin: 3mm 0 2mm; } figure img { max-height: 138mm; }" if wide else "")
    return f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body>{''.join(body)}</body></html>"


def to_pdf(html_text: str, name: str, wide: bool = False) -> str:
    tmp = os.path.join(OUT, f".{name}.html")
    open(tmp, "w", encoding="utf-8").write(html_text)
    pdf = os.path.join(OUT, f"{name}.pdf")
    subprocess.run(["node", "scripts/pdf.mjs", os.path.abspath(tmp), os.path.abspath(pdf)] + (["landscape"] if wide else []), cwd=os.path.join(ROOT, "web"), check=True,
                   stdout=subprocess.DEVNULL, shell=os.name == "nt")
    if not os.environ.get("DOCS_KEEP_HTML"):   # 모양 확인용으로 남기기
        os.remove(tmp)
    return pdf


def png_size(path: str) -> tuple[int, int]:
    """PNG 머리에서 가로·세로 (PIL 없이)"""
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


# ---------- Word ----------
def to_docx(meta: dict, blocks: list[tuple], code: str, wide: bool = False) -> str:
    from docx import Document
    from docx.enum.section import WD_ORIENT  # noqa: F401
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = (Mm(210), Mm(297)) if wide else (Mm(297), Mm(210))
    if wide:
        from docx.enum.section import WD_ORIENT
        sec.orientation = WD_ORIENT.LANDSCAPE
    full = 255 if wide else 170   # 본문 폭 mm
    sec.left_margin = sec.right_margin = Mm(18)
    sec.top_margin = sec.bottom_margin = Mm(16)
    FONT = "Malgun Gothic"
    for st in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Title", "List Bullet", "List Number"):
        s = doc.styles[st]
        s.font.name = FONT
        rpr = s.element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.append(fonts)
        for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            fonts.set(qn(a), FONT)
    doc.styles["Normal"].font.size = Pt(10)
    navy, brand = RGBColor(0x2A, 0x28, 0x57), RGBColor(0x5F, 0x59, 0xE0)
    for st, size in (("Heading 1", 15), ("Heading 2", 12.5), ("Heading 3", 11)):
        doc.styles[st].font.size = Pt(size)
        doc.styles[st].font.color.rgb = navy

    def shade(cell, hexfill):
        tcPr = cell._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear")
        sh.set(qn("w:color"), "auto")
        sh.set(qn("w:fill"), hexfill)
        tcPr.append(sh)

    def add_runs(par, text, size=None, bold=False):
        for k, t in runs(text):
            r = par.add_run(t if k in ("t", "b", "c") else f" {t} ")
            r.bold = bold or k in ("b", "변경", "신규", "삭제")
            if size:
                r.font.size = Pt(size)
            if k == "c":
                r.font.name = "Consolas"
            if k in TAG:
                fg = TAG[k][0].lstrip("#")
                r.font.color.rgb = RGBColor.from_string(fg.upper())
                r.font.size = Pt(8)
                rpr = r._r.get_or_add_rPr()
                hl = OxmlElement("w:shd")
                hl.set(qn("w:val"), "clear")
                hl.set(qn("w:fill"), TAG[k][1].lstrip("#"))
                rpr.append(hl)

    def table(rows, widths=None):
        t = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for ri, r in enumerate(rows):
            for ci, c in enumerate(r):
                cell = t.cell(ri, ci)
                cell.paragraphs[0].text = ""
                add_runs(cell.paragraphs[0], c, size=9, bold=ri == 0)
                if ri == 0:
                    shade(cell, "F1F0FE")
        if widths:
            for ri in range(len(rows)):
                for ci, w in enumerate(widths):
                    t.cell(ri, ci).width = Mm(w)
        doc.add_paragraph()
        return t

    # 표지
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(90)
    r = p.add_run(PROJECT)
    r.font.color.rgb, r.bold = brand, True
    p = doc.add_paragraph()
    r = p.add_run(meta.get("title", code))
    r.font.size, r.bold, r.font.color.rgb = Pt(26), True, navy
    add_runs(doc.add_paragraph(), meta.get("summary", ""), size=11.5)
    doc.add_paragraph()
    table([["항목", "내용"]] + cover_rows(meta, code), widths=[34, 140])
    doc.add_paragraph().add_run("개정 이력").bold = True
    table([["버전", "날짜", "내용"]] + [list(h) for h in HISTORY], widths=[18, 26, 130])
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    for b in blocks:
        k = b[0]
        if k in ("h1", "h2", "h3"):
            h = doc.add_heading(level=int(k[1]))
            add_runs(h, b[1])
        elif k == "p":
            add_runs(doc.add_paragraph(), b[1])
        elif k in ("ul", "ol"):
            for x in b[1]:
                add_runs(doc.add_paragraph(style="List Bullet" if k == "ul" else "List Number"), x)
        elif k == "note":
            t = doc.add_table(rows=1, cols=1)
            c = t.cell(0, 0)
            shade(c, "F8F7FC")
            add_runs(c.paragraphs[0], b[1], size=9.5)
            doc.add_paragraph()
        elif k == "table":
            table(b[1])
        elif k == "img" and os.path.exists(b[1]):
            w, hgt = png_size(b[1])
            maxh = 138 if wide else 120
            width = Mm(min(full, maxh * w / hgt))
            doc.add_picture(b[1], width=width)
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap = doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_runs(cap, b[2], size=9)
        elif k == "code":
            t = doc.add_table(rows=1, cols=1)
            c = t.cell(0, 0)
            shade(c, "1F2340")
            c.paragraphs[0].text = ""
            for li, line in enumerate(b[1].split("\n")):
                par = c.paragraphs[0] if li == 0 else c.add_paragraph()
                r = par.add_run(line)
                r.font.name, r.font.size = "Consolas", Pt(8.5)
                r.font.color.rgb = RGBColor(0xE6, 0xE8, 0xF5)
                par.paragraph_format.space_after = Pt(0)
            doc.add_paragraph()
        elif k == "break":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # 바닥글: 쪽 번호
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.add_run(f"{meta.get('title', code)} {VERSION}  ·  ").font.size = Pt(8)
    for code_ in ("PAGE",):
        r = fp.add_run()
        for tag, txt in (("begin", None), (None, code_), ("end", None)):
            if tag:
                e = OxmlElement("w:fldChar")
                e.set(qn("w:fldCharType"), tag)
            else:
                e = OxmlElement("w:instrText")
                e.set(qn("xml:space"), "preserve")
                e.text = txt
            r._r.append(e)
        r.font.size = Pt(8)
    path = os.path.join(OUT, f"{DOCS_NAME}.docx")
    doc.save(path)
    return path


# ---------- 화면정의서: records/screens.py → 블록 ----------
def screens_blocks() -> tuple[dict, list[tuple]]:
    spec = importlib.util.spec_from_file_location("screens", os.path.join(ROOT, "records", "screens.py"))
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    pick = {}
    for f in sorted(os.listdir(SHOTS)):
        pick.setdefault(re.sub(r"^\d+-|\.png$", "", f), os.path.join("shot", f))
    for f in sorted(os.listdir(EXTRA)) if os.path.isdir(EXTRA) else []:
        pick.setdefault(re.sub(r"^\d+-|\.png$", "", f), os.path.join("extra", f))
    n = sum(len(items) for _, items in sc.GROUPS)
    meta = {"title": "화상 면접 화면정의서 (6.1)",
            "summary": f"실제로 구현해 돌아가는 화면 {n}개의 목적·구성·동작·API와 대표 사진. 원본(11/4)의 화상면접 화면 7개에 채용 사이트·코딩 테스트·관리자 화면을 더했습니다."}
    blocks = [("h1", "1. 화면 목록"),
              ("p", "ID는 팀 화면정의서 번호를 따르고, 원본에 없던 화면은 번호를 이어 붙였습니다. 사진은 2026-11-17 자동 화면 시험(E2E)이 실제 서버·모델을 켜고 찍은 것이며, 이름·이력서는 시험용 가상 데이터입니다.")]
    rows = [["ID", "화면", "주소", "사용자"]]
    for _, items in sc.GROUPS:
        rows += [[s[0], s[1], f"`{s[2]}`", s[3]] for s in items]
    blocks.append(("table", rows))
    for gi, (g, items) in enumerate(sc.GROUPS, 2):
        blocks.append(("h1", f"{gi}. {g}"))
        for s in items:
            sid, name, path, user, purpose, parts, rules, apis, shot = s
            blocks.append(("h2", f"{sid} {name}"))
            blocks.append(("table", [["항목", "내용"], ["주소", f"`{path}`"], ["사용자", user], ["목적", purpose], ["관련 API", apis]]))
            blocks.append(("h3", "구성"))
            blocks.append(("ul", parts))
            blocks.append(("h3", "동작·규칙"))
            blocks.append(("ul", rules))
            key = shot and next((v for k, v in pick.items() if k == shot), None)
            if key:
                kind, f = key.split(os.sep, 1) if os.sep in key else key.split("/", 1)
                blocks.append(("img", os.path.join(SHOTS if kind == "shot" else EXTRA, f), f"{sid} {name}"))
            blocks.append(("break",))
    return meta, blocks


DOCS_NAME = ""


def build(key: str) -> list[str]:
    global DOCS_NAME
    DOCS_NAME = DOCS[key]
    if key == "화면정의서":
        meta, blocks = screens_blocks()
    else:
        src = open(os.path.join(SRC, f"{key}.md"), encoding="utf-8").read()
        src = re.sub(r"^@include (\S+)$", lambda m: open(os.path.join(SRC, m.group(1)), encoding="utf-8").read(), src, flags=re.M)   # 자동 생성 조각
        meta, blocks = parse(src)
    code = f"6.1-{ {'PRD': 'PRD', 'TRD': 'TRD', '화면정의서': 'SCR', '테스트결과서': 'TST', '워크플로우': 'WF', 'DB설계서': 'DB'}[key]}"
    wide = meta.get("landscape") == "yes"   # 넓은 그림이 있는 문서는 A4 가로
    return [to_pdf(to_html(meta, blocks, code, wide), DOCS_NAME, wide), to_docx(meta, blocks, code, wide)]


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for k in sys.argv[1:] or list(DOCS):
        for p in build(k):
            print("저장:", p)
