# Makefile 대신 쓰는 작업 스크립트 (Windows PowerShell 5.1)
#   powershell -ExecutionPolicy Bypass -File tasks.ps1 up     # 컨테이너 빌드·실행 (.env 없으면 .env.example 복사)
#   powershell -ExecutionPolicy Bypass -File tasks.ps1 seed   # DB 초기화 → 스키마 → 시험 데이터 → 확인용 계정 정리 → 회사 문서 (→ Ollama 있으면 임베딩)
#   powershell -ExecutionPolicy Bypass -File tasks.ps1 test   # pytest (api 컨테이너 안에서) + vitest
#   시험 결과는 records/test_runs.csv에 자동으로 쌓이고, seed 전에 직접 응시한 면접은 records/interviews/로 저장된다 (포트폴리오, 11/11)
#   엑셀 다시 만들기: python scripts/build_portfolio.py → records/portfolio_6_1.xlsx
#   powershell -ExecutionPolicy Bypass -File tasks.ps1 e2e    # seed로 DB 초기화 → Playwright (PC의 Chrome, 가짜 카메라·마이크). 스크린샷 web/e2e/screenshots
#   powershell -ExecutionPolicy Bypass -File tasks.ps1 bench  # STT·TTS 비교 기준값: Supertonic으로 고정 문장 음성(없으면) → 지금 STT로 받아 적기 → records/speech_bench.csv (11/12)
#     내 목소리 녹음: python bench/record_server.py → http://localhost:8765 (bench/data/mine, 저장소에 안 올림)
param([Parameter(Mandatory = $true)][ValidateSet('up', 'seed', 'test', 'e2e', 'bench')][string]$Task)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function dc {
    docker compose @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $args 실패 (종료 코드 $LASTEXITCODE)" }
}
$logs = Join-Path $PSScriptRoot 'records/.logs'
New-Item -ItemType Directory -Force $logs | Out-Null
function record($kind, $log) { python (Join-Path $PSScriptRoot 'scripts/record_run.py') $kind $log }   # 기록 실패는 시험 결과에 영향 없음
$psql = @('exec', '-T', 'postgres', 'psql', '-U', 'recruit', '-d', 'recruit', '-v', 'ON_ERROR_STOP=1', '-q')

