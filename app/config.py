from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _csv_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name, "")
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_name: str
    public_base_url: str
    data_dir: Path
    db_path: Path
    timezone: str

    wechat_token: str
    wechat_app_id: str
    wechat_app_secret: str
    wechat_verify_signature: bool
    reply_ack_text: str

    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout_seconds: int
    max_memory_items: int
    task_poll_interval_seconds: int
    system_prompt: str

    safety_mode: bool
    safety_require_openid_whitelist: bool
    safety_allowed_openids: tuple[str, ...]
    safety_admin_token: str
    safety_max_text_chars: int
    safety_max_messages_per_minute: int
    safety_max_messages_per_day: int
    safety_reply_prefix: str
    safety_allow_memory: bool
    safety_allow_task_creation: bool
    safety_allow_proactive_task_send: bool
    wechat_max_reply_chunks: int


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    db_path = Path(os.getenv("DB_PATH", str(data_dir / "wegent.sqlite3"))).resolve()
    return Settings(
        app_name=os.getenv("APP_NAME", "WeGent"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        data_dir=data_dir,
        db_path=db_path,
        timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
        wechat_token=os.getenv("WECHAT_TOKEN", ""),
        wechat_app_id=os.getenv("WECHAT_APP_ID", ""),
        wechat_app_secret=os.getenv("WECHAT_APP_SECRET", ""),
        wechat_verify_signature=_bool_env("WECHAT_VERIFY_SIGNATURE", True),
        reply_ack_text=os.getenv("REPLY_ACK_TEXT", "收到，我正在处理。"),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "qwen2.5:7b"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_timeout_seconds=_int_env("LLM_TIMEOUT_SECONDS", 120),
        max_memory_items=_int_env("MAX_MEMORY_ITEMS", 12),
        task_poll_interval_seconds=_int_env("TASK_POLL_INTERVAL_SECONDS", 30),
        system_prompt=os.getenv(
            "SYSTEM_PROMPT",
            "You are WeGent, a practical personal AI assistant inside WeChat. "
            "Be concise, helpful, and transparent that you are an AI assistant. "
            "When you are missing information, ask one clear follow-up question.",
        ),
        safety_mode=_bool_env("SAFETY_MODE", True),
        safety_require_openid_whitelist=_bool_env("SAFETY_REQUIRE_OPENID_WHITELIST", True),
        safety_allowed_openids=_csv_env("SAFETY_ALLOWED_OPENIDS"),
        safety_admin_token=os.getenv("SAFETY_ADMIN_TOKEN", ""),
        safety_max_text_chars=_int_env("SAFETY_MAX_TEXT_CHARS", 800),
        safety_max_messages_per_minute=_int_env("SAFETY_MAX_MESSAGES_PER_MINUTE", 3),
        safety_max_messages_per_day=_int_env("SAFETY_MAX_MESSAGES_PER_DAY", 20),
        safety_reply_prefix=os.getenv("SAFETY_REPLY_PREFIX", "[AI助手] "),
        safety_allow_memory=_bool_env("SAFETY_ALLOW_MEMORY", True),
        safety_allow_task_creation=_bool_env("SAFETY_ALLOW_TASK_CREATION", False),
        safety_allow_proactive_task_send=_bool_env("SAFETY_ALLOW_PROACTIVE_TASK_SEND", False),
        wechat_max_reply_chunks=_int_env("WECHAT_MAX_REPLY_CHUNKS", 1),
    )
