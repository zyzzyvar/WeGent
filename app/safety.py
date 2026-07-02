from __future__ import annotations

import time
from dataclasses import dataclass

from app.config import Settings
from app.db import Database, utc_now_iso


@dataclass(frozen=True)
class SafetyDecision:
    should_process: bool
    reply: str | None = None
    status: str = "ok"
    reason: str = "ok"


class SafetyGuard:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db

    def subscribe_reply(self, openid: str) -> str:
        self.db.record_safety_event(openid, "subscribe", "user subscribed")
        if self._whitelist_blocks(openid):
            return self._not_allowed_reply()
        return (
            "我是 WeGent AI 办事助手，不是人工客服或真人经理。回复由 AI 生成，"
            "可能出错。请不要发送身份证、银行卡、验证码、病历、密码等敏感信息。"
            "继续使用表示你理解并同意《用户协议》和《隐私政策》。"
        )

    def review_user_message(self, openid: str, text: str) -> SafetyDecision:
        if not self.settings.safety_mode:
            return SafetyDecision(should_process=True)

        if self._whitelist_blocks(openid):
            self.db.record_safety_event(openid, "blocked", "openid not in beta whitelist")
            return SafetyDecision(
                should_process=False,
                reply=self._not_allowed_reply(),
                status="blocked:not_whitelisted",
                reason="not_whitelisted",
            )

        if not self._increment_rate(openid, "minute", self.settings.safety_max_messages_per_minute, 60):
            self.db.record_safety_event(openid, "blocked", "minute rate limit")
            return SafetyDecision(
                should_process=False,
                reply="当前内部验证版已触发分钟级限频，请稍后再试。",
                status="blocked:rate_minute",
                reason="rate_minute",
            )

        if not self._increment_rate(openid, "day", self.settings.safety_max_messages_per_day, 86400):
            self.db.record_safety_event(openid, "blocked", "daily rate limit")
            return SafetyDecision(
                should_process=False,
                reply="当前内部验证版已触发今日限额，请明天再试。",
                status="blocked:rate_day",
                reason="rate_day",
            )

        if len(text) > self.settings.safety_max_text_chars:
            self.db.record_safety_event(openid, "blocked", "message too long")
            return SafetyDecision(
                should_process=False,
                reply=f"当前内部验证版单次消息最多 {self.settings.safety_max_text_chars} 字，请缩短后再发。",
                status="blocked:too_long",
                reason="too_long",
            )

        notice = self._first_notice(openid)
        if notice:
            self.db.record_safety_event(openid, "notice", "first safety notice")
            return SafetyDecision(
                should_process=False,
                reply=notice,
                status="notice:first_use",
                reason="first_use_notice",
            )

        risky_category = self._risky_category(text)
        if risky_category:
            self.db.record_safety_event(openid, "blocked", f"risky category: {risky_category}")
            return SafetyDecision(
                should_process=False,
                reply=(
                    f"为降低账号和内容风险，当前内部验证版暂不处理“{risky_category}”相关请求。"
                    "请勿发送身份证、银行卡、验证码、病历、密码、私钥等敏感信息。"
                ),
                status=f"blocked:risky:{risky_category}",
                reason=f"risky:{risky_category}",
            )

        return SafetyDecision(should_process=True)

    def label_reply(self, content: str) -> str:
        if not self.settings.safety_mode:
            return content
        prefix = self.settings.safety_reply_prefix
        text = content.strip()
        if not prefix or text.startswith(prefix):
            return text
        return f"{prefix}{text}"

    def _whitelist_blocks(self, openid: str) -> bool:
        if not self.settings.safety_require_openid_whitelist:
            return False
        return openid not in set(self.settings.safety_allowed_openids)

    def _not_allowed_reply(self) -> str:
        return (
            "当前服务仅面向内部白名单验证，暂未开放使用。你的访问已记录，"
            "请联系管理员加入白名单后再使用。"
        )

    def _first_notice(self, openid: str) -> str | None:
        key = f"safety_notice_sent:{self.settings.wechat_app_id}:{openid}"
        if self.db.get_kv(key):
            return None
        self.db.set_kv(key, {"sent_at": utc_now_iso()})
        return (
            "开始前先说明：我是 WeGent AI 办事助手，不是人工客服或真人经理；"
            "回复由 AI 生成，可能存在错误。当前是小范围内部验证版，"
            "不处理医疗、法律、金融投资、违法违规、色情低俗、暴力自伤、"
            "诈骗绕过、隐私凭证等高风险内容。继续使用表示你理解并同意"
            "《用户协议》和《隐私政策》。请重新发送你的问题。"
        )

    def _increment_rate(self, openid: str, scope: str, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return False
        now = int(time.time())
        bucket = now // window_seconds
        key = f"safety_rate:{self.settings.wechat_app_id}:{scope}:{openid}:{bucket}"
        payload = self.db.get_kv(key) or {"count": 0}
        count = int(payload.get("count", 0)) + 1
        self.db.set_kv(
            key,
            {"count": count},
            expires_at=(bucket + 1) * window_seconds + 60,
        )
        return count <= limit

    def _risky_category(self, text: str) -> str | None:
        normalized = text.lower()
        categories = {
            "违法违规": (
                "洗钱",
                "诈骗",
                "钓鱼",
                "盗号",
                "破解",
                "绕过风控",
                "绕过审核",
                "木马",
                "病毒",
                "黑产",
                "刷量",
                "代实名",
                "伪造证件",
            ),
            "隐私凭证": (
                "验证码",
                "银行卡",
                "身份证",
                "密码",
                "私钥",
                "助记词",
                "token",
                "cookie",
                "短信码",
            ),
            "医疗健康": (
                "诊断",
                "处方",
                "用药",
                "剂量",
                "病历",
                "手术",
                "药能不能吃",
                "抑郁症",
            ),
            "法律合规": (
                "起诉",
                "判几年",
                "律师函",
                "合同纠纷",
                "逃税",
                "避税方案",
                "劳动仲裁",
            ),
            "金融投资": (
                "买哪只股票",
                "荐股",
                "投资建议",
                "收益保证",
                "杠杆",
                "期货",
                "合约",
                "币圈",
                "贷款套现",
            ),
            "色情低俗": (
                "色情",
                "成人视频",
                "约炮",
                "裸聊",
            ),
            "暴力自伤": (
                "自杀",
                "自残",
                "杀人",
                "炸药",
                "爆炸物",
                "枪支",
            ),
        }
        for category, keywords in categories.items():
            if any(keyword in normalized for keyword in keywords):
                return category
        return None