switch ($Task) {
    'up' {
        if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host '.env.example → .env 복사함' }
        dc up -d --build --wait
    }
    'seed' {
        python scripts/record_run.py export      # 초기화 전에 직접 응시한 면접 기록을 records/interviews/로
        dc @psql -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
        foreach ($f in 'db/common_schema.sql', 'db/interview_schema.sql', 'seed/test_data.sql', 'seed/demo_accounts.sql') {
            Write-Host "적재: $f"
            dc @psql -f "/work/$f"
        }
        # 6.1 개발·시험용 가상 IT 회사 문서 (seed/corpus_6_1/META_SPEC.md). 다른 파트와 통합할 때는 seed/corpus_v3 seed/corpus_v3_add
        dc exec -T api python scripts/load_corpus.py seed/corpus_6_1
        dc exec -T api python scripts/build_question_bank.py     # 직무별 회사 질문 은행 (2차 기술 본 질문의 출발점, 11/10)
        dc exec -T api python scripts/load_resume_detail.py      # 지원자 50명 이력서를 팀 이력서 양식(4쪽)으로
        dc exec -T api python scripts/seed_doc_review.py         # 1차 서류 심사 중인 공고 + 지원자 30명(cand51~80, 팀 양식 이력서·AI 적합도)
        dc exec -T -e MODULE_MODE=stub -e FACE_MODE=stub -e STT_MODE=stub -e TTS_MODE=stub api python scripts/simulate_stage2.py         # 1차 합격 10명 중 7명은 2차를 마친 상태로 (면접·확정·순위·AI 추천)
        dc exec -T api python scripts/seed_doc_screen.py        # 발표된 공고에도 AI 1차 검토 근거 (저장해 둔 결과 seed/doc_screen_cache.json, 11/12)
        Write-Host '코딩 문제 모음 검증·적재 (judge 컨테이너에서 실행, 몇 분 걸림)'
        dc exec -T api python scripts/load_coding.py
        $ErrorActionPreference = 'Continue'   # 5.1에서 네이티브 stderr 리디렉션이 Stop이면 예외가 됨
        # 임베딩 모델(EMBED_MODEL, bge-m3)이 Ollama에 있을 때만 (이 PC는 면접용 qwen3만 받아 둠)
        docker compose exec -T api python -c 'import os, sys, httpx; m = os.environ.get(''EMBED_MODEL'', ''bge-m3''); t = httpx.get(os.environ.get(''OLLAMA_BASE_URL'', ''http://ollama:11434'') + ''/api/tags'', timeout=3).json(); sys.exit(0 if any(x[''name''].split('':'')[0] == m for x in t[''models'']) else 1)' 2>$null
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -eq 0) { dc exec -T api python scripts/embed_docs.py }
        else { Write-Host 'Ollama 또는 임베딩 모델(bge-m3) 없음 → 임베딩 건너뜀 (벡터 검색 없이 조건 필터만)' }
        if (-not $env:SEED_FOR_E2E) { Write-Host '적재: seed/demo_haneul_coding.sql (김하늘도 코딩부터)'; dc @psql -f '/work/seed/demo_haneul_coding.sql' }
        dc @psql -c "SELECT (SELECT count(*) FROM candidate) AS candidates, (SELECT count(*) FROM application WHERE status = 'stage2') AS stage2_applications, (SELECT count(*) FROM company_doc_chunk) AS doc_chunks, (SELECT count(*) FROM company_doc_chunk WHERE embedding IS NOT NULL) AS embedded"
    }
    'test' {
        docker compose exec -T api pytest -q db/ stubs_6_1/ app_6_1/ api/ | Tee-Object -FilePath "$logs/pytest.log"
        $code = $LASTEXITCODE
        record pytest "$logs/pytest.log"
        Push-Location web
        try { npx vitest run | Tee-Object -FilePath "$logs/vitest.log"; $vcode = $LASTEXITCODE } finally { Pop-Location }
        record vitest "$logs/vitest.log"
        if ($code -ne 0 -or $vcode -ne 0) { throw "시험 실패 (pytest $code, vitest $vcode)" }
    }
    'e2e' {
        $env:SEED_FOR_E2E = '1'   # E2E 10문항 흐름은 코딩을 마친 김하늘로 (직접 확인용 seed는 김하늘도 코딩부터)
        powershell -ExecutionPolicy Bypass -File $PSCommandPath seed
        Remove-Item Env:SEED_FOR_E2E
        if ($LASTEXITCODE -ne 0) { throw 'seed 실패' }
        # 시험 동안만 웹을 개발 서버로(가짜 얼굴은 개발 서버에서만 통함), 얼굴 대조는 가짜로. 끝나면 되돌린다
        dc -f compose.yml -f compose.ollama.yml -f compose.e2e.yml up -d --wait web api worker
        Push-Location web
        try {
            npx playwright test | Tee-Object -FilePath "$logs/e2e.log"
            $code = $LASTEXITCODE
            record e2e "$logs/e2e.log"
            if ($code -ne 0) { throw "e2e 실패 (종료 코드 $code)" }
        } finally { Pop-Location; dc up -d web api worker }
    }
    'bench' {
        $b = "$((Resolve-Path bench).Path):/bench"; $r = "$((Resolve-Path records).Path):/records"
        if (-not (Test-Path bench/data/tts_supertonic-3/timing.csv)) { dc run --rm --no-deps -v $b tts python /bench/tts_supertonic.py }
        dc run --rm --no-deps -v $b -v $r stt python /bench/stt_bench.py --engine faster-whisper --model large-v3-turbo --note '기준(지금 서비스)'
    }
}
