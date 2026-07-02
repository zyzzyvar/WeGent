from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app.assistant import AssistantService
from app.config import load_settings
from app.db import Database
from app.llm import LocalLLMClient
from app.safety import SafetyGuard
from app.tasks import TaskRunner
from app.wechat import (
    WeChatOfficialClient,
    build_text_reply,
    parse_plaintext_message,
    verify_signature,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

settings = load_settings()
db = Database(settings.db_path)
llm = LocalLLMClient(settings)
assistant = AssistantService(settings, db, llm)
wechat = WeChatOfficialClient(settings, db)
safety = SafetyGuard(settings, db)
task_runner = TaskRunner(settings, db, assistant, wechat)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def _static_html(filename: str) -> HTMLResponse:
    with open(f"app/static/{filename}", "r", encoding="utf-8") as file:
        return HTMLResponse(file.read())


@app.on_event("startup")
async def on_startup() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db.init()
    task_runner.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await task_runner.stop()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home_page() -> HTMLResponse:
    return _static_html("home.html")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page() -> HTMLResponse:
    return _static_html("privacy.html")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page() -> HTMLResponse:
    return _static_html("terms.html")


@app.get("/wechat/official/callback", response_class=PlainTextResponse)
async def verify_wechat_callback(
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    echostr: str = Query(""),
) -> str:
    if not settings.wechat_verify_signature:
        return echostr
    if verify_signature(settings.wechat_token, timestamp, nonce, signature):
        return echostr
    raise HTTPException(status_code=403, detail="Invalid signature")


@app.post("/wechat/official/callback")
async def receive_wechat_message(
    request: Request,
    background_tasks: BackgroundTasks,
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
) -> Response:
    if settings.wechat_verify_signature and not verify_signature(
        settings.wechat_token,
        timestamp,
        nonce,
        signature,
    ):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.body()
    message = parse_plaintext_message(payload)
    db.ensure_user(message.from_user)

    if message.msg_type == "event" and message.raw.get("Event") == "subscribe":
        return _xml_reply(message.from_user, message.to_user, safety.subscribe_reply(message.from_user))

    if message.msg_type == "event":
        db.record_safety_event(message.from_user, "event", message.content)
        return PlainTextResponse("success")

    if message.msg_type not in {"text", "voice"}:
        db.record_safety_event(message.from_user, "blocked", f"unsupported message type: {message.msg_type}")
        content = "当前内部验证版仅支持文字和可识别语音，暂不处理图片、文件、位置、链接等消息。"
        return _xml_reply(message.from_user, message.to_user, content)

    decision = safety.review_user_message(message.from_user, message.content)
    inserted = db.record_message(
        openid=message.from_user,
        role="user",
        content=message.content,
        msg_id=message.msg_id,
        status=decision.status,
    )
    if decision.reply is not None:
        return _xml_reply(message.from_user, message.to_user, decision.reply)

    if inserted and decision.should_process:
        background_tasks.add_task(process_and_reply, message.from_user, message.content)

    return _xml_reply(message.from_user, message.to_user, settings.reply_ack_text)


@app.get("/h5/settings", response_class=HTMLResponse)
async def settings_page() -> HTMLResponse:
    return _static_html("settings.html")


@app.get("/api/users/{openid}/settings")
async def get_user_settings(
    openid: str,
    token: str = Query(""),
    x_safety_token: str = Header("", alias="X-Safety-Token"),
) -> dict[str, object]:
    _require_admin_token(token or x_safety_token)
    db.ensure_user(openid)
    user = db.get_user(openid)
    memories = db.list_memories(openid, limit=50)
    return {
        "openid": openid,
        "memory_enabled": bool(user["memory_enabled"]) if user else True,
        "memory_count": len(memories),
        "memories": [row["content"] for row in memories],
    }


@app.post("/api/users/{openid}/memory/enabled")
async def update_memory_enabled(
    openid: str,
    payload: dict[str, bool],
    token: str = Query(""),
    x_safety_token: str = Header("", alias="X-Safety-Token"),
) -> dict[str, bool]:
    _require_admin_token(token or x_safety_token)
    enabled = bool(payload.get("enabled", True))
    db.set_memory_enabled(openid, enabled)
    return {"memory_enabled": enabled}


@app.post("/api/users/{openid}/memory/clear")
async def clear_user_memory(
    openid: str,
    token: str = Query(""),
    x_safety_token: str = Header("", alias="X-Safety-Token"),
) -> dict[str, int]:
    _require_admin_token(token or x_safety_token)
    return {"deleted": db.clear_memories(openid)}


@app.get("/ops/safety/users")
async def safety_users(
    token: str = Query(""),
    x_safety_token: str = Header("", alias="X-Safety-Token"),
) -> dict[str, object]:
    _require_admin_token(token or x_safety_token)
    return {
        "users": [dict(row) for row in db.list_users(limit=100)],
        "events": [dict(row) for row in db.list_safety_events(limit=100)],
    }


async def process_and_reply(openid: str, content: str) -> None:
    try:
        answer = await assistant.handle_text(openid, content, current_message_recorded=True)
    except Exception as exc:  # noqa: BLE001 - user should get a graceful failure.
        logger.exception("Failed to process message for %s", openid)
        answer = f"我这边处理失败了：{exc}"

    try:
        await wechat.send_text(openid, answer)
    except Exception:
        logger.exception("Failed to send WeChat customer-service message to %s", openid)


def _xml_reply(to_user: str, from_user: str, content: str) -> Response:
    xml = build_text_reply(to_user=to_user, from_user=from_user, content=safety.label_reply(content))
    return Response(content=xml, media_type="application/xml")


def _require_admin_token(provided: str) -> None:
    if not settings.safety_admin_token:
        raise HTTPException(status_code=403, detail="SAFETY_ADMIN_TOKEN is not configured")
    if provided != settings.safety_admin_token:
        raise HTTPException(status_code=403, detail="Invalid safety admin token")
