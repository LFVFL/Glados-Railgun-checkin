"""GLaDOS / Railgun 自动签到（Cloudflare Turnstile 版）

流程（与站点前端完全一致，逆向自 glados.space 的 main~189dec1b chunk）：
  1. GET  /api/user/checkin/challenge      -> {nonce, ttl, turnstile(sitekey), ip}
  2. Turnstile widget: sitekey, action="checkin", cData=nonce, appearance="interaction-only"
  3. 必须等 nonce 生成后 >= 2500ms 再提交
  4. proof = sha256(nonce + ".glados-observe-v1")   （key 来自站点 JS 的字符码数组）
  5. POST /api/user/checkin  {token: hostname, nonce, proof, tsState, turnstile}
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CONSOLE_URL = "https://glados.space/console/checkin"
CHECKIN_PATH = "/api/user/checkin"
CHALLENGE_PATH = "/api/user/checkin/challenge"
PROOF_KEY = "glados-observe-v1"  # 站点 JS: [103,108,97,100,111,115,45,111,98,115,101,114,118,101,45,118,49]
MIN_GAP_MS = 2500


def proof_of(nonce: str) -> str:
    return hashlib.sha256(f"{nonce}.{PROOF_KEY}".encode()).hexdigest()


def parse_cookie_string(raw: str) -> List[Dict[str, Any]]:
    """把 `a=1; b=2` 形式的 cookie 串转成 Playwright 的 cookie 结构。

    站点 cookie 没有显式 SameSite，Chromium 会把 SameSite=None 且非 Secure 的直接丢弃，
    所以这里统一给 Lax，并关掉 httpOnly/secure 的推断。
    """
    out: List[Dict[str, Any]] = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        out.append(
            {
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".glados.space",
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        )
    return out


@dataclass
class AccountResult:
    ok: bool = False
    repeated: bool = False
    points: Optional[float] = None
    gained: Optional[float] = None
    streak: Optional[int] = None
    days_left: Optional[int] = None
    plan: str = "-"
    traffic_used: str = "-"
    ip: str = "-"
    message: str = ""
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)


def human_gb(n: float) -> str:
    return f"{n / 1024 ** 3:.2f} GB"


def wait_for_button(page, log, timeout_s: int = 45) -> str:
    """等前端拿到 challenge 并把签到按钮渲染出来。"""
    deadline = time.time() + timeout_s
    labels: List[str] = []
    while time.time() < deadline:
        labels = page.evaluate(
            f"Array.from(document.querySelectorAll('button')).map(b => b.innerText.trim())"
        )
        for label in labels:
            if label.lower() in ("checkin", "retry", "重试", "签到"):
                return label
        page.wait_for_timeout(1500)
    raise RuntimeError(f"签到按钮未渲染，当前按钮: {labels}")


def attempt_checkin(page, log, timeout_s: int = 75) -> Dict[str, Any]:
    """导航到签到页，点按钮，等 POST /api/user/checkin 的响应。"""
    log("打开签到页…")
    page.goto(
        CONSOLE_URL,
        wait_until="domcontentloaded",
        timeout=90_000,
        referer="https://glados.space/console",
    )

    label = wait_for_button(page, log)
    log(f"点击按钮: {label}")

    captured: List[Dict[str, Any]] = []

    def on_response(resp):
        if CHECKIN_PATH in resp.url and resp.request.method == "POST":
            record: Dict[str, Any] = {"status": resp.status}
            try:
                record["body"] = resp.json()
            except Exception:
                record["body"] = {"raw": (resp.text() or "")[:400]}
            raw = resp.request.post_data or ""
            record["post"] = raw
            try:
                sent = json.loads(raw)
            except Exception:
                sent = {}
            record["tsState"] = sent.get("tsState")
            record["has_token"] = bool(sent.get("turnstile"))
            captured.append(record)

    page.on("response", on_response)
    try:
        page.evaluate(
            """() => {
                const b = Array.from(document.querySelectorAll('button'))
                    .find(x => /^(checkin|retry|重试|签到)$/i.test(x.innerText.trim()));
                if (b) b.click();
            }"""
        )

        # Turnstile 自动通过通常 3~20s；interaction-only 下偶尔更慢，给足窗口
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            if captured:
                return captured[-1]
            left = int(deadline - time.time())
            if left % 10 < 2:
                log(f"  等待 Cloudflare 校验… 剩余 {left}s")
        return {}
    finally:
        page.remove_listener("response", on_response)


def run_account(index: int, cookie_raw: str, headless: bool, log) -> AccountResult:
    from playwright.sync_api import sync_playwright

    result = AccountResult()
    log(f"开始处理账号 #{index}")

    channel = os.environ.get("GLADOS_BROWSER_CHANNEL", "").strip() or None
    ua = os.environ.get("GLADOS_UA", "").strip() or None
    attempts = max(1, int(os.environ.get("GLADOS_RETRY", "3") or 3))

    context_kwargs: Dict[str, Any] = {
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "viewport": {"width": 1440, "height": 900},
    }
    if ua:
        context_kwargs["user_agent"] = ua

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            channel=channel,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(**context_kwargs)
        context.add_cookies(parse_cookie_string(cookie_raw))
        page = context.new_page()

        body: Dict[str, Any] = {}
        record: Dict[str, Any] = {}

        for attempt in range(1, attempts + 1):
            if attempt > 1:
                log(f"第 {attempt} 次尝试…")
                page.wait_for_timeout(3000)

            try:
                record = attempt_checkin(page, log)
            except Exception as exc:
                log(f"  第 {attempt} 次失败: {str(exc)[:120]}")
                record = {}

            body = record.get("body") or {}
            code = body.get("code")
            log(
                f"  返回 code={code} reason={body.get('reason')} "
                f"tsState={record.get('tsState')} token={record.get('has_token')}"
            )

            if code in (0, 1) or body.get("repeated"):
                break
            if code == 4 and body.get("reason") == "device-mismatch":
                result.detail["mismatch"] = {
                    "loginDevice": body.get("loginDevice"),
                    "currentDevice": body.get("currentDevice"),
                }
                log("  设备不匹配：请用与登录时相同的操作系统/浏览器 UA")
                break
            if attempt < attempts:
                log("  Cloudflare 校验未通过，重试…")

        result.detail["checkin"] = body
        result.detail["attempts"] = record

        # challenge 里带的客户端 IP，用于推送展示
        try:
            ch = page.evaluate(
                "async () => (await (await fetch('/api/user/checkin/challenge', {credentials:'include'})).json())"
            )
            if isinstance(ch, dict) and ch.get("ip"):
                result.ip = ch["ip"]
        except Exception:
            pass

        # 账号状态 / 积分，用于推送排版
        for key, path in (
            ("status", "/api/user/status"),
            ("points", "/api/user/points"),
        ):
            try:
                result.detail[key] = page.evaluate(
                    f"async () => (await (await fetch('{path}', {{credentials:'include'}})).json())"
                )
            except Exception:
                pass

        result.detail["cookie_count"] = len(context.cookies())
        context.close()
        browser.close()

    code = body.get("code")
    result.repeated = bool(body.get("repeated"))
    result.message = str(body.get("message") or "").strip()
    result.reason = str(body.get("reason") or "")
    result.ok = bool(code in (0, 1) or result.repeated)

    if body.get("points") is not None:
        try:
            result.points = float(body["points"])
        except (TypeError, ValueError):
            pass

    st = result.detail.get("status") or {}
    data = st.get("data") or {}
    if data:
        result.days_left = data.get("daysLeft") or data.get("days_left") or data.get("remaining_days")
        vip = data.get("vip")
        if vip is not None:
            result.plan = str(vip)
        traffic = data.get("traffic")
        if traffic is not None:
            result.traffic_used = human_gb(float(traffic))

    pts = result.detail.get("points") or {}
    if pts.get("points") is not None:
        try:
            result.points = float(pts["points"])
        except (TypeError, ValueError):
            pass
    if body.get("streak") is not None:
        result.streak = body["streak"]

    history = pts.get("history") or []
    if history and not result.repeated:
        today = time.strftime("%Y-%m-%d")
        for row in history:
            if row.get("business") == "system:checkin" and str(row.get("detail")) == today:
                try:
                    result.gained = float(row.get("change"))
                except (TypeError, ValueError):
                    pass
                break

    log(
        f"账号 #{index} 结果: code={code} reason={result.reason or '-'} "
        f"points={result.points} message={result.message[:60]!r}"
    )
    return result


# ---------------------------------------------------------------- push

BADGE = {
    "ok": ("#0f9d58", "#e8f5ee", "签到成功"),
    "rep": ("#1a73e8", "#e8f0fe", "今日已签"),
    "fail": ("#d93025", "#fce8e6", "签到失败"),
}


def num(value: Optional[float], dash: str = "—") -> str:
    """19.0 -> 19，19.5 -> 19.5。"""
    if value is None:
        return dash
    try:
        v = float(value)
    except (TypeError, ValueError):
        return dash
    return f"{v:g}"


def render_push_html(results: List[AccountResult], headless: bool) -> str:
    """手机优先的推送卡片。

    PushPlus 在微信内置浏览器里渲染，可视宽度约 330~380px，
    所以不用 <table>，改用可换行的 flex 块，任何宽度都不会挤变形。
    """
    ok_count = sum(1 for r in results if r.ok and not r.repeated)
    rep_count = sum(1 for r in results if r.repeated)
    fail_count = sum(1 for r in results if not r.ok)
    total_gain = num(sum(r.gained or 0 for r in results))

    accent = "#0f9d58" if fail_count == 0 else "#d93025"
    headline = "GLaDOS 每日签到" if fail_count == 0 else "GLaDOS 签到异常"

    cards = []
    for i, r in enumerate(results, 1):
        key = "fail" if not r.ok else ("rep" if r.repeated else "ok")
        color, bg, text = BADGE[key]
        gained = f"+{num(r.gained)}" if r.gained not in (None, 0) else "—"
        ip = r.ip if r.ip and r.ip != "-" else "—"
        msg = (r.message or ("今天已有签到记录" if r.repeated else "—")).replace("<", "&lt;")
        if len(msg) > 90:
            msg = msg[:90] + "…"

        stats = [
            ("本次", gained, color if gained != "—" else "#999"),
            ("总积分", num(r.points), "#111"),
            ("连续", f"{num(r.streak)} 天" if r.streak is not None else "—", "#111"),
            ("剩余", f"{num(r.days_left)} 天" if r.days_left is not None else "—", "#111"),
        ]
        stat_html = "".join(
            f"""<div style="flex:1 0 44%;min-width:108px;padding:6px 0;">
      <div style="font-size:11px;color:#9a9a9a;line-height:1.4;">{label}</div>
      <div style="font-size:15px;font-weight:700;color:{color_};line-height:1.5;white-space:nowrap;">{value}</div>
    </div>"""
            for label, value, color_ in stats
        )

        cards.append(
            f"""<div style="border:1px solid #ececec;border-radius:10px;padding:12px 13px;margin:0 0 10px;background:#fff;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
    <div style="font-size:14px;font-weight:700;color:#111;white-space:nowrap;">账号 #{i}</div>
    <div style="display:inline-block;padding:3px 9px;border-radius:99px;background:{bg};color:{color};font-size:11px;font-weight:600;white-space:nowrap;">{text}</div>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:0 8px;margin-top:6px;">
    {stat_html}
  </div>
  <div style="margin-top:8px;padding-top:8px;border-top:1px dashed #eee;font-size:11px;color:#9a9a9a;line-height:1.6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">出口 IP · {ip}</div>
  <div style="margin-top:2px;font-size:11px;color:#8a8a8a;line-height:1.6;word-break:break-word;">{msg}</div>
