from dataclasses import replace

from app.config import load_settings
from app.db import Database
from app.safety import SafetyGuard


def make_guard(tmp_path, **overrides):
    values = {
        "wechat_app_id": "test-appid",
        "safety_mode": True,
        "safety_require_openid_whitelist": True,
        "safety_allowed_openids": ("allowed",),
        "safety_max_messages_per_minute": 3,
        "safety_max_messages_per_day": 10,
    }
    values.update(overrides)
    settings = replace(load_settings(), **values)
    db = Database(tmp_path / "test.sqlite3")
    db.init()
    return SafetyGuard(settings, db), db


def test_whitelist_blocks_unknown_openid(tmp_path) -> None:
    guard, db = make_guard(tmp_path)

    decision = guard.review_user_message("unknown", "hello")

    assert not decision.should_process
    assert decision.status == "blocked:not_whitelisted"
    assert "白名单" in decision.reply
    assert db.list_safety_events()[0]["event_type"] == "blocked"


def test_first_allowed_message_returns_ai_notice_only(tmp_path) -> None:
    guard, _db = make_guard(tmp_path)

    first = guard.review_user_message("allowed", "hello")
    second = guard.review_user_message("allowed", "hello again")

    assert not first.should_process
    assert "AI 办事助手" in first.reply
    assert second.should_process
    assert second.reply is None


def test_risky_message_is_blocked_after_notice(tmp_path) -> None:
    guard, _db = make_guard(tmp_path)

    guard.review_user_message("allowed", "hello")
    decision = guard.review_user_message("allowed", "验证码是 123456")

    assert not decision.should_process
    assert decision.status == "blocked:risky:隐私凭证"
    assert "隐私凭证" in decision.reply


def test_rate_limit_blocks_after_threshold(tmp_path) -> None:
    guard, _db = make_guard(tmp_path, safety_max_messages_per_minute=2)

    guard.review_user_message("allowed", "hello")
    second = guard.review_user_message("allowed", "hello 2")
    third = guard.review_user_message("allowed", "hello 3")

    assert second.should_process
    assert not third.should_process
    assert third.status == "blocked:rate_minute"


def test_reply_label_is_idempotent(tmp_path) -> None:
    guard, _db = make_guard(tmp_path)

    assert guard.label_reply("hello") == "[AI助手] hello"
    assert guard.label_reply("[AI助手] hello") == "[AI助手] hello"
