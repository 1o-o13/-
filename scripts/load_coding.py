"""코딩 테스트 문제 모음(seed/coding_bank) 검증·적재. tasks.ps1 seed가 api 컨테이너 안에서 실행한다 (judge 컨테이너 필요).
검증 규칙은 api/coding/verify.py (3번 즉석 출제와 같음). 하나라도 어기면 그 문제는 넣지 않고 이유를 출력한다.
이미 들어간 문제(prompt_version bank:<key>)는 건너뛴다.
"""
import json
import os
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.coding import verify  # noqa: E402
from seed.coding_bank import slot1, slot2, slot3  # noqa: E402


def main(argv=None):
    db = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    ok = 0
    for p in slot1.PROBLEMS + slot2.PROBLEMS + slot3.PROBLEMS:
        if db.execute("SELECT 1 FROM coding_problem WHERE prompt_version = %s", (f"bank:{p['key']}",)).fetchone():
            ok += 1
            continue
        cases, limits, problems = verify.build(p)
        if problems:
            print(f"✗ {p['key']} {p['title']}: " + " / ".join(problems[:5]))
            continue
        verify.save(db, p, cases, limits, "collected", f"bank:{p['key']}")
        ok += 1
        print(f"✓ {p['key']} {p['tier']} {p['title']} · 케이스 {len(cases)}개 · 제한 {json.dumps(limits)}")
    print(f"코딩 문제 {ok}개 준비됨")
    db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