</div>"""
        )

    return f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Helvetica Neue',Arial,sans-serif;max-width:720px;margin:0 auto;background:#f6f7f9;border-radius:12px;overflow:hidden;">
  <div style="padding:16px 14px;background:linear-gradient(135deg,{accent} 0%,#141414 175%);color:#fff;">
    <div style="font-size:17px;font-weight:700;letter-spacing:.2px;">{headline}</div>
    <div style="margin-top:5px;font-size:12px;opacity:.93;line-height:1.6;">
      {time.strftime('%m-%d %H:%M')} · 成功 {ok_count} · 已签 {rep_count} · 失败 {fail_count}
    </div>
  </div>

  <div style="padding:12px 14px 4px;">
    <div style="display:flex;flex-wrap:wrap;gap:10px;background:#fff;border:1px solid #ececec;border-radius:10px;padding:12px 13px;">
      <div style="flex:1 0 30%;min-width:78px;">
        <div style="font-size:11px;color:#9a9a9a;line-height:1.4;">本次收益</div>
        <div style="font-size:19px;font-weight:700;color:{accent};line-height:1.5;white-space:nowrap;">+{total_gain}</div>
      </div>
      <div style="flex:1 0 30%;min-width:78px;">
        <div style="font-size:11px;color:#9a9a9a;line-height:1.4;">账号数</div>
        <div style="font-size:19px;font-weight:700;color:#111;line-height:1.5;">{len(results)}</div>
      </div>
      <div style="flex:1 0 30%;min-width:78px;">
        <div style="font-size:11px;color:#9a9a9a;line-height:1.4;">运行模式</div>
        <div style="font-size:19px;font-weight:700;color:#111;line-height:1.5;">{'Headless' if headless else 'Headful'}</div>
      </div>
    </div>
  </div>

  <div style="padding:10px 14px 2px;">
    {''.join(cards)}
  </div>

  <div style="padding:0 14px 14px;font-size:11px;color:#a5a5a5;line-height:1.7;">
    Turnstile 由真实 Chromium 现场通过 · action=checkin · cData=nonce<br>
    proof = sha256(nonce + ".glados-observe-v1")
  </div>
</div>"""


