"""纯 HTTP 引擎：Turnstile 求解服务 + 直接调用 glados API。

适用场景：GitHub Actions 这类无桌面/无 GPU 环境，浏览器拿不到 Turnstile token。
流程与前端完全一致，只是 token 由求解服务代为取得：

  1. GET  /api/user/checkin/challenge            -> nonce / sitekey / ip
  2. 求解服务：sitekey + pageurl + action=checkin + cdata=nonce -> token
  3. proof = sha256(nonce + ".glados-observe-v1")
  4. POST /api/user/checkin {token, nonce, proof, tsState:"ok", turnstile:token}
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional, Tuple

import requests

PROOF_KEY = "glados-observe-v1"
SITE = "https://glados.space"
PAGE_URL = "https://glados.space/console/checkin"
CHALLENGE = "/api/user/checkin/challenge"
CHECKIN = "/api/user/checkin"
ACTION = "checkin"

# 与登录设备对齐的 UA / Client Hints 组合
UA_PROFILES: Dict[str, Dict[str, str]] = {
    "windows": {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"15.0.0"',
        "sec-ch-ua-arch": '"x86"',
        "sec-ch-ua-bitness": '"64"',
    },
    "android": {
        "User-Agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"),
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua-platform-version": '"14.0.0"',
    },
    "ios": {
        "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                       "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
    },
    "mac": {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    },
    "linux": {
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
    },
}

DEVICE_TO_FAMILY = {
    "Windows": "windows",
    "Android": "android",
    "iOS": "ios",
    "Mac": "mac",
    "macOS": "mac",
    "Linux": "linux",
}


def proof_of(nonce: str) -> str:
    return hashlib.sha256(f"{nonce}.{PROOF_KEY}".encode()).hexdigest()


def _base_headers(profile: Dict[str, str]) -> Dict[str, str]:
    h = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": SITE,
        "Referer": PAGE_URL,
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }
    h.update(profile)
    return h


# ---------------------------------------------------------------- 求解服务

CAPSOLVER_CREATE = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT = "https://api.capsolver.com/getTaskResult"
YESCAPTCHA_CREATE = "https://api.yescaptcha.com/createTask"
YESCAPTCHA_RESULT = "https://api.yescaptcha.com/getTaskResult"
TWOCAPTCHA_IN = "https://2captcha.com/in.php"
TWOCAPTCHA_RES = "https://2captcha.com/res.php"


def solve_capsolver(key: str, sitekey: str, pageurl: str, action: str, cdata: str, log) -> Optional[str]:
    create = requests.post(
        CAPSOLVER_CREATE,
        json={
            "clientKey": key,
            "task": {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": pageurl,
                "websiteKey": sitekey,
                "metadata": {"action": action, "cdata": cdata},
            },
        },
        timeout=30,
    ).json()
    if create.get("errorId"):
        log(f"  capsolver createTask 失败: {create}")
        return None
    tid = create.get("taskId")
    for _ in range(40):
        time.sleep(3)
        r = requests.post(
            CAPSOLVER_RESULT,
            json={"clientKey": key, "taskId": tid},
            timeout=30,
        ).json()
        st = r.get("status")
        if st == "ready":
            return (r.get("solution") or {}).get("token")
        if r.get("errorId"):
            log(f"  capsolver getTaskResult 失败: {r}")
            return None
    return None


def solve_2captcha(key: str, sitekey: str, pageurl: str, action: str, cdata: str, log) -> Optional[str]:
    r = requests.post(
        TWOCAPTCHA_IN,
        data={
            "method": "turnstile",
            "key": key,
            "sitekey": sitekey,
            "pageurl": pageurl,
            "action": action,
            "data": cdata,
            "json": 1,
        },
        timeout=30,
    ).json()
    if r.get("status") != 1:
        log(f"  2captcha in.php 失败: {r}")
        return None
    rid = r.get("request")
    for _ in range(40):
        time.sleep(5)
        g = requests.get(
            TWOCAPTCHA_RES,
            params={"key": key, "action": "get", "id": rid, "json": 1},
            timeout=30,
        ).json()
        if g.get("status") == 1:
            return g.get("request")
        if g.get("request") not in ("CAPCHA_NOT_READY",):
            log(f"  2captcha res.php 失败: {g}")
            return None
    return None


def solve_yescaptcha(key: str, sitekey: str, pageurl: str, action: str, cdata: str, log) -> Optional[str]:
    create = requests.post(
        YESCAPTCHA_CREATE,
        json={
            "clientKey": key,
            "task": {
                "type": "TurnstileTaskProxyless",
                "websiteUrl": pageurl,
                "websiteKey": sitekey,
                "action": action,
                "cdata": cdata,
            },
        },
        timeout=30,
    ).json()
    if create.get("errorId"):
        log(f"  yescaptcha createTask 失败: {create}")
        return None
    tid = create.get("taskId")
    for _ in range(40):
        time.sleep(3)
        r = requests.post(
            YESCAPTCHA_RESULT,
            json={"clientKey": key, "taskId": tid},
            timeout=30,
        ).json()
        if r.get("status") == "ready":
            sol = r.get("solution") or {}
            return sol.get("token") or sol.get("gRecaptchaResponse")
        if r.get("errorId"):
            log(f"  yescaptcha getTaskResult 失败: {r}")
            return None
    return None


SOLVERS = {
    "capsolver": solve_capsolver,
    "2captcha": solve_2captcha,
    "yescaptcha": solve_yescaptcha,
}


# ---------------------------------------------------------------- 主流程

def run_account(index: int, cookie_raw: str, provider: str, api_key: str, log) -> Dict[str, Any]:
    """返回与浏览器引擎一致的字典结构，便于统一渲染/推送。"""
    log(f"开始处理账号 #{index}（api 引擎 / {provider}）")

    cookie_dict = {}
    for part in cookie_raw.split(";"):
        if "=" in part:
            k, _, v = part.strip().partition("=")
            cookie_dict[k] = v

    info: Dict[str, Any] = {"attempts": [], "checkin": {}, "points": {}, "status": {}, "ip": ""}

    family_order = ["windows", "android", "ios", "mac", "linux"]
    body: Dict[str, Any] = {}
    queue = list(family_order)
    tried: set = set()

    while queue:
        family = queue.pop(0)
        if family in tried:
            continue
        tried.add(family)
        profile = UA_PROFILES[family]
        log(f"  使用 UA 配置文件: {family}")
        s = requests.Session()
        s.cookies.update(cookie_dict)
        s.headers.update(_base_headers(profile))

        try:
            ch = s.get(SITE + CHALLENGE, timeout=30).json()
        except Exception as exc:
            log(f"  challenge 请求异常: {exc}")
            break

        nonce = ch.get("nonce")
        sitekey = ch.get("turnstile")
        if not nonce or not sitekey:
            log(f"  challenge 返回异常: {ch}")
            body = {"code": -1, "message": f"challenge 异常: {ch}"}
            break

        info["ip"] = ch.get("ip") or info["ip"]

        # 前端会等 nonce 生成后 >= 2500ms 再提交
        time.sleep(2.6)

        solver = SOLVERS[provider]
        token = solver(api_key, sitekey, PAGE_URL, ACTION, nonce, log)
        if not token:
            log("  求解服务未返回 token，换下一个 UA 继续重试")
            continue

        payload = {
            "token": "glados.space",
            "nonce": nonce,
            "proof": proof_of(nonce),
            "tsState": "ok",
            "turnstile": token,
        }
        try:
            body = s.post(SITE + CHECKIN, json=payload, timeout=45).json()
        except Exception as exc:
            log(f"  checkin 请求异常: {exc}")
            continue

        code = body.get("code")
        log(f"  返回 code={code} reason={body.get('reason')} repeated={body.get('repeated')} "
            f"login={body.get('loginDevice')} cur={body.get('currentDevice')}")
        info["attempts"].append({"family": family, "code": code, "reason": body.get("reason")})

        if code in (0, 1) or body.get("repeated"):
            info["checkin"] = body
            info["mismatch"] = None
            try:
                info["status"] = s.get(SITE + "/api/user/status", timeout=30).json()
                info["points"] = s.get(SITE + "/api/user/points", timeout=30).json()
            except Exception:
                pass
            return info

        # device-mismatch：按服务器回报的登录设备，优先换对应 UA
        if code == 4 and body.get("reason") == "device-mismatch":
            info["mismatch"] = {
                "loginDevice": body.get("loginDevice"),
                "currentDevice": body.get("currentDevice"),
            }
            want = DEVICE_TO_FAMILY.get(str(body.get("loginDevice")))
            log(f"  设备不匹配（登录={body.get('loginDevice')} 当前={body.get('currentDevice')}），"
                f"改用 {want or '未知'} UA 重试")
            if want and want not in tried:
                queue.insert(0, want)
            continue

        # code=5 说明设备已匹配，只是 token 不被接受：继续换 UA 没有意义
        if code == 5 and body.get("reason") == "turnstile":
            log("  Turnstile token 未被接受（设备已匹配）。多为求解服务 token 与本站 IP/参数不匹配，"
                "请检查求解服务线路或换 provider")
            break

    info["checkin"] = body
    return info
