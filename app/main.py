from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app.assistant import AssistantService
from app.config import load_settings
from app.db import Database
from app.llm import LocalLLMClient
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
task_runner = TaskRunner(settings, db, assistant, wechat)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


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
        content = (
            "你好，我是 WeGent 办事助手。你可以直接发问题、语音，"
            "也可以发送“帮助”查看我现在支持的能力。"
        )
        return _xml_reply(message.from_user, message.to_user, content)

    if message.msg_type not in {"text", "voice"}:
        content = "我已经收到这条消息。当前验证版先支持文字和可识别语音，文件上传会通过 H5/微信客服补上。"
        return _xml_reply(message.from_user, message.to_user, content)

    inserted = db.record_message(
        openid=message.from_user,
        role="user",
        content=message.content,
        msg_id=message.msg_id,
    )
    if inserted:
        background_tasks.add_task(process_and_reply, message.from_user, message.content)

    return _xml_reply(message.from_user, message.to_user, settings.reply_ack_text)


@app.get("/h5/settings", response_class=HTMLResponse)
async def settings_page() -> HTMLResponse:
    with open("app/static/settings.html", "r", encoding="utf-8") as file:
        return HTMLResponse(file.read())


@app.get("/api/users/{openid}/settings")
async def get_user_settings(openid: str) -> dict[str, object]:
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
async def update_memory_enabled(openid: str, payload: dict[str, bool]) -> dict[str, bool]:
    enabled = bool(payload.get("enabled", True))
    db.set_memory_enabled(openid, enabled)
    return {"memory_enabled": enabled}


@app.post("/api/users/{openid}/memory/clear")
async def clear_user_memory(openid: str) -> dict[str, int]:
    return {"deleted": db.clear_memories(openid)}


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
    xml = build_text_reply(to_user=to_user, from_user=from_user, content=content)
    return Response(content=xml, media_type="application/xml")
