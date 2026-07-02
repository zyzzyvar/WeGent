from dataclasses import replace

from app.config import load_settings
from app.db import Database
from app.wechat import build_text_reply, parse_plaintext_message, verify_signature
from app.wechat import WeChatOfficialClient


def test_verify_signature() -> None:
    assert verify_signature(
        token="token",
        timestamp="1710000000",
        nonce="nonce",
        signature="80b94323d2cec5b96d07867a5166387fa34e8f84",
    )


def test_parse_plaintext_message() -> None:
    payload = b"""
    <xml>
      <ToUserName><![CDATA[gh_test]]></ToUserName>
      <FromUserName><![CDATA[openid_test]]></FromUserName>
      <CreateTime>1710000000</CreateTime>
      <MsgType><![CDATA[text]]></MsgType>
      <Content><![CDATA[hello]]></Content>
      <MsgId>123</MsgId>
    </xml>
    """
    message = parse_plaintext_message(payload)
    assert message.to_user == "gh_test"
    assert message.from_user == "openid_test"
    assert message.msg_type == "text"
    assert message.content == "hello"
    assert message.msg_id == "123"


def test_build_text_reply() -> None:
    xml = build_text_reply("openid_test", "gh_test", "ok")
    assert "<ToUserName><![CDATA[openid_test]]></ToUserName>" in xml
    assert "<FromUserName><![CDATA[gh_test]]></FromUserName>" in xml
    assert "<Content><![CDATA[ok]]></Content>" in xml


def test_access_token_cache_key_is_scoped_to_appid(tmp_path) -> None:
    settings_a = replace(load_settings(), wechat_app_id="appid-a")
    settings_b = replace(load_settings(), wechat_app_id="appid-b")
    db = Database(tmp_path / "test.sqlite3")

    client_a = WeChatOfficialClient(settings_a, db)
    client_b = WeChatOfficialClient(settings_b, db)

    assert client_a._access_token_cache_key() == "wechat_access_token:appid-a"
    assert client_b._access_token_cache_key() == "wechat_access_token:appid-b"
