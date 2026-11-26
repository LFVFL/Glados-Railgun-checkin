# Glados-Railgun-checkin

GLaDOS（Railgun）每日自动签到 + PushPlus 手机美化推送。**配好之后不用管，每天自动跑。**

站点在 2026 年给签到接入了 **Cloudflare Turnstile**，原来的纯 `requests` 脚本会被判 `code=5 turnstile`。
本仓库的做法是：用 **Peak Solutions 求解服务**拿到 Turnstile token，再按站点前端完全一致的算法提交签到。
不需要浏览器、不需要自己的电脑开机，GitHub 免费额度就够。

![推送效果](imgs/preview.png)

> 上图账号与 IP 均为虚构示例。

---

## 0. 三分钟上手（照这个顺序做就行）

如果你是第一次用，**只看这一节就够了**。全程不需要装任何软件。

### 第 1 步：Fork 这个仓库

点右上角 **Fork** → 保持默认 → **Create fork**。
（你自己的仓库才能存自己的 Cookie 和密钥。）

### 第 2 步：注册 Peak Solutions，拿一个 key

1. 打开 <https://peak.fo>，用邮箱注册（**新账号送 1000 次免费求解**，够用很久）；
2. 登录后进 **Dashboard → API Keys**，创建一个 key；
3. 复制那串以 `pk_` 开头的字符串，先存到记事本里。

> 为什么用它：签到时站点要验证 Cloudflare Turnstile，而这个验证必须由「像真人」的客户端完成。
> Peak 就是干这个的，几秒返回 token，不需要你本机跑浏览器。
> 单次求解约 $0.001，1000 次免费额度按「每账号每天 1 次」算够用很久（脚本会先查今天是否已签，已签不花钱）。

### 第 3 步：取 Cookie（最关键的一步，慢一点没关系）

1. 电脑上用 **Chrome** 打开 <https://glados.space/console> 并登录你的账号；
2. 按 **F12** 打开开发者工具 → 切到 **Network（网络）** 标签；
3. 按 **F5** 刷新页面；
4. 在请求列表里点任意一条 `glados.space` 开头的请求；
5. 右侧找到 **Request Headers（请求标头）** → 找 **Cookie** 那一行；
6. 把这一行的**完整内容**复制出来。长这样：

```
gld:sess=AAAA...; gld:sess.sig=BBBB...; gld:accts=CCCC...; gld:accts.sig=DDDD...
```

> 一定要把 `gld:sess`、`gld:sess.sig`、`gld:accts`、`gld:accts.sig` **四段全带上**，少一段就会登录失败。
> 复制的时候不要带 `Cookie:` 这个前缀，只要冒号后面的值。

**多个账号怎么弄**：每个账号分别按上面步骤取一份，然后用 `&` 拼成一行：

```
gld:sess=账号1...; gld:sess.sig=账号1...&gld:sess=账号2...; gld:sess.sig=账号2...&gld:sess=账号3...; ...
```

推送里会用**邮箱 `@` 前面的部分**做标题（比如 `alice`、`bob`），一眼就能对上是谁。

### 第 4 步：注册 PushPlus，拿推送 token

1. 打开 <https://www.pushplus.plus>，微信扫码登录；
2. 首页能看到你的一串 **token**（32 位），复制下来；
3. 关注它的微信公众号，这样推送会直接发到微信。

**想同时推给好几个人**：在里面建一个「群组」把大家都加进去，用**群组 token** 即可；
或者直接把多串 token 用 `&` 拼起来填进 secret（脚本会逐个推送同一份内容）。

### 第 5 步：把上面拿到的值填进 GitHub Secrets

进你自己的仓库 → **Settings（设置）** → 左侧 **Secrets and variables** → **Actions**
→ 右上 **New repository secret**，依次添加下面三条：

| Name（名字，必须一字不差） | Secret（值） |
|---|---|
| `GLADOS_COOKIES` | 第 3 步复制的 Cookie（多账号用 `&` 连接） |
| `PUSHPLUS_TOKEN` | 第 4 步的 PushPlus token（多个用 `&` 连接） |
| `TURNSTILE_PROVIDER` | 固定填 `peak` |
| `TURNSTILE_API_KEY` | 第 2 步的 `pk_...` key |

> 注意：**Name 是区分大小写的**，必须和上表完全一致。值直接粘贴，不要加引号。

### 第 6 步：手动跑一次，确认成功

1. 点仓库上方 **Actions** 标签；
2. 左侧选 **auto check**；
3. 右边点 **Run workflow** → **Run workflow**；
4. 等约 1 分钟，点进这次运行，看日志里出现：

