# WeGent

WeGent 是一个面向微信服务号的个人 AI 办事助手验证项目。用户在服务号聊天框里发送文字或可识别语音，服务端接收微信消息，调用本地或内网大模型，再通过公众号客服消息把结果回复给用户。

当前版本适合小范围验证：

- 微信服务号消息推送 Token 校验
- 文本和语音识别结果处理
- 异步客服消息回复
- OpenAI-compatible 本地大模型网关
- SQLite 用户记忆、技能开关和定时任务骨架
- 简单 H5 设置页

## 架构

```text
微信服务号
  -> /wechat/official/callback
  -> FastAPI 消息网关
  -> SQLite 记忆 / 任务存储
  -> OpenAI-compatible 大模型接口
  -> 微信客服消息回复
```

## 目录

```text
app/
  assistant.py          助手逻辑、记忆指令、提醒任务
  config.py             环境变量配置
  db.py                 SQLite 存储
  llm.py                本地大模型网关
  main.py               FastAPI 入口和微信回调
  skills.py             内置技能注册表
  tasks.py              定时任务轮询
  wechat.py             微信签名、XML 解析、客服消息发送
  static/settings.html  验证版 H5 设置页
tests/                  基础测试
.env.example            配置模板
```

## 当前微信指令

```text
帮助
技能列表
技能详情 图片识别
安装技能 记忆
卸载技能 定时任务

记住 我喜欢简洁回答
查看记忆
忘记记忆 1
清空记忆
关闭记忆
开启记忆

提醒我 2026-06-03 09:00 检查某件事
任务列表
取消任务 1
```

当前可直接使用的技能是“记忆”和“定时任务”。“语音”和“图片识别”已经进入技能注册表，后续接入 ASR/TTS、图片下载和视觉模型后即可启用。

## 本地启动

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```text
http://127.0.0.1:8000/health
```

期望返回：

```json
{"status":"ok"}
```

## 环境变量

复制 `.env.example` 为 `.env` 后填写：

```env
PUBLIC_BASE_URL=https://your-domain.example

WECHAT_TOKEN=your-callback-token
WECHAT_APP_ID=your-service-account-appid
WECHAT_APP_SECRET=your-service-account-secret
WECHAT_VERIFY_SIGNATURE=true

LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=

DATA_DIR=./data
TIMEZONE=Asia/Shanghai
```

说明：

- `PUBLIC_BASE_URL`：公网访问地址，正式部署时填你的域名。
- `WECHAT_TOKEN`：微信消息推送页面填写的 Token，必须和微信开发者平台一致。
- `WECHAT_APP_ID` / `WECHAT_APP_SECRET`：服务号 AppID 和 AppSecret。
- `LLM_BASE_URL`：OpenAI-compatible 大模型接口地址。
- `LLM_MODEL`：模型名称。
- `WECHAT_VERIFY_SIGNATURE`：正式环境保持 `true`。

不要提交 `.env`。里面包含 AppSecret 等敏感信息。

## 大模型接口要求

默认客户端调用 OpenAI-compatible 接口：

```http
POST /v1/chat/completions
```

响应格式：

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

常见兼容来源：

- Ollama OpenAI-compatible endpoint
- vLLM
- LM Studio
- Xinference
- 自建 OpenAI-compatible 网关

如果你的模型接口不是这个协议，改 `app/llm.py` 即可。

## 微信服务号配置

