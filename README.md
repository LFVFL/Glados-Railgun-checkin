# Glados-Railgun-checkin

GLaDOS（Railgun）每日自动签到 + PushPlus 美化推送。

站点在 2026 年给签到接入了 **Cloudflare Turnstile**，原来的纯 `requests` 脚本会被判 `code=5 turnstile`。
本仓库改用 **Playwright 驱动真实 Chromium** 现场通过 Turnstile，再按站点前端完全一致的算法提交签到。

---

## 1. 签到链路（逆向自站点前端）

```
GET  /api/user/checkin/challenge
     -> { code:0, nonce, ttl:300000, turnstile:"0x4AAAAAAFF5pkT0bg7fX7nw", ip }

Turnstile 组件（站点用 render 动态挂载）
     sitekey    = 上面的 turnstile 字段
     action     = "checkin"
     cData      = nonce
     appearance = "interaction-only"     # 正常情况下无需点击，自动通过

POST /api/user/checkin
     body = { token: location.hostname, nonce, proof, tsState, turnstile }
     proof = sha256(nonce + ".glados-observe-v1")   # hex
```

`proof` 的密钥 `glados-observe-v1` 来自站点 JS 里的字符码数组
`[103,108,97,100,111,115,45,111,98,115,101,114,118,101,45,118,49]`。

服务端返回码：

| code | reason | 含义 |
|---|---|---|
| 0 | – | 签到成功，`points` 为本次收益 |
| 1 | – | 今日已签（`repeated: true`），不会重复计分 |
| 4 | `device-mismatch` | 当前 UA 与登录设备不一致，返回 `loginDevice` / `currentDevice` |
| 5 | `turnstile` | Cloudflare 校验未通过，`retryable: true`，**什么都没记录** |

> `code=5` 不会写入任何记录，所以可以安全重试。脚本默认重试 3 次。

---

## 2. 为什么必须是 headful

| 模式 | 结果 |
|---|---|
| headless | Turnstile 拿不到 token（`tsState=error`），提交后 `code=5 turnstile` |
| headful（真实桌面会话） | Turnstile 自动通过（`tsState=ok`），签到成功 |

所以：

- **GitHub Actions** 用 `windows-latest`（自带交互式桌面会话）原生 headful 运行；
- **Linux** 需要 `xvfb-run`；
- **本地**直接有头运行即可。

## 3. device-mismatch 说明（重要）

站点会把**登录设备**与**当前设备**做比对，判定依据是 UA 里的操作系统：

```
code=4 reason=device-mismatch  loginDevice=Windows  currentDevice=Linux   # xvfb + 默认 UA
code=4 reason=device-mismatch  loginDevice=Android  currentDevice=Windows
```

因此 **cookie 必须来自与运行环境一致的登录**：

- CI 跑 `windows-latest` → 用 **Windows 桌面 Chrome** 登录后抓的 cookie；
- 若你是用手机（Android/iOS）登录的，请用桌面 Chrome 重新登录一次，再抓 cookie。

> 只改 UA 不改 Client Hints 也能骗过设备检查，但 Turnstile 会因 UA 与
> `navigator.userAgentData` 不一致而失败，所以**不要伪造**，直接让环境自洽。

---

## 4. 部署（GitHub Actions）

1. Fork 本仓库。
2. 仓库 **Settings → Secrets and variables → Actions → New repository secret**：

   | Secret | 必填 | 说明 |
   |---|---|---|
   | `GLADOS_COOKIES` | ✅ | 一个或多个账号的 Cookie，多账号用 `&` 连接 |
   | `PUSHPLUS_TOKEN` | 建议 | PushPlus token，不填则只打日志 |

3. **Actions → auto check → Run workflow** 手动跑一次，确认日志出现
   `返回 code=0/1` 与 `PushPlus 推送成功`。
4. 之后按 `cron: '18 1,4 * * *'`（北京时间 09:18 / 12:18）自动执行。

### Cookie 怎么取

1. 桌面版 Chrome 打开 <https://glados.space/console> 并登录；
2. `F12` → **Network** → 刷新页面 → 点任一 `glados.space` 请求；
3. **Request Headers → Cookie**，复制 `gld:sess=...; gld:sess.sig=...; gld:accts=...; gld:accts.sig=...`；
4. 多账号：每个账号单独按上面步骤取一份，用 `&` 拼成一行。

```
gld:sess=AAA; gld:sess.sig=BBB; gld:accts=CCC; gld:accts.sig=DDD&gld:sess=EEE; gld:sess.sig=FFF; ...
```

---

## 5. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `GLADOS_COOKIES` | – | 必填，cookie 串，多账号用 `&` 分隔 |
| `PUSHPLUS_TOKEN` | – | PushPlus token |
| `GLADOS_HEADLESS` | `0` | **保持 0**；设 1 会因 Turnstile 失败 |
| `GLADOS_RETRY` | `3` | Turnstile/网络失败时的重试次数 |
| `GLADOS_BROWSER_CHANNEL` | – | 本地可设 `chrome` 用系统 Chrome；CI 留空用 Playwright 自带 Chromium |
| `GLADOS_UA` | – | 需要对齐登录设备时才用，一般留空 |

---

## 6. 本地运行

```bash
pip install -r requirements.txt
python -m playwright install chromium

# Windows PowerShell
$env:GLADOS_COOKIES = "gld:sess=...; gld:sess.sig=..."
$env:PUSHPLUS_TOKEN  = "your_token"
python checkin.py
```

Linux 无桌面时：

```bash
xvfb-run -a --server-args="-screen 0 1440x900x24" python checkin.py
```

---

## 7. 推送效果

采用**手机优先**布局（PushPlus 主要在微信内置浏览器查看）：账号卡片式排列，
四宫格指标、状态徽标、出口 IP 与原始返回信息分层展示，窄屏不会挤成一条缝。

<img src="imgs/preview.png" width="330" alt="推送效果">

---

## 8. 常见问题

**Q: 日志出现 `code=5 reason=turnstile`**
说明 Turnstile 没通过。依次检查：是否 headful；CI 是否用 `windows-latest`；
是否有 CDN/代理拦截 `challenges.cloudflare.com`；cookie 是否已过期。

**Q: 日志出现 `code=4 reason=device-mismatch`**
cookie 的登录设备与运行环境不一致。看日志里的 `loginDevice` / `currentDevice`，
用与运行环境相同的设备重新登录并抓 cookie。

**Q: 日志出现 `code=1 repeated: true`**
今天已经签过了，属于正常情况，不会重复加分。

**Q: 登录页能打开但按钮一直不出现**
cookie 失效（被登出）。重新登录拿新 cookie。

---

## 9. 变更说明

- **2026-11-26**：适配 Cloudflare Turnstile。改用 Playwright 真实 Chromium 通过
  `action=checkin / cData=nonce / interaction-only` 校验；按前端算法补上
  `proof = sha256(nonce + ".glados-observe-v1")`；推送后端改为 PushPlus，
  并使用手机优先的卡片式排版；新增失败自动重试与 `device-mismatch` 诊断。

## 免责声明

仅供个人账号自动签到使用。请遵守站点服务条款，脚本自负风险。