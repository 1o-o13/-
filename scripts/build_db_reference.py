"""DB 설계서의 '외래키 전체 목록'·'테이블 상세'를 실제 DB와 스키마 주석에서 만든다 (11/17).
  python scripts/build_db_reference.py   → docs/최종/src/_db_fk.md · _db_tables.md (DB설계서.md가 @include로 넣는다)
- 외래키·관계(1:1/1:N)·NULL 허용·삭제 동작: 실행 중인 postgres 컨테이너의 시스템 카탈로그
- 칼럼 설명·허용 값: db/interview_schema.sql 의 줄 끝 주석(--)과 CHECK (... IN (...))
"""
import json
import os
import re
import subprocess

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "최종", "src")
SQL = os.path.join(ROOT, "db", "interview_schema.sql")
OWN = ["interview_setting", "interview_session", "interview_question", "interview_answer", "answer_judgement", "answer_signal",
       "interview_evaluation", "evaluation_check", "ai_error_alert", "identity_check", "proctor_event", "suspicion_case",
       "interview_incident", "interview_note", "answer_accommodation", "llm_call", "question_bank", "prepared_question",
       "application_stage", "application_stage_log", "stage_transition"]
GROUP = {"interview_setting": "면접 설정", "interview_session": "응시", "interview_question": "질문", "interview_answer": "답변",
         "answer_judgement": "판정", "answer_signal": "판정", "interview_evaluation": "평가", "evaluation_check": "평가",
         "ai_error_alert": "평가", "identity_check": "본인 확인·감독", "proctor_event": "본인 확인·감독", "suspicion_case": "본인 확인·감독",
         "interview_incident": "장애·메모", "interview_note": "장애·메모", "answer_accommodation": "응시 편의", "llm_call": "질문·LLM",
         "question_bank": "질문·LLM", "prepared_question": "질문·LLM", "application_stage": "단계", "application_stage_log": "단계",
         "stage_transition": "단계"}
TYPE = {"int8": "bigint", "int4": "int", "int2": "smallint", "bool": "boolean", "_text": "text[]"}
DEL = {"c": "같이 삭제 (CASCADE)", "a": "막음 (자식이 있으면 지울 수 없음)", "n": "NULL로 비움", "r": "막음", "d": "기본값으로"}
MEANING = {  # (자식, 칼럼): 뜻. 없으면 칼럼 이름으로 정함
    ("interview_question", "parent_question_id"): "꼬리질문·재질문이 이어지는 원래 질문 (자기 참조)",
    ("interview_session", "coding_session_id"): "3번 질문에 쓸 코딩 응시 (비개발 직군은 비어 있음)",
    ("interview_session", "application_id"): "어느 지원 건의 응시인지 (지원 건당 최대 3차)",
    ("interview_answer", "question_id"): "어느 질문의 답변인지 (질문당 1개, 재녹음 불가)",
    ("answer_judgement", "answer_id"): "어느 답변의 판정인지 (다시 판정하면 새 행, 현재 판정은 1개)",
    ("answer_signal", "answer_id"): "어느 답변의 표정·목소리 구간인지",
    ("interview_evaluation", "session_id"): "어느 응시의 최종 평가인지 (버전 1·2)",
    ("evaluation_check", "evaluation_id"): "어느 평가 버전의 5검사인지",
    ("ai_error_alert", "interview_evaluation_id"): "재평가까지 실패한 평가",
    ("ai_error_alert", "application_id"): "알림이 걸린 지원 건",
    ("proctor_event", "question_id"): "감독 이벤트가 생긴 문항",
    ("suspicion_case", "interview_session_id"): "면접 중 생긴 의심 건이면 그 응시",
    ("prepared_question", "bank_id"): "질문 은행에서 꺼낸 질문이면 그 은행 질문",
    ("prepared_question", "application_id"): "어느 지원 건을 위해 미리 만든 질문인지",
    ("llm_call", "session_id"): "면접 중 호출이면 그 응시",
    ("llm_call", "application_id"): "어느 지원 건을 위한 호출인지",
    ("interview_setting", "posting_id"): "어느 공고의 면접 설정인지 (공고와 1 : 1)",
    ("job_posting", "hiring_request_id"): "부서 채용 요청에서 만든 공고면 그 요청",
    ("coding_attempt", "problem_id"): "푼 문제",
    ("interview_session", "id"): "",
}


