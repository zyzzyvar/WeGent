from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape

import httpx

from app.config import Settings
from app.db import Database


def verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    if not token or not timestamp or not nonce or not signature:
        return False
    raw = "".join(sorted([token, timestamp, nonce]))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return digest == signature


@dataclass(frozen=True)
class WeChatMessage:
    to_user: str
    from_user: str
    msg_type: str
    msg_id: str | None
    content: str
    raw: dict[str, str]


def parse_plaintext_message(payload: bytes) -> WeChatMessage:
    root = ET.fromstring(payload)
    fields = {child.tag: child.text or "" for child in root}
    msg_type = fields.get("MsgType", "")
    content = fields.get("Content", "")
    if msg_type == "voice":
        content = fields.get("Recognition") or "[voice message]"
    elif msg_type == "image":
        content = fields.get("PicUrl") or "[image message]"
    elif msg_type == "event":
        event = fields.get("Event", "")
        event_key = fields.get("EventKey", "")
        content = f"[event:{event}:{event_key}]"

    return WeChatMessage(
        to_user=fields.get("ToUserName", ""),
        from_user=fields.get("FromUserName", ""),
        msg_type=msg_type,
        msg_id=fields.get("MsgId") or fields.get("CreateTime"),
        content=content,
        raw=fields,
    )


def build_text_reply(to_user: str, from_user: str, content: str) -> str:
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )


class WeChatOfficialClient:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db

    async def get_access_token(self) -> str:
        cache_key = self._access_token_cache_key()
        cached = self.db.get_kv(cache_key)
        if cached and cached.get("access_token"):
            return str(cached["access_token"])

        if not self.settings.wechat_app_id or not self.settings.wechat_app_secret:
            raise RuntimeError("WECHAT_APP_ID and WECHAT_APP_SECRET are required to send messages.")

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.settings.wechat_app_id,
                    "secret": self.settings.wechat_app_secret,
                },
            )
            response.raise_for_status()
            data = response.json()

        if "access_token" not in data:
            raise RuntimeError(f"Failed to get WeChat access_token: {data}")

        expires_in = max(int(data.get("expires_in", 7200)) - 300, 60)
        self.db.set_kv(
            cache_key,
            {"access_token": data["access_token"]},
            expires_at=int(time.time()) + expires_in,
        )
        return str(data["access_token"])

    def _access_token_cache_key(self) -> str:
        return f"wechat_access_token:{self.settings.wechat_app_id}"

    async def send_text(self, openid: str, content: str) -> None:
        access_token = await self.get_access_token()
        chunks = _chunk_text(content, size=1800)
        async with httpx.AsyncClient(timeout=15) as client:
            for chunk in chunks[:5]:
                response = await client.post(
                    "https://api.weixin.qq.com/cgi-bin/message/custom/send",
                    params={"access_token": access_token},
                    json={
                        "touser": openid,
                        "msgtype": "text",
                        "text": {"content": chunk},
                    },
                )
                response.raise_for_status()
                data = response.json()
                if data.get("errcode") not in (0, None):
                    raise RuntimeError(f"Failed to send WeChat message: {data}")


def _chunk_text(content: str, size: int) -> list[str]:
    text = content.strip() or "处理完成，但没有生成可发送的内容。"
    return [text[i : i + size] for i in range(0, len(text), size)]
