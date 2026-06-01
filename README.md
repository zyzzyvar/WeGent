# WeGent

WeGent is a WeChat Official Account assistant service backed by a local LLM. The first validation version focuses on:

- WeChat Official Account callback verification.
- Text and recognized voice message handling.
- Async replies through WeChat customer-service messages.
- OpenAI-compatible local LLM gateway.
- SQLite-backed user memory and scheduled task skeleton.
- A small H5 settings page.

## Architecture

```text
WeChat Service Account
  -> /wechat/official/callback
  -> FastAPI message gateway
  -> SQLite memory / task store
  -> local OpenAI-compatible LLM
  -> WeChat customer-service reply
```

## Quick Start

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Edit `.env` before connecting WeChat:

```env
WECHAT_TOKEN=your-callback-token
WECHAT_APP_ID=your-service-account-appid
WECHAT_APP_SECRET=your-service-account-secret
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:7b
```

## WeChat Official Account Setup

Register and manage the service account in the WeChat Official Account console, then manage developer-facing settings in the WeChat Developer Platform. Since the December 2025 migration, the old Official Account path `Settings and Development -> Development Interface Management` has moved to:

```text
WeChat Developer Platform -> My Services -> Official Account / Service Account
```

Use these developer-platform locations:

1. `Basic Info`: find the account `AppID`.
2. `Basic Info -> Development Secret`: enable or reset `AppSecret`, and add the server egress IP to the API IP allowlist.
3. `Basic Info -> Domain and Message Push Config`: set the message push URL to `https://your-domain/wechat/official/callback`.
4. `Domain and Message Push Config`: set token to the same value as `WECHAT_TOKEN`, use plaintext message mode for the first validation build, and enable message push.
5. `API Management -> API Permissions and Quotas`: confirm customer-service messaging permissions are available if you want async model results.

If you use a personal subject account, complete administrator real-name verification before enabling `AppSecret`. For non-personal subjects, complete subject verification if the platform asks for it.

The backend immediately returns an acknowledgement to WeChat, then sends the final model answer through the customer-service message API.

## Local LLM Contract

The default LLM client expects an OpenAI-compatible endpoint:

```http
POST /v1/chat/completions
```

with a response shaped like:

```json
{
  "choices": [
    {
      "message": {
        "content": "..."
      }
    }
  ]
}
```

If your local model uses another protocol, replace `app/llm.py`.

## Current Commands

Send these in the service account chat:

- `帮助`
- `记住 我喜欢简洁的回答`
- `查看记忆`
- `清空记忆`
- `关闭记忆`
- `开启记忆`
- `提醒我 2026-05-30 09:00 检查某件事`

## H5 Settings

Validation page:

```text
https://your-domain/h5/settings?openid=USER_OPENID
```

This is intentionally simple. Before real users, replace the explicit `openid` parameter with WeChat webpage authorization and add CSRF/auth checks.

## Production Notes

- Add WeChat webpage OAuth for all H5 settings/payment pages.
- Add encrypted callback support if you enable WeChat safe mode.
- Add template/subscription notification for long-running or delayed tasks, because customer-service messages are window-limited.
- Add file upload through H5 or WeChat customer service if users need PDF/Word uploads.
- Add content safety, model/service registration handling, and explicit AI identity disclosure before public launch.