def psql(q: str):
    out = subprocess.run(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "recruit", "-d", "recruit", "-At", "-c", q],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    return json.loads(out or "[]")


def meaning(child: str, col: str, parent: str) -> str:
    if (child, col) in MEANING:
        return MEANING[(child, col)]
    if parent == "admin_user":
        return "처리·작성한 관리자"
    return {"application": "어느 지원 건의 것인지", "candidate": "어느 지원자의 것인지", "job_posting": "어느 공고의 것인지",
            "interview_session": "어느 응시의 기록인지", "coding_session": "어느 코딩 응시의 것인지", "coding_attempt": "어느 문제 풀이의 것인지",
            "coding_problem": "어느 문제의 것인지", "department": "어느 부서인지", "announcement": "어느 발표의 알림인지",
            "consent_document": "어느 동의서 버전에 동의했는지", "interview_question": "어느 질문의 것인지"}.get(parent, "")


def build_fk():
    fks = psql("""select json_agg(row_to_json(x)) from (
      select cl.relname child, a.attname col, pc.relname parent, pa.attname pcol, c.confdeltype del,
        (select is_nullable = 'YES' from information_schema.columns where table_name = cl.relname and column_name = a.attname) nul,
        exists(select 1 from pg_constraint u where u.conrelid = c.conrelid and u.contype in ('p','u') and u.conkey = c.conkey)
          or exists(select 1 from pg_index i where i.indrelid = c.conrelid and i.indisunique and i.indnatts = 1 and i.indkey[0] = c.conkey[1] and i.indpred is null) one
      from pg_constraint c join pg_class cl on cl.oid = c.conrelid join pg_class pc on pc.oid = c.confrelid
      join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
      join pg_attribute pa on pa.attrelid = c.confrelid and pa.attnum = c.confkey[1]
      where c.contype = 'f' and cardinality(c.conkey) = 1 order by 3, 1, 2) x""")
    by = {}
    for f in fks:
        by.setdefault(f["parent"], []).append(f)
    order = ["application", "interview_session", "interview_question", "interview_answer", "interview_evaluation", "job_posting", "candidate",
             "coding_session", "question_bank", "admin_user"]
    parents = order + sorted(p for p in by if p not in order)
    lines = [f"외래키 {len(fks) + 1}개 중 한 칼럼짜리 {len(fks)}개를 **부모 테이블(들어가는 곳)** 별로 묶었습니다. 나머지 1개는 두 칼럼짜리 "
             "`interview_question (parent_question_id, session_id) → interview_question (id, session_id)`로, 꼬리·재질문이 **같은 응시 안의** 질문만 가리키게 막습니다.  '자식.칼럼'이 '부모.칼럼'을 가리키고, 조인할 때는 `자식.칼럼 = 부모.칼럼`으로 잇습니다. "
             "**6.1**은 면접 파트가 만든 테이블입니다.", ""]
    for p in parents:
        if p not in by:
            continue
        lines += [f"## {p} 로 들어오는 연결 ({len(by[p])}개)", "",
                  "| 자식 테이블.칼럼 | → 부모.칼럼 | 관계 | 비어도 되나 | 부모를 지우면 | 뜻 |", "|---|---|---|---|---|---|"]
        for f in by[p]:
            own = " **6.1**" if f["child"] in OWN else ""
            rel = "1 : 1" if f["one"] else "1 : N"
            if f["child"] == f["parent"]:
                rel = "자기 참조"
            lines.append(f"| `{f['child']}.{f['col']}`{own} | `{p}.{f['pcol']}` | {rel} | {'예' if f['nul'] else '아니요 (필수)'} | "
                         f"{DEL.get(f['del'], f['del'])} | {meaning(f['child'], f['col'], p)} |")
        lines.append("")
    open(os.path.join(OUT, "_db_fk.md"), "w", encoding="utf-8").write("\n".join(lines))
    return len(fks)


