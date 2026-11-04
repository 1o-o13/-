"""FastAPI 앱. 라우터 등록, 시작 때 LLM 설정을 검사해 잘못된 .env면 바로 실패시킨다."""
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from api import auth, notify, site, social
from api.admin import document as admin_document
from api.admin import postings as admin_postings
from api.admin import routes as admin
from api.coding import routes as coding
from api.interview import extras as interview_extras
from api.interview import routes as interview
from app_6_1 import llm


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm.check_config()
    if os.environ.get("MODULE_MODE") == "real":       # 사내 모델(꼬리질문·국외 전송 미동의)을 미리 GPU에 올림
        threading.Thread(target=llm.warm_local, args=(os.environ.get("LLM_LOCAL_MODEL", "qwen3:4b"),), daemon=True).start()
        from api import retrieve                      # BM25 형태소 분석기 첫 로딩(약 20초)을 미리
        threading.Thread(target=retrieve.tokens, args=("준비",), daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def keep_candidate_login(request: Request, call_next):
    """지원자 로그인 1시간은 '마지막으로 쓴 뒤 1시간'. 성공한 요청마다 쿠키를 늘린다.
    면접 중에는 상태 확인·답변 제출 요청이 계속 오가서 면접 도중에 로그아웃되지 않는다"""
    response = await call_next(request)
    if response.status_code < 400 and request.url.path != "/api/auth/logout" and "set-cookie" not in response.headers:
        new = auth.slide(request.cookies.get(auth.COOKIE))
        if new:
            response.set_cookie(auth.COOKIE, new[0], max_age=new[1], httponly=True, samesite="lax")
    return response
app.include_router(auth.router)
app.include_router(interview.router)
app.include_router(interview_extras.router)   # 연습 면접·글로 답하기·라이브니스 (11/12)
app.include_router(coding.router)
app.include_router(admin_postings.router)   # 채용 요청·공고 관리 (임시, 공고 파트 정식 기능 오면 교체)
app.include_router(admin.router)
app.include_router(admin_document.router)
app.include_router(notify.router)
app.include_router(site.router)
app.include_router(social.router)


@app.get("/api/health")
def health():
    return {"ok": True, "module_mode": os.environ.get("MODULE_MODE")}
