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
    )
