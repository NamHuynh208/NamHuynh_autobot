import asyncio
import hmac
import json
import logging
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import date, datetime, time as clock, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import page_chat
from .config import Settings, env, timezone
from .database import Database
from .discord_listener import run_discord
from .messenger_bridge import run_matrix
from .summarizer import enqueue, run_jobs

PUBLIC_ORIGIN = env("PUBLIC_ORIGIN", "https://autobot.example.com")
SECURE = PUBLIC_ORIGIN.startswith("https://")
COOKIE = "__Host-autobot" if SECURE else "autobot-local"
SESSION_SECONDS = 12 * 3600
STATIC = Path(__file__).parent / "static"
PAGE_WEBHOOK = "/webhook/messenger"


@asynccontextmanager
async def lifespan(app):
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    password = env("ADMIN_PASSWORD")
    host = urlsplit(PUBLIC_ORIGIN).hostname
    if len(password) < 20 or host is None or (not SECURE and host != "127.0.0.1"):
        raise RuntimeError("Đặt ADMIN_PASSWORD ít nhất 20 ký tự và PUBLIC_ORIGIN HTTPS (HTTP chỉ dùng loopback local).")
    db = app.state.db = Database()
    tasks = {}
    try:
        await db.open(env("DATABASE_PATH", "data/autobot.sqlite3"))
        timezone()
        app.state.health = health = dict(discord="connecting", matrix="connecting", scheduler="connecting")
        app.state.meta = None
        app.state.sessions = {}
        app.state.failed = deque()
        app.state.wake = wake = asyncio.Event()
        app.state.page_wake = asyncio.Event()
        tasks = {key: asyncio.create_task(coro, name=key) for key, coro in {
            "discord": run_discord(db, env("DISCORD_USER_TOKEN"), health),
            "matrix": run_matrix(db, health), "scheduler": run_jobs(db, health, wake),
            "page_chat": page_chat.run_page_chat(db, app.state, service_status),
        }.items()}
        app.state.tasks = tasks
        yield
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        if hasattr(db, "conn"):
            await db.conn.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(PUBLIC_ORIGIN).hostname or "127.0.0.1", "autobot", "127.0.0.1"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def protect(request, call_next):
    if request.method in ("POST", "PUT") and request.url.path != PAGE_WEBHOOK:
        size = request.headers.get("content-length", "")
        if not size.isascii() or not size.isdecimal() or len(size) > 6 or int(size) > 200_000:
            return JSONResponse({"detail": "Yêu cầu quá lớn hoặc thiếu Content-Length."}, 413)
        if request.url.path != "/internal/meta-status" and request.headers.get("origin") != PUBLIC_ORIGIN:
            return JSONResponse({"detail": "Origin không hợp lệ."}, 403)
    response = await call_next(request)
    response.headers.update({
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                                   "img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    })
    if SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    detail = ["JSON không hợp lệ." if item["type"] == "json_invalid" else
              " · ".join(str(p) for p in item["loc"][1:]) + ": " + item["msg"] for item in exc.errors()]
    return JSONResponse({"detail": detail}, 422)


def equal(one, two):
    return hmac.compare_digest(one.encode(), two.encode())


def authenticated(request):
    token = request.cookies.get(COOKIE)
    return bool(token and request.app.state.sessions.get(token, 0) > time.monotonic())


def admin(request: Request):
    if not authenticated(request):
        raise HTTPException(401, "Phiên đã hết hạn. Hãy đăng nhập lại.")
    return request.app.state.db


@app.get("/", include_in_schema=False)
async def page(request: Request):
    return FileResponse(STATIC.parent / ("dashboard.html" if authenticated(request) else "login.html"))


@app.get("/healthz")
async def live():
    return {"ok": True}


@app.get(PAGE_WEBHOOK)
async def verify_page_webhook(request: Request):
    verify_token = env("FB_VERIFY_TOKEN")
    query = request.query_params
    challenge = query.get("hub.challenge", "")
    if (not verify_token or query.get("hub.mode") != "subscribe" or not 0 < len(challenge) <= 256
            or not equal(query.get("hub.verify_token", ""), verify_token)):
        raise HTTPException(403, "Xác minh webhook thất bại.")
    return PlainTextResponse(challenge)


@app.post(PAGE_WEBHOOK)
async def receive_page_webhook(request: Request):
    secret = env("FB_APP_SECRET")
    signature = request.headers.get("x-hub-signature-256", "")
    if not secret or len(signature) != 71 or not signature.startswith("sha256="):
        raise HTTPException(403, "Chữ ký webhook không hợp lệ.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 200_000:
            raise HTTPException(413, "Webhook quá lớn.")
        body.extend(chunk)
    expected = "sha256=" + hmac.digest(secret.encode(), body, "sha256").hex()
    if not equal(signature, expected):
        raise HTTPException(403, "Chữ ký webhook không hợp lệ.")
    try:
        payload = page_chat.Webhook.model_validate_json(body)
    except ValidationError:
        raise HTTPException(400, "Payload webhook không hợp lệ.") from None
    await page_chat.accept(request.app.state.db, payload)
    request.app.state.page_wake.set()
    return PlainTextResponse("EVENT_RECEIVED")


class Login(BaseModel):
    password: str = Field(max_length=512)


@app.post("/api/login")
async def login(data: Login, request: Request, response: Response):
    state, now = request.app.state, time.monotonic()
    correct = equal(data.password, env("ADMIN_PASSWORD"))
    if not correct:
        while state.failed and state.failed[0] <= now - 300:
            state.failed.popleft()
        if len(state.failed) >= 8:
            raise HTTPException(429, "Quá nhiều lần đăng nhập sai. Thử lại sau 5 phút.", {"Retry-After": "300"})
        state.failed.append(now)
        raise HTTPException(401, "Mật khẩu không đúng.")
    for token, expiry in list(state.sessions.items()):
        if expiry <= now:
            del state.sessions[token]
    state.sessions.pop(request.cookies.get(COOKIE), None)
    while len(state.sessions) >= 32:
        del state.sessions[next(iter(state.sessions))]
    token = secrets.token_urlsafe(32)
    state.sessions[token] = now + SESSION_SECONDS
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, secure=SECURE, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/api/logout")
async def logout(request: Request, response: Response, _=Depends(admin)):
    request.app.state.sessions.pop(request.cookies.get(COOKIE), None)
    response.delete_cookie(COOKIE, secure=SECURE, httponly=True, samesite="strict")
    return {"ok": True}


class MetaStatus(BaseModel):
    state_event: str = Field(max_length=40)
    ttl: int = Field(default=21600, ge=0, le=86400)
    remote_id: str = ""


@app.post("/internal/meta-status", status_code=204)
async def meta_status(data: MetaStatus, request: Request):
    secret_path = Path(env("META_AS_TOKEN_FILE", "/run/autobot/meta-as-token"))
    try:
        secret = secret_path.read_text().strip()
    except OSError:
        secret = ""
    if not secret or not equal(request.headers.get("authorization", ""), f"Bearer {secret}"):
        raise HTTPException(403, "Không có quyền.")
    if data.remote_id or data.state_event in {"STARTING", "UNCONFIGURED", "BRIDGE_UNREACHABLE"}:
        request.app.state.meta = (data.state_event, int(time.time()) + data.ttl)


def service_status(state):
    services = dict(state.health)
    for key in services:
        task = state.tasks[key]
        if task.done() and (task.cancelled() or task.exception() is not None):
            services[key] = "error"
    meta = state.meta
    services["meta"] = meta[0] if meta and meta[1] > time.time() else "unknown"
    return services


@app.get("/api/overview")
async def overview(request: Request, db=Depends(admin)):
    services = service_status(request.app.state)
    stats = (await db.rows("SELECT COUNT(*) AS total, COUNT(*) FILTER(WHERE is_summarized=0) AS pending FROM messages"))[0]
    job = await db.rows("SELECT id,kind,state FROM jobs ORDER BY (state='done'), CASE WHEN state='done' THEN -id ELSE id END LIMIT 1")
    latest = await reports(db, "", None, None, 1, None)
    return {"services": services, "stats": stats, "job": job[0] if job else None, "latest": latest[0] if latest else None,
            "automatic": db.settings.automatic, "timezone": str(timezone()), "checked": int(time.time())}


@app.post("/api/summarize", status_code=202)
async def summarize(request: Request, db=Depends(admin)):
    job_id, queued = await enqueue(db, "manual")
    request.app.state.wake.set()
    return {"id": job_id, "queued": queued}


@app.get("/api/settings")
async def get_settings(db=Depends(admin)):
    return db.settings


@app.put("/api/settings")
async def save_settings(settings: Settings, request: Request, db=Depends(admin)):
    await db.save_settings(settings)
    request.app.state.wake.set()
    return settings


class Automatic(BaseModel):
    automatic: bool


@app.put("/api/automatic")
async def automatic(data: Automatic, request: Request, db=Depends(admin)):
    await db.save_settings(db.settings.model_copy(update={"automatic": data.automatic}))
    request.app.state.wake.set()
    return data


Platform = Literal["", "discord", "messenger"]


async def reports(db, platform, start, end, limit, before):
    where, args = ["1=1"], []
    if platform:
        where.append({"discord": "s.discord_count>0", "messenger": "s.messenger_count>0"}[platform])
    if start and end and start > end:
        raise HTTPException(422, "Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.")
    for day, operator, adjustment in [(start, ">=", 0), (end, "<", 1)]:
        if day:
            if day.year > 9998:
                raise HTTPException(422, "Năm ngoài phạm vi hỗ trợ.")
            where.append(f"s.created {operator} ?")
            args.append(int(datetime.combine(day + timedelta(days=adjustment), clock(), timezone()).timestamp()))
    if before:
        where.append("s.id<?")
        args.append(before)
    rows = await db.rows("SELECT s.id,s.created,s.discord_count,s.messenger_count,s.body,s.delivery,j.kind "
                         "FROM summaries s JOIN jobs j ON j.id=s.job_id WHERE " + " AND ".join(where)
                         + " ORDER BY s.id DESC LIMIT ?", [*args, limit])
    return [row | {"body": json.loads(row["body"])} for row in rows]


@app.get("/api/summaries")
async def summary_list(platform: Platform = "", start: date | None = None, end: date | None = None,
                       limit: int = Query(15, ge=1, le=100), before: int | None = Query(None, ge=1), db=Depends(admin)):
    return await reports(db, platform, start, end, limit, before)


@app.get("/api/messages")
async def message_list(platform: Platform = "", summarized: Literal["", "0", "1"] = "", q: str = Query("", max_length=200),
                       limit: int = Query(25, ge=1, le=100), before: int | None = Query(None, ge=1), db=Depends(admin)):
    where, args = ["1=1"], []
    for value, clause in [(platform, "platform=?"), (summarized, "is_summarized=?"), (before, "id<?")]:
        if value:
            where.append(clause)
            args.append(value)
    if q.strip():
        where.append("(content LIKE ? ESCAPE '\\' OR author LIKE ? ESCAPE '\\' OR room LIKE ? ESCAPE '\\')")
        search = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args.extend([search] * 3)
    return await db.rows("SELECT id,platform,room,author,content,ts,is_summarized FROM messages WHERE "
                         + " AND ".join(where) + " ORDER BY id DESC LIMIT ?", [*args, limit])