```
共 3 个账号 · 引擎=api(peak)
返回 code=0 reason=None repeated=False
汇总: 成功 1 · 已签 2 · 失败 0 · 本次 +2 分
PushPlus 推送成功 [1/1]: GLaDOS 签到成功 · +2分
```

看到 `code=0`（新签到）或 `code=1`（今天已签过，正常）就说明通了，同时微信会收到推送。

### 第 7 步：什么都不用做了

默认每天自动跑两次（北京时间 **09:18** 和 **12:18**）。
第二次是兜底：如果第一次因为网络抖动失败，第二次还能补上；已经签过的账号不会重复加分，
而且**不会重复消耗求解额度**（脚本先查签到记录，已签就跳过）。

---

## 0.1 常见卡住的点（新手必看）

| 现象 | 原因与解法 |
|---|---|
| 日志 `code=4 reason=device-mismatch` | UA 和登录设备不一致。脚本会**自动**按 `loginDevice` 换 UA 重试，看到这条后紧跟着 `code=0/1` 就属于正常过程 |
| 日志 `code=5 reason=turnstile` | 求解服务返回的 token 被拒。**先确认 `action=checkin` 和 `cdata=nonce` 都传了**（本仓库已内置）；仍失败再换 provider 或换网络 |
| 日志 `code=1 repeated=True`，`本次 +0 分` | 今天已经签过了，**正常**，不是失败 |
| `缺少 GLADOS_COOKIES` | 第 5 步的 secret 名字拼错了，或值留空 |
| 推送标题是 `GLaDOS 今日已签` | 三个账号今天都签过了，正常 |
| 连续 / 剩余 显示 `—` | 站点没返回对应字段；一般刷新一次就好，不影响签到 |
| 微信收不到推送 | PushPlus 里没关注公众号，或 token 填错；去 PushPlus 后台看「发送记录」 |
| 想改执行时间 | 改 `.github/workflows/gladosCheck.yml` 里的 `cron: '18 1,4 * * *'`（**UTC 时间**，北京时间 = UTC+8） |
| Actions 到点没跑 | GitHub 的定时任务高峰期会延迟几分钟到半小时，属正常；可以点 Run workflow 手动补一次 |

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

## 2. 两种引擎（关键）

Cloudflare Turnstile 是**反自动化**组件，token 只能由真实、非自动化的浏览器产生。实测：

| 运行环境 | 引擎 | 结果 |
|---|---|---|
| 本地真实桌面（Windows/macOS） | browser（headful） | ✅ 自动通过，签到成功 |
| GitHub 托管 runner（无 GPU 虚拟机） | browser（headful） | ❌ widget 不完成，`code=None` |
| 任意环境 | browser（headless） | ❌ `tsState=error`，`code=5 turnstile` |

因此脚本提供 **两个引擎**：

### 引擎 A：`api`（CI 推荐）

纯 HTTP，不需要浏览器：先由**Turnstile 求解服务**拿 token，再按前端同样的算法提交。

```
challenge -> 求解服务(sitekey + pageurl + action=checkin + cdata=nonce) -> token
          -> proof = sha256(nonce + ".glados-observe-v1") -> POST /api/user/checkin
```

支持 `peak` / `capsolver` / `yescaptcha` / `2captcha`。内置 **UA 自动对齐**：遇到 `code=4 device-mismatch`
会读取 `loginDevice` 并自动切换到对应系统 UA 重试，所以 Windows / Android / iOS / macOS 的 cookie 都能用。