def sql_comments() -> dict:
    """{테이블: {칼럼: (주석, 허용 값)}} — interview_schema.sql의 줄 끝 주석"""
    text, out, cur = open(SQL, encoding="utf-8").read(), {}, None
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if m := re.match(r"CREATE TABLE (\w+)", ln):
            cur = m.group(1)
            out[cur] = {}
            continue
        if cur and ln.startswith(");"):
            cur = None
            continue
        if cur and (m := re.match(r"\s{4}(\w+)\s+(bigint|smallint|integer|text|jsonb|boolean|numeric|timestamptz|real|double|vector|text\[\])", ln)):
            col = m.group(1)
            body = ln
            j = i + 1
            while j < len(lines) and re.match(r"\s{10,}\S", lines[j]) and not re.match(r"\s{4}\w+\s", lines[j]):
                body += " " + lines[j].strip()
                j += 1
            cm = body.split("--", 1)[1].strip() if "--" in body else ""
            vals = re.search(r"IN \(([^)]*)\)", body)
            out[cur][col] = (cm, vals.group(1).replace("'", "") if vals else "")
    return out


def build_tables():
    cols = psql("""select json_agg(row_to_json(x)) from (
      select c.table_name tb, c.column_name col, c.udt_name ty, c.is_nullable = 'YES' nul, c.column_default def, c.ordinal_position pos,
        exists(select 1 from information_schema.table_constraints tc join information_schema.key_column_usage k on k.constraint_name = tc.constraint_name
               and k.table_name = tc.table_name where tc.constraint_type = 'PRIMARY KEY' and tc.table_name = c.table_name and k.column_name = c.column_name) pk,
        (select ccu.table_name || '.' || ccu.column_name from information_schema.table_constraints tc join information_schema.key_column_usage k
                on k.constraint_name = tc.constraint_name and k.table_name = tc.table_name
                join information_schema.constraint_column_usage ccu on ccu.constraint_name = tc.constraint_name
         where tc.constraint_type = 'FOREIGN KEY' and tc.table_name = c.table_name and k.column_name = c.column_name
         order by (ccu.table_name = c.table_name) limit 1) fk
      from information_schema.columns c where c.table_schema = 'public' order by 1, 6) x""")
    by = {}
    for c in cols:
        by.setdefault(c["tb"], []).append(c)
    cm = sql_comments()
    lines = ["6.1이 만든 테이블 21개의 모든 칼럼입니다. 설명과 허용 값은 `db/interview_schema.sql`의 주석과 CHECK 제약에서 가져왔습니다. "
             "'키' 칸의 FK는 어느 테이블·칼럼으로 들어가는지 함께 적었습니다.", ""]
    last = None
    for t in OWN:
        if GROUP[t] != last:
            last = GROUP[t]
        lines += [f"## {t}", "", "| 칼럼 | 자료형 | 필수 | 키 | 설명 · 허용 값 |", "|---|---|---|---|---|"]
        for c in by.get(t, []):
            key = "PK" if c["pk"] else ""
            if c["fk"]:
                key = (key + " · " if key else "") + f"FK → `{c['fk']}`"
            note, vals = cm.get(t, {}).get(c["col"], ("", ""))
            desc = note
            if vals:
                desc = (desc + " · " if desc else "") + f"값: {vals}"
            if c["def"] and "nextval" not in c["def"] and "IDENTITY" not in (c["def"] or ""):
                desc = (desc + " · " if desc else "") + f"기본값 {c['def'].split('::')[0]}"
            desc = desc.replace("|", "/")
            lines.append(f"| `{c['col']}` | {TYPE.get(c['ty'], c['ty'])} | {'' if c['nul'] else '필수'} | {key} | {desc} |")
        lines.append("")
    open(os.path.join(OUT, "_db_tables.md"), "w", encoding="utf-8").write("\n".join(lines))


if __name__ == "__main__":
    n = build_fk()
    build_tables()
    print(f"외래키 {n}개, 테이블 {len(OWN)}개 → {OUT}")
