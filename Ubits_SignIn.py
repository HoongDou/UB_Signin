"""
UBits 自动签到脚本
环境变量：
  UBITS_COOKIE  必填，登录 UBits.club 后从浏览器复制的完整 Cookie
  UBITS_UA      可选，User-Agent，建议与获取 Cookie 时的浏览器保持一致
  UBITS_PROXY   可选，代理地址，如 http://127.0.0.1:7890

cron: 0 8 * * *
"""

import os
import re
from datetime import datetime
from typing import Optional, Tuple

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False

try:
    from notify import send as ql_send
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

SIGNIN_URL = "https://ubits.club/attendance.php"
SITE_URL   = "https://ubits.club/"
TIMEOUT    = 60

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def send_notify(title: str, content: str):
    if HAS_NOTIFY:
        ql_send(title, content)
    else:
        log(f"[通知] {title}\n{content}")


def under_challenge(html: str) -> bool:
    return any(k in html for k in [
        "Just a moment",
        "Checking your browser",
        "cf-browser-verification",
        "Enable JavaScript and cookies to continue",
    ])


def build_headers(cookie: str, ua: str, referer: str = None) -> dict:
    return {
        "Cookie": cookie,
        "User-Agent": ua,
        "Referer": referer or SITE_URL,
        "Origin": SITE_URL.rstrip("/"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Sec-CH-UA": '"Chromium";v="147", "Google Chrome";v="147", "Not/A)Brand";v="24"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-CH-UA-Platform-Version": '"15.0.0"',
        "Sec-CH-UA-Arch": '"x86"',
        "Sec-CH-UA-Bitness": '"64"',
        "Sec-CH-UA-Full-Version": '"147.0.0.0"',
        "Sec-CH-UA-Full-Version-List": '"Chromium";v="147.0.0.0", "Google Chrome";v="147.0.0.0", "Not/A)Brand";v="24.0.0.0"',
        "Sec-CH-UA-Model": '""',
    }


def fetch(url: str, cookie: str, ua: str, proxies: Optional[dict]) -> Optional[object]:
    """发起 GET 请求，失败返回 None。"""
    kwargs = dict(
        headers=build_headers(cookie, ua),
        proxies=proxies,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    if HAS_CURL_CFFI:
        kwargs["impersonate"] = "chrome120"
    try:
        return cffi_requests.get(url, **kwargs)
    except Exception as e:
        log(f"请求 {url} 失败：{e}")
        return None


def is_cookie_invalid(final_url: str, html: str) -> bool:
    if "login.php" in final_url:
        return True
    invalid_keywords   = ["login.php", "takelogin.php", "登录", "登入", "用户名", "密码"]
    logged_in_keywords = ["logout.php", "userdetails.php", "attendance.php", "签到", "控制面板"]
    return any(k in html for k in invalid_keywords) and not any(k in html for k in logged_in_keywords)


def check_already_signed(index_html: str) -> Tuple[bool, str]:
    """
    检查首页导航栏里的签到链接文字。
    已签到时链接文字形如：[签到已得10, 补签卡: 0]
    未签到时链接文字形如：[签到]
    返回 (已签到, 消息)，解析失败返回 (False, "")。
    """
    # 匹配 <a href="attendance.php" ...>[签到已得10, 补签卡: 0]</a>
    m = re.search(
        r'<a\s[^>]*href=["\']attendance\.php["\'][^>]*>'
        r'\[签到已得\s*(\d+)\s*,\s*补签卡\s*:\s*(\d+)\s*\]'
        r'</a>',
        index_html, re.S
    )
    if m:
        coins, makeup = m.group(1), m.group(2)
        return True, f"今日已签到，已得 {coins} U币，补签卡: {makeup}"

    return False, ""


def parse_signin_result(html: str) -> Tuple[Optional[bool], str]:
    m = re.search(r"本次签到获得\s*<[^>]+>\s*(\d+)\s*</[^>]+>\s*个U币", html, re.S)
    if m:
        return True, f"签到成功，获得 {m.group(1)} U币"

    m = re.search(r"本次签到获得\s*(\d+)\s*个U币", html, re.S)
    if m:
        return True, f"签到成功，获得 {m.group(1)} U币"

    if re.search(r"<h2[^>]*>\s*签到成功\s*</h2>", html, re.S):
        return True, "签到成功"

    m = re.search(r"签到已得\s*(\d+)", html, re.S)
    if m:
        return True, f"今日已签到，已得 {m.group(1)} U币"

    if any(k in html for k in ["今天已签到", "今日已签到", "已经签到", "您今天已经签到过"]):
        return True, "今日已签到"

    for k in ["签到失败", "发生错误", "非法请求", "权限不足"]:
        if k in html:
            return False, f"签到失败，页面提示：{k}"

    return None, ""


def do_signin(cookie: str, ua: str, proxies: Optional[dict]) -> Tuple[bool, str]:
    # ── 第一步：检查首页，判断今日是否已签到 ──────────────────────────────
    log(f"预检首页 {SITE_URL}")
    index_res = fetch(SITE_URL, cookie, ua, proxies)

    if index_res is not None and index_res.status_code == 200:
        index_html = index_res.text or ""

        if under_challenge(index_html):
            return False, "签到失败，被 Cloudflare 拦截，请检查 Cookie 是否包含有效 cf_clearance"

        if is_cookie_invalid(str(index_res.url), index_html):
            return False, "签到失败，Cookie 可能已失效，请重新填写"

        already, msg = check_already_signed(index_html)
        if already:
            log(f"首页预检：{msg}，跳过签到请求")
            return True, msg
    else:
        log("首页预检失败，跳过预检直接尝试签到")

    # ── 第二步：请求签到页 ─────────────────────────────────────────────────
    log(f"请求 {SIGNIN_URL}")
    res = fetch(SIGNIN_URL, cookie, ua, proxies)

    if res is None:
        return False, "签到失败，请求异常"

    log(f"HTTP {res.status_code}，最终地址：{res.url}")
    html = res.text or ""

    if res.status_code == 403:
        if under_challenge(html):
            return False, "签到失败，被 Cloudflare challenge 拦截，cf_clearance 可能已过期，请重新从浏览器获取"
        return False, f"签到失败，403 非 CF challenge，响应片段：{html[:200]}"

    if res.status_code not in (200, 500):
        return False, f"签到失败，状态码：{res.status_code}"

    if under_challenge(html):
        return False, "签到失败，被 Cloudflare 拦截，cf_clearance 可能已过期"

    if is_cookie_invalid(str(res.url), html):
        return False, "签到失败，Cookie 可能已失效，请重新填写"

    success, message = parse_signin_result(html)
    if success is not None:
        return success, message

    return True, "签到完成，但未识别到具体返回文字"


def main():
    cookie = os.environ.get("UBITS_COOKIE", "").strip()
    ua     = os.environ.get("UBITS_UA", "").strip() or DEFAULT_UA
    proxy  = os.environ.get("UBITS_PROXY", "").strip()

    if not cookie:
        log("❌ 未设置环境变量 UBITS_COOKIE，退出")
        send_notify("【UBits 签到】", "❌ 未设置环境变量 UBITS_COOKIE")
        return

    proxies = {"http": proxy, "https": proxy} if proxy else None

    log("开始 UBits 签到")
    success, message = do_signin(cookie, ua, proxies)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status  = "✅ 成功" if success else "❌ 失败"
    log(f"{status}：{message}")

    send_notify(
        "【UBits 自动签到】",
        f"{status}\n结果：{message}\n时间：{now_str}",
    )


if __name__ == "__main__":
    main()