def push_pushplus(token: str, results: List[AccountResult], headless: bool, log) -> None:
    import requests

    fail = sum(1 for r in results if not r.ok)
    total = num(sum(r.gained or 0 for r in results))
    title = f"GLaDOS 签到{'成功' if fail == 0 else f'异常({fail})'} · +{total}分"
    payload = {
        "token": token,
        "title": title,
        "content": render_push_html(results, headless),
        "template": "html",
    }
    try:
        resp = requests.post("https://www.pushplus.plus/send", json=payload, timeout=30)
        data = resp.json()
        if data.get("code") == 200:
            log(f"PushPlus 推送成功: {title}")
        else:
            log(f"PushPlus 推送失败: {data}")
    except Exception as exc:
        log(f"PushPlus 推送异常: {exc}")


# ---------------------------------------------------------------- main

def main() -> int:
    # Turnstile 在 headless 下拿不到 token（tsState=error），默认必须 headful。
    # CI 用虚拟显示（Windows runner 自带桌面会话，Linux 用 xvfb-run）。
    headless = os.environ.get("GLADOS_HEADLESS", "0").lower() in ("1", "true", "yes")
    raw_cookies = os.environ.get("GLADOS_COOKIES", "").strip()
    push_token = os.environ.get("PUSHPLUS_TOKEN", "").strip()

    def log(msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    if not raw_cookies:
        log("缺少 GLADOS_COOKIES")
        return 1

    cookies = [c.strip() for c in raw_cookies.split("&") if c.strip()]
    log(f"共 {len(cookies)} 个账号 · headless={headless} · 站点={CONSOLE_URL}")

    results: List[AccountResult] = []
    for i, cookie in enumerate(cookies, 1):
        try:
            results.append(run_account(i, cookie, headless, log))
        except Exception as exc:
            log(f"账号 #{i} 异常: {str(exc)[:160]}")
            results.append(AccountResult(ok=False, message=str(exc)[:200], reason="exception"))

    ok = sum(1 for r in results if r.ok and not r.repeated)
    rep = sum(1 for r in results if r.repeated)
    bad = sum(1 for r in results if not r.ok)
    gained = num(sum(r.gained or 0 for r in results))
    log(f"汇总: 成功 {ok} · 已签 {rep} · 失败 {bad} · 本次 +{gained} 分")

    if push_token:
        push_pushplus(push_token, results, headless, log)
    else:
        log("未配置 PUSHPLUS_TOKEN，跳过推送")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())