> **`peak` 是本项目实测唯一跑通的 provider**（[peak.fo](https://peak.fo)，Cloudflare 专精，
> 单次 POST 同步返回 token，无需轮询，新账号送 1000 次免费）。
> 关键点：必须把 `action=checkin` 和 `cdata=<本次 nonce>` 一起传给求解服务——
> Cloudflare 会把这两个值绑进 token，缺任一（或 cdata 用了旧 nonce）服务端会回 `code=5 turnstile`。

### 引擎 B：`browser`（本地 / 自建 runner 推荐）

Playwright 驱动真实 Chromium（headful）现场通过 Turnstile，**只有在真实桌面环境才有效**。

> 选择逻辑：配置了 `TURNSTILE_PROVIDER` + `TURNSTILE_API_KEY` 走 `api`，否则走 `browser`。

## 3. 三种落地方式

| 方案 | 成本 | 稳定性 | 说明 |
|---|---|---|---|
| **① 求解服务 + GitHub Actions** | 约 ¥0.01~0.05/次 | ⭐⭐⭐⭐⭐ | 推荐，配两个 secret 即可 |
| **② 自建 runner（自己的电脑/NAS/软路由）** | 免费 | ⭐⭐⭐⭐⭐ | 用 `gladosCheck.selfhosted.yml`，真实桌面，browser 引擎必过 |
| **③ GitHub 托管 runner + browser 引擎** | 免费 | ⭐ | 实测过不了 Turnstile，**不推荐** |

### 自建 runner 怎么跑

1. 仓库 **Settings → Actions → Runners → New self-hosted runner**，按提示在目标机器
   （Windows 桌面 / macOS，需有真实图形会话）上执行 `config.cmd`，标签保持默认；
2. 仓库里启用 `.github/workflows/gladosCheck.selfhosted.yml`（默认只允许手动触发，
   想定时就把文件里的 `schedule` 取消注释，并停用 `gladosCheck.yml` 的定时）；
3. 该工作流用 `runs-on: [self-hosted, Windows, X64]` + 系统 Chrome，headful 直跑。

> 为什么免费方案里只有自建 runner 靠谱：Turnstile 判定的是**真实浏览器环境**
> （GPU、渲染、输入事件、指纹自洽），托管 runner 的虚拟机在这几项上都露馅。

## 4. device-mismatch 说明

站点把**登录设备**与**当前设备**比对，依据是 UA 里的操作系统：

```
code=4 reason=device-mismatch  loginDevice=Android  currentDevice=Windows
```

- `api` 引擎会按 `loginDevice` 自动切换 UA；
- `browser` 引擎要求运行环境与登录设备一致（如都用 Windows 桌面 Chrome）。

---

## 5. 部署（GitHub Actions）

1. Fork 本仓库。
2. 仓库 **Settings → Secrets and variables → Actions → New repository secret**：

   | Secret | 必填 | 说明 |
   |---|---|---|
   | `GLADOS_COOKIES` | ✅ | 一个或多个账号的 Cookie，多账号用 `&` 连接 |
   | `PUSHPLUS_TOKEN` | 建议 | PushPlus token。**多接收方用 `&` 连接**（如 `tokA&tokB`），会逐个推送同一份内容；不填则只打日志 |
   | `TURNSTILE_PROVIDER` | 推荐 | `peak` / `capsolver` / `yescaptcha` / `2captcha` |
   | `TURNSTILE_API_KEY` | 推荐 | 求解服务的 API Key |

   > 不配 `TURNSTILE_*` 时走浏览器引擎；GitHub 托管 runner 上过不了 Turnstile（见第 2 节）。

3. **Actions → auto check → Run workflow** 手动跑一次，确认日志出现
   `返回 code=0/1` 与 `PushPlus 推送成功`。
4. 之后按 `cron: '18 1,4 * * *'`（北京时间 09:18 / 12:18）自动执行。

多账号签到结果里，每张卡片的标题是**邮箱 `@` 之前的部分**（如 `demo.alice`、`demo.bob`、`demo.carol`），
一眼就能对上是谁，不显示域名后缀以节省窄屏宽度；取不到邮箱时回退成 `账号 #N`。

> 每天跑两次是冗余设计：第一次若遇到网络/求解抖动，第二次还能补上；
> 已经签过的账号会返回 `code=1`，不重复加分。`peak` 每次求解都会计费，
> 但 api 引擎在求解**之前**会先查 `/api/user/points` 的今日签到记录，
> 已签就直接返回、不调用求解服务（实测余额零消耗），
> 所以 1000 次免费额度实际是按「每天每账号 1 次」在耗，约够 330 天（3 账号）。
> 预检查查询失败时不会误判，照常走完整求解流程。

### 实测验证记录（2026-11-26）

| 环节 | 结果 |
|---|---|
| 本地 `peak` 求解 → 提交 | **`code=0 Checkin! Got 2 Points`**（`demo.alice@example.com` +2 分） |
| 本地 PushPlus 推送 | 成功，标题 `GLaDOS 签到成功 · +2分` |
| GitHub Actions api 引擎（单账号） | `code=1 repeated=True`，`PushPlus 推送成功`，run success |
| GitHub Actions api 引擎（三账号） | `成功 0 · 已签 3 · 失败 0`，其中一账号自动走 `code=4 → android UA` 重试成功 |
| 推送标题三态 | 已签 → `GLaDOS 今日已签 · 无需重复`；新签 → `签到成功 · +N分`；失败 → `签到异常(N)` |

### 求解服务怎么配

**Peak（推荐，本项目实测跑通）**：在 <https://peak.fo/dashboard/keys> 注册，新账号送 1000 次免费，
拿到 `pk_...` 后：

```
TURNSTILE_PROVIDER = peak
TURNSTILE_API_KEY  = pk_xxxxxxxxxxxxxxxx
```

CapSolver / YesCaptcha / 2Captcha 同理，把 provider 换成对应名字即可
（脚本已内置这四家的求解流程；peak 是唯一实测验证过的）。

### Cookie 怎么取

1. 桌面版 Chrome 打开 <https://glados.space/console> 并登录；
2. `F12` → **Network** → 刷新页面 → 点任一 `glados.space` 请求；
3. **Request Headers → Cookie**，复制 `gld:sess=...; gld:sess.sig=...; gld:accts=...; gld:accts.sig=...`；
4. 多账号：每个账号单独按上面步骤取一份，用 `&` 拼成一行。

```
gld:sess=AAA; gld:sess.sig=BBB; gld:accts=CCC; gld:accts.sig=DDD&gld:sess=EEE; gld:sess.sig=FFF; ...
```

---

## 6. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `GLADOS_COOKIES` | – | 必填，cookie 串，多账号用 `&` 分隔 |
| `PUSHPLUS_TOKEN` | – | PushPlus token，多接收方用 `&` / `,` / `;` / 空白分隔，自动去重，逐个推送相同内容 |
| `TURNSTILE_PROVIDER` | – | 求解服务：`peak` / `capsolver` / `yescaptcha` / `2captcha`（配置后走 api 引擎） |
| `TURNSTILE_API_KEY` | – | 求解服务 API Key |
| `GLADOS_PROXY` | – | 出口代理，`http://user:pass@host:port` 或 `socks5://host:port`。**IP 被限流时填这个最有效** |
| `GLADOS_HEADLESS` | `0` | browser 引擎必须 `0`；`1` 会因 Turnstile 拿不到 token 失败 |
| `GLADOS_RETRY` | `3` | browser 引擎失败重试次数 |
| `GLADOS_BROWSER_CHANNEL` | – | 本地可设 `chrome` 用系统 Chrome；CI 留空用 Playwright 自带 Chromium |

---

## 7. 本地运行

```bash
pip install -r requirements.txt
python -m playwright install chromium

# Windows PowerShell（browser 引擎）
$env:GLADOS_COOKIES = "gld:sess=...; gld:sess.sig=..."
$env:PUSHPLUS_TOKEN  = "your_token"
python checkin.py

# 或者用 api 引擎（无需浏览器）
$env:TURNSTILE_PROVIDER = "capsolver"
$env:TURNSTILE_API_KEY  = "CAP-xxxx"
python checkin.py
```

Linux 无桌面时（browser 引擎）：

```bash
xvfb-run -a --server-args="-screen 0 1440x900x24" python checkin.py
```

---

## 8. 推送效果

采用**手机优先**布局（PushPlus 主要在微信内置浏览器查看）：账号卡片式排列，
四宫格指标、状态徽标、出口 IP 与原始返回信息分层展示，窄屏不会挤成一条缝。

<img src="imgs/preview.png" width="330" alt="推送效果">

- 卡片标题 = 该账号邮箱 @ 之前的部分（下图中的 demo.alice 等均为**虚构示例**）；
- 状态徽标三种：签到成功（绿）/ 今日已签（蓝）/ 失败时为红色；
- 本次 / 总积分 / 连续天数 / 剩余天数 四项指标；
- 底部是出口 IP 与站点原始返回信息，便于排查。

> 截图中的账号名、积分、IP（203.0.113.10 是文档专用保留网段）全部为假数据。

---

## 9. 常见问题

**Q: 日志出现 `code=None`（一直没有 POST）**
浏览器引擎里 Turnstile widget 没完成。看日志里那行 `Turnstile 资源加载异常`：

- 出现 `400 .../cdn-cgi/challenge-platform/...`：**当前出口 IP 被 Cloudflare 限流**。
  这是最常见的故障——同一个 IP 在 Cloudflare 眼里“可疑”时，challenge 端点直接 400，
  widget 不会渲染，签到请求根本发不出去。
  **首选对策：配 `GLADOS_PROXY` 换个干净出口**，其次换网络（家宽 ↔ 手机热点）、
  等几小时冷却，或改用 `api` 引擎（求解服务自带干净出口）。
  用第三方 Turnstile 演示页（如 `nopecha.com/demo/turnstile`）也能复现 400，
  说明与本脚本、与 glados 都无关（用代理访问该演示页可反向确认代理是否干净）。
- 出现 `failed net::ERR_...`：本地网络/代理/DNS 拦了 `challenges.cloudflare.com`。
- 什么都没打印：页面没加载完，检查 cookie 是否已失效。

**Q: 日志出现 `code=5 reason=turnstile`**
Turnstile 没通过（此时说明设备检查已通过，只差 token）。若用的是 `api` 引擎，
多为求解服务 token 与本站参数/IP 不匹配，换 provider 或换线路；
若用 `browser` 引擎，同上先排查 IP 限流。

**Q: 日志出现 `code=4 reason=device-mismatch`**
`api` 引擎会自动切换 UA 重试；若仍失败，看日志里的 `loginDevice`，确认对应 UA 配置文件存在。
`browser` 引擎则需运行环境与登录设备一致。

**Q: 日志出现 `code=1 repeated: true`**
今天已经签过了，属于正常情况，不会重复加分。

**Q: 登录页能打开但按钮一直不出现**
cookie 失效（被登出）。重新登录拿新 cookie。

---

## 10. 变更说明

- **2026-11-26**：适配 Cloudflare Turnstile。
  - 新增 `engine_api.py`：Turnstile 求解服务（capsolver/yescaptcha/2captcha）+ 纯 HTTP 提交，
    并自动对齐 `loginDevice` 的 UA（解决 `device-mismatch`）；
  - `checkin.py` 保留 Playwright 浏览器引擎（真实桌面可用），按环境变量自动选择引擎；
  - 按前端算法补上 `proof = sha256(nonce + ".glados-observe-v1")`；
  - 推送后端改为 PushPlus，手机优先卡片式排版；
  - 工作流改为 `ubuntu-latest`，有求解服务走 api 引擎，否则回退 xvfb + 浏览器引擎。
- **2026-11-26（续）**：跑通 Peak Solutions，取得真实 `code=0`。
  - 新增 provider `peak`（peak.fo，单次 POST 同步返回 token，无需轮询）；
  - **定位到 `code=5 turnstile` 的真正原因**：求解时必须同时传 `action=checkin` 与
    `cdata=<本次 nonce>`。缺二者之一服务端就拒收 token，与 IP、UA、浏览器无关；
  - 实测结果：无 action → `code=5`；仅 action → `code=5`；
    `action+cdata` → **`code=0 Checkin! Got 2 Points`**；
  - 两个引擎都支持 `GLADOS_PROXY`（`session.proxies` / Playwright `proxy`），
    代理不可用时明确报错而非静默失败；
  - 出口 IP 被 Cloudflare 限流时（challenge 端点 400）立即放弃本轮重试，避免情况恶化。
- **2026-11-26（三）**：多账号可辨识 + 推送标题三态化。
  - 推送卡片标题由 `账号 #N` 改为邮箱前缀（读 `/api/user/status` 的 `data.email`，
    只保留 `@` 前部分），多账号不再需要人工对数；
  - 推送标题区分「今日已签 / 签到成功 +N分 / 签到异常(N)」，
    不再出现「签到成功 · +0分」这种看起来像刚签过的误导文案；
  - `AccountResult` 新增 `email` 字段，两个引擎都会填充。
- **2026-11-26（四）**：省求解额度 —— 新增「今日已签」预检查。
  - `api` 引擎在调用求解服务之前先查 `/api/user/points`，
    若 `history` 里已有当天的 `system:checkin`，直接按 `code=1 repeated` 返回，
    **不消耗求解额度**；实测 Peak 余额 `0.8838 → 0.8838` 零变动；
  - 查询失败（网络/接口异常）时返回 `None` 并继续完整流程，
    不会因为查不到就误判成「已签」而漏签；
  - 每天两次 cron 的意义由此变为纯冗余：第一次签到，第二次只是兜底。
- **2026-11-26（五）**：多接收方推送 + 字段修正 + 新手文档。
  - `PUSHPLUS_TOKEN` 支持填多个 token（`&` / `,` / `;` / 空白分隔），
    自动去重后逐个推送**同一份内容**；单个 token 失效只影响它自己，其余照常送达；
  - 修正两处字段名：剩余天数实际在 `status.data.leftDays`（不是 `daysLeft`）、
    连续天数在 `points.streak`（不是签到返回里），此前这两项一直显示 `—`；
  - 仓库预览图改用虚构账号（`demo.alice` / `demo.bob` / `demo.carol`）
    与文档专用 IP `203.0.113.10`，不再暴露真实邮箱前缀；
  - README 新增「三分钟上手」7 步教程和「常见卡住的点」对照表，面向前端零基础用户。

## 免责声明

仅供个人账号自动签到使用。请遵守站点服务条款，脚本自负风险。