先在 [微信公众平台](https://mp.weixin.qq.com/) 注册并管理服务号。开发接口相关配置已迁移到 [微信开发者平台](https://developers.weixin.qq.com/platform/)。

进入：

```text
微信开发者平台 -> 我的业务 -> 公众号/服务号
```

需要配置这些位置：

1. `基础信息`：查看 `AppID`。
2. `基础信息 -> 开发密钥`：启用或重置 `AppSecret`。
3. `基础信息 -> 开发密钥 -> API IP 白名单`：加入服务器出口公网 IP。
4. `基础信息 -> 域名与消息推送配置 -> 消息推送`：配置消息回调。
5. `接口管理 -> 接口权限与额度`：确认有客服消息相关权限。

消息推送填写：

```text
URL: https://your-domain.example/wechat/official/callback
Token: 与 .env 里的 WECHAT_TOKEN 一致
EncodingAESKey: 随机生成
消息加密: 明文模式
数据格式: XML
```

当前代码只支持明文模式。安全模式需要补充微信 AES 解密逻辑后再开启。

## 本地临时隧道验证

如果还没有备案域名或云服务器，可以用临时公网隧道验证消息闭环。

示例使用 Cloudflare Tunnel：

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

它会输出类似：

```text
https://example-name.trycloudflare.com
```

微信消息推送 URL 填：

```text
https://example-name.trycloudflare.com/wechat/official/callback
```

注意：

- 临时隧道地址可能变化。
- 电脑关机、网络变化或进程退出后需要重新配置。
- 临时隧道只适合小范围验证，不适合生产。

## 阿里云 ECS 部署

以下流程覆盖 Ubuntu/Debian 和 Alibaba Cloud Linux/CentOS/RHEL。阿里云 ECS 常见镜像不一定有 `apt`，请先确认系统类型。

### 1. 准备云资源

在阿里云购买中国内地 ECS 或轻量应用服务器。安全组放行：

```text
22/tcp    SSH
80/tcp    HTTP
443/tcp   HTTPS
```

如果使用中国内地服务器并绑定域名，正式上线前需要完成 ICP 备案。备案未完成时，可以先用临时隧道、香港/海外服务器，或只做本地验证。

### 2. 解析域名

在 DNS 控制台添加 A 记录：

```text
主机记录: @ 或你的子域名
记录类型: A
记录值: ECS 公网 IP
```

例如：

```text
api.example.com -> 1.2.3.4
```

### 3. 登录服务器

```bash
ssh root@your-server-ip
```

查看系统类型：

```bash
cat /etc/os-release
```

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nginx
```

Alibaba Cloud Linux / CentOS / RHEL：

```bash
sudo yum install -y git python3 python3-pip nginx
```

如果系统提示没有 `yum`，再试：

```bash
sudo dnf install -y git python3 python3-pip nginx
```

安装完成后确认版本：

```bash
git --version
python3 --version
pip3 --version
nginx -v
```

### 4. 拉取代码

```bash
cd /opt
git clone https://github.com/zyzzyvar/WeGent.git
cd WeGent
```

### 5. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

如果 `python3 -m venv .venv` 提示没有 `venv` 模块：

```bash
sudo yum install -y python3-virtualenv
python3 -m virtualenv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

如果执行 `pip install -e ".[dev]"` 提示 `Directory '.' is not installable. File 'setup.py' not found.`，通常是 `pip` 版本太旧，先执行上面的升级命令后再安装。

### 6. 写入配置

```bash
cp .env.example .env
nano .env
```

示例：

```env
PUBLIC_BASE_URL=https://api.example.com
WECHAT_TOKEN=wegent2026
WECHAT_APP_ID=your-appid
WECHAT_APP_SECRET=your-appsecret
WECHAT_VERIFY_SIGNATURE=true

LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:7b

DATA_DIR=/opt/WeGent/data
TIMEZONE=Asia/Shanghai
```

如果大模型也部署在同一台服务器，`LLM_BASE_URL` 可以保持本机地址。

如果大模型在家里或另一台内网机器，不建议直接把模型端口暴露到公网。建议使用 VPN、内网穿透白名单、SSH 反向隧道，或单独做带鉴权的大模型网关。

### 7. 测试启动

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个 SSH 窗口测试：

```bash
curl http://127.0.0.1:8000/health
```

返回：

```json
{"status":"ok"}
```

### 8. 配置 systemd

创建服务：

```bash
nano /etc/systemd/system/wegent.service
```

写入：

```ini
[Unit]
Description=WeGent WeChat AI Assistant
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/WeGent
EnvironmentFile=/opt/WeGent/.env
ExecStart=/opt/WeGent/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动：

```bash
systemctl daemon-reload
systemctl enable --now wegent
systemctl status wegent
```

查看日志：

```bash
journalctl -u wegent -f
```

### 9. 配置 Nginx 反向代理

创建站点：

```bash
nano /etc/nginx/sites-available/wegent
```

HTTP 配置：

```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用：

```bash
ln -s /etc/nginx/sites-available/wegent /etc/nginx/sites-enabled/wegent
nginx -t
systemctl reload nginx
```

测试：

```bash
curl http://api.example.com/health
```

### 10. 配置 HTTPS

建议使用 HTTPS 后再配置微信消息推送。

安装 Certbot：

```bash
apt install -y certbot python3-certbot-nginx
```

签发证书：

```bash
certbot --nginx -d api.example.com
```

测试：

```bash
curl https://api.example.com/health
```

微信消息推送 URL：

```text
https://api.example.com/wechat/official/callback
```

### 11. 配置微信 API IP 白名单

在服务器上查看出口 IP：

```bash
curl https://api.ipify.org
```

把返回的公网 IP 加到微信开发者平台：

```text
基础信息 -> 开发密钥 -> API IP 白名单
```

如果没有加入，调用微信接口会报：

```text
40164 invalid ip ... not in whitelist
```

### 12. 启用微信消息推送

微信开发者平台填写：

```text
URL: https://api.example.com/wechat/official/callback
Token: 与 WECHAT_TOKEN 一致
消息加密: 明文模式
数据格式: XML
```

点确定后，微信会发起 Token 校验。成功后关注服务号并发送：

```text
帮助
```

正常会先收到：

```text
收到，我正在处理。
```

随后收到模型生成的正式回复。

## 当前支持的聊天指令

在服务号聊天框发送：

```text
帮助
记住 我喜欢简洁的回答
查看记忆
清空记忆
关闭记忆
开启记忆
提醒我 2026-05-30 09:00 检查某件事
```

## H5 设置页

验证版地址：

```text
https://your-domain.example/h5/settings?openid=USER_OPENID
```

当前 H5 页为了验证方便，直接用 URL 参数传 `openid`。正式使用前必须改成微信网页授权，并补充登录态、CSRF、防越权访问等保护。

## 常见故障

### check token request timeout, 200301

微信访问消息推送 URL 超时。检查：

- 域名是否解析到正确公网 IP
- 服务器安全组是否放行 80/443
- Nginx 是否正常转发到 `127.0.0.1:8000`
- `curl https://your-domain/health` 是否返回 `{"status":"ok"}`
- 如果用 HTTP，不要把 URL 写成 HTTPS
- 如果用 HTTPS，证书和 TLS 握手必须正常

### Token 校验失败

检查：

- 微信页面 Token 是否和 `.env` 的 `WECHAT_TOKEN` 完全一致
- 服务是否重启并加载了新的 `.env`
- 当前是否选择了明文模式

### 只收到“收到，我正在处理”，没有最终回复

检查：

- `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET` 是否正确
- 微信 API IP 白名单是否包含服务器出口 IP
- 是否有客服消息权限
- 大模型接口是否可访问
- `journalctl -u wegent -f` 是否有异常日志

### 40164 invalid ip not in whitelist

把服务器出口 IP 加入微信开发者平台 API IP 白名单。

### 大模型连接失败

检查：

```bash
curl http://127.0.0.1:11434/v1/models
```

如果模型服务不在同一台机器，确认网络、鉴权、端口和防火墙。

### Cloudflare Tunnel 530

临时隧道连接到 Cloudflare 边缘节点失败或中断。重启 `cloudflared` 生成新地址，或改用正式云服务器/Nginx 部署。

## 生产化待办

- 支持微信安全模式 AES 解密
- H5 设置页接入微信网页授权
- 文件上传和文档解析
- 定时任务完成通知的模板/订阅消息通道
- 支付和订阅
- 用户协议、隐私政策、数据删除入口
- 生产数据库和备份策略
- 内容安全、AI 身份标识、日志审计
- 公开服务前处理 ICP、公安联网备案，以及生成式 AI 服务相关合规事项

## 测试

```bash
pytest
```

当前测试覆盖：

- 微信签名校验
- 微信 XML 消息解析
- 文本回复 XML 生成
- 已入库消息不重复进入模型上下文
