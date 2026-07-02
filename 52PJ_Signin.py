"""
File: main.py (吾爱破解签到)
Author: HoongDou & Modified from Mrzqd Version
Date: 2026/06/29
cron: 30 7 * * *
new Env('吾爱破解签到');

支持两种模式：
1. 浏览器模式（主要）：使用 undetected-chromedriver 绕过 WAF
2. API 模式（备用）：使用外部 API 处理加密验证

环境变量：
  PJ52_COOKIE         必填，多账号用 & 分隔
  PJ52_TOKEN          选填，API 模式需要
  PJ52_MODE           选填，browser 或 api，默认 browser
  PJ52_AUTO_FALLBACK  选填，1 开启自动降级（默认），0 关闭
  PJ52_TEST_MODE      选填，设置为 1 启用测试模式
  PJ52_DEBUG          选填，设置为 1 启用详细调试日志
"""

import os
import re
import sys
import json
import time
import random
import shutil
from datetime import datetime
from typing import Dict, Tuple, Optional, List, Any
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

# 浏览器相关导入
try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

try:
    from pyvirtualdisplay import Display
    HAS_XVFB = True
except ImportError:
    HAS_XVFB = False

# 通知模块
try:
    from notify import send as ql_send
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False


# --- 配置与常量 ---
URL_BASE = "https://www.52pojie.cn/"
URL_HOME = URL_BASE
URL_INDEX = URL_BASE + "forum.php"
URL_TASK_APPLY = URL_BASE + "home.php?mod=task&do=apply&id=2"
URL_TASK_DRAW = URL_BASE + "home.php?mod=task&do=draw&id=2"
URL_WAF_VERIFY = URL_BASE + "waf_zw_verify"
URL_EXTERNAL_API = "https://52pojie-sign-sever.zzboy.tk/api/52pojie"

COMMON_HEADERS = {
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    'Accept-Language': "zh-CN,zh;q=0.9,en;q=0.8",
    'Accept-Encoding': "gzip, deflate, br",
    'Connection': "keep-alive",
    'Upgrade-Insecure-Requests': "1",
}

REQUEST_TIMEOUT = 30
SLEEP_TIME_RANGE = [60, 180]  # 账号间延迟范围（秒）
TEST_SLEEP_RANGE = [1, 5]     # 测试模式延迟范围

# 全局调试开关
DEBUG_MODE = False


# --- 日志与通知 ---
def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def debug_log(msg: str):
    """调试日志，只在 DEBUG_MODE 开启时输出"""
    if DEBUG_MODE:
        log(f"🔍 [DEBUG] {msg}")


def send_notify(title: str, content: str):
    if HAS_NOTIFY:
        try:
            ql_send(title, content)
        except Exception as e:
            log(f"通知发送失败: {e}")
    else:
        log(f"[通知] {title}\n{content}")


# --- Cookie 解析（增强版）---
def parse_cookie_str(cookie_str: str) -> Tuple[Optional[Dict[str, str]], Optional[List[Dict]], str]:
    """
    解析 Cookie 字符串，支持 URL 解码
    返回：(requests用的dict, selenium用的list, 错误信息)
    """
    if not cookie_str:
        return None, None, "Cookie字符串为空"

    cookies_dict = {}
    cookies_list = []
    required_keys = {"htVC_2132_saltkey", "htVC_2132_auth"}
    found_keys = set()

    debug_log(f"原始 Cookie 长度: {len(cookie_str)} 字符")
    debug_log(f"Cookie 片段: {cookie_str[:100]}...")

    for item in cookie_str.split(';'):
        parts = item.split('=', 1)
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip()
            
            # 不对 value 进行解码，保持原样
            # 因为 requests 和 selenium 会自动处理
            
            # requests 格式
            cookies_dict[key] = value
            
            # selenium 格式
            cookies_list.append({
                'name': key,
                'value': value,
                'domain': '.52pojie.cn',
                'path': '/',
            })
            
            if key in required_keys:
                found_keys.add(key)
                debug_log(f"找到必需字段: {key} = {value[:20]}...")

    debug_log(f"解析出 {len(cookies_dict)} 个 Cookie 字段")
    debug_log(f"必需字段状态: {found_keys}")

    if not required_keys.issubset(found_keys):
        missing = ", ".join(list(required_keys - found_keys))
        return None, None, f"Cookie中缺失必需字段: {missing}"
    
    return cookies_dict, cookies_list, ""


# --- 统一检测函数（增强版）---
def check_login_status(html: str) -> Tuple[bool, str]:
    """
    检查是否登录成功
    返回：(是否登录, 错误信息)
    """
    if not html:
        return False, "页面为空"
    
    debug_log(f"检查登录状态，HTML 长度: {len(html)} 字符")
    
    soup = BeautifulSoup(html, "html.parser")
    
    # 检查 WAF 拦截
    if "wzws-waf" in html.lower() or "访问验证" in html or "请开启JavaScript" in html:
        debug_log("检测到 WAF 拦截页面")
        return False, "被 WAF 拦截，请稍后重试"
    
    # 检查验证码
    if "验证码" in html or "captcha" in html.lower():
        debug_log("检测到验证码页面")
        return False, "需要验证码验证"
    
    # 检查是否需要登录（登录按钮）
    login_button = soup.find('button', class_="pn vm")
    if login_button:
        debug_log("检测到登录按钮")
        return False, "Cookie失效 (需要登录)"
    
    # 检查登录标志（多种方式）
    login_indicators = {
        "退出链接": "退出" in html or "logout" in html.lower(),
        "个人资料": "个人资料" in html or "home.php?mod=space" in html,
        "我的帖子": "我的帖子" in html,
        "用户组": "用户组" in html,
        "用户名显示": 'class="vwmy"' in html or 'id="myspace"' in html,
    }
    
    debug_log(f"登录指标: {login_indicators}")
    
    logged_in = any(login_indicators.values())
    
    if not logged_in:
        # 保存页面片段用于调试
        debug_log(f"未检测到登录标志，页面开头:\n{html[:500]}")
        return False, "Cookie已失效，请手动更新"
    
    debug_log("✓ 已登录")
    return True, "登录成功"


def check_already_signed_status(html: str) -> Tuple[bool, str]:
    """
    统一检查是否已签到（适用于两种模式）
    返回：(是否已签到, 消息)
    """
    if not html:
        return False, ""
    
    soup = BeautifulSoup(html, "html.parser")
    
    # 方法1: 检查图片状态（最可靠）
    sign_images = soup.find_all('img', class_="qq_bind")
    for img_node in sign_images:
        src = img_node.get("src", "")
        debug_log(f"签到图片 src: {src}")
        if src.endswith("wbs.png"):  # 已签到图标
            return True, "今日已签到 (图片状态wbs.png)"
        elif src.endswith("qds.png"):  # 未签到图标
            return False, ""
    
    # 方法2: 检查导航栏签到链接文本
    pattern = r'<a[^>]*href=["\']home\.php\?mod=task&do=apply&id=2["\'][^>]*>([^<]+)</a>'
    match = re.search(pattern, html)
    
    if match:
        text = match.group(1).strip()
        debug_log(f"签到链接文本: {text}")
        if "签到已得" in text or "已签" in text:
            days_match = re.search(r'(\d+)', text)
            if days_match:
                return True, f"今日已签到 (已签 {days_match.group(1)} 天)"
            return True, f"今日已签到 ({text})"
    
    # 方法3: 检查页面内容
    if any(k in html for k in ["您今天已经签到", "今天已经签到过", "您今天已经申请过"]):
        return True, "今日已签到"
    
    return False, ""


def parse_signin_result(html: str) -> Tuple[bool, str]:
    """
    统一解析签到结果（适用于两种模式）
    返回：(是否成功, 消息)
    """
    if not html:
        return False, "页面为空"
    
    debug_log(f"解析签到结果，HTML 长度: {len(html)} 字符")
    
    soup = BeautifulSoup(html, "html.parser")
    
    # 检查消息区域
    message_div = soup.find("div", id="messagetext")
    
    if message_div:
        message_p = message_div.find("p")
        if message_p:
            result_text = message_p.text.strip()
            debug_log(f"消息文本: {result_text}")
            
            # 需要登录
            if "您需要先登录" in result_text:
                return False, "Cookie失效"
            
            # 签到成功
            if "恭喜" in result_text:
                # 尝试提取CB数量
                cb_match = re.search(r'(\d+)\s*个?CB', result_text)
                if cb_match:
                    return True, f"签到成功，获得 {cb_match.group(1)} CB"
                return True, "签到成功"
            
            # 已签到
            if "不是进行中的任务" in result_text or "已完成" in result_text or "已经申请过" in result_text:
                return True, "今日已签到"
            
            # 其他错误
            if "失败" in result_text or "错误" in result_text:
                return False, f"签到失败: {result_text}"
            
            return False, f"未知结果: {result_text}"
    
    # 没有消息区域，检查页面内容
    # 已签到
    if any(k in html for k in ["您今天已经签到", "已经签到过", "您今天已经申请过"]):
        return True, "今日已签到"
    
    # 签到成功 - 多种格式
    cb_match = re.search(r'获得了?\s*(\d+)\s*个?CB', html)
    if cb_match:
        return True, f"签到成功，获得 {cb_match.group(1)} CB"
    
    cb_match2 = re.search(r'积分[^>]*吾爱币\s*(\d+)\s*CB', html)
    if cb_match2:
        return True, f"签到成功，获得 {cb_match2.group(1)} CB"
    
    if "恭喜" in html or "成功" in html:
        return True, "签到成功"
    
    # 失败
    if "失败" in html or "错误" in html:
        debug_log(f"检测到失败关键词，页面片段:\n{html[:800]}")
        return False, "签到失败"
    
    # 无法判断
    debug_log(f"无法判断签到结果，页面片段:\n{html[:800]}")
    return False, "未识别到签到结果"


# --- 浏览器辅助函数 ---
def find_chrome_binary():
    """查找 Chrome 浏览器"""
    paths = [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        '/snap/bin/chromium',
        shutil.which('google-chrome'),
        shutil.which('google-chrome-stable'),
        shutil.which('chromium'),
        shutil.which('chromium-browser'),
    ]
    
    for path in paths:
        if path and os.path.exists(path):
            debug_log(f"找到 Chrome: {path}")
            return path
    return None


def find_chromedriver():
    """查找 ChromeDriver"""
    paths = [
        '/usr/local/bin/chromedriver-149',
        '/usr/local/bin/chromedriver',
        '/usr/bin/chromedriver',
        shutil.which('chromedriver'),
    ]
    
    for path in paths:
        if path and os.path.exists(path):
            debug_log(f"找到 ChromeDriver: {path}")
            return path
    return None


def check_waf_challenge(html: str) -> bool:
    """检查是否遇到 WAF"""
    if not html:
        return True
    
    waf_keywords = [
        "请开启JavaScript并刷新该页",
        "wzws-waf-cgi",
        "请开启JavaScript",
        "<noscript>",
    ]
    
    is_waf = any(keyword in html for keyword in waf_keywords)
    if is_waf:
        debug_log("检测到 WAF 挑战页面")
    return is_waf


def wait_for_page_load(driver, max_wait=60):
    """等待页面加载完成"""
    start_time = time.time()
    last_check = ""
    stable_count = 0
    
    debug_log(f"等待页面加载（最多 {max_wait} 秒）")
    
    while time.time() - start_time < max_wait:
        try:
            html = driver.page_source
            
            if not check_waf_challenge(html):
                if html == last_check:
                    stable_count += 1
                    if stable_count >= 2:
                        debug_log("页面加载稳定")
                        return True
                else:
                    stable_count = 0
                last_check = html
            else:
                debug_log("仍在 WAF 挑战中...")
            
            time.sleep(2)
        except Exception as e:
            debug_log(f"页面加载检查出错: {e}")
            pass
    
    debug_log("页面加载超时")
    return False


# --- 浏览器模式签到（增强版）---
def signin_browser(cookie_str: str) -> Tuple[bool, str]:
    """使用浏览器签到"""
    if not HAS_UC:
        return False, "未安装 undetected-chromedriver"
    
    display = None
    driver = None
    
    # 启动虚拟显示
    if HAS_XVFB:
        try:
            display = Display(visible=False, size=(1920, 1080))
            display.start()
            log("✅ 虚拟显示已启动")
        except Exception as e:
            log(f"⚠️ 虚拟显示启动失败: {e}")
            debug_log(f"虚拟显示错误详情: {e}")
    
    try:
        chrome_path = find_chrome_binary()
        chromedriver_path = find_chromedriver()
        
        if not chrome_path:
            return False, "未找到 Chrome 浏览器"
        if not chromedriver_path:
            return False, "未找到 ChromeDriver"
        
        log(f"使用 Chrome: {chrome_path}")
        log(f"使用 ChromeDriver: {chromedriver_path}")
        
        # 配置选项
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-web-security')
        options.add_argument('--disable-features=IsolateOrigins,site-per-process')
        
        if DEBUG_MODE:
            options.add_argument('--enable-logging')
            options.add_argument('--v=1')
        
        # 启动浏览器
        log("启动浏览器...")
        driver = uc.Chrome(
            options=options,
            driver_executable_path=chromedriver_path,
            browser_executable_path=chrome_path,
            use_subprocess=False,
            version_main=None  # 自动检测版本
        )
        log("✅ 浏览器已启动")
        
        # Step 1: 访问首页
        log(f"\n[1/6] 访问首页 {URL_HOME}")
        driver.get(URL_HOME)
        if not wait_for_page_load(driver, max_wait=60):
            return False, "首页加载超时"
        time.sleep(random.uniform(2, 3))
        
        debug_log(f"首页 URL: {driver.current_url}")
        debug_log(f"首页标题: {driver.title}")
        
        # Step 2: 注入 Cookie
        log("[2/6] 注入 Cookie")
        _, cookies_list, error = parse_cookie_str(cookie_str)
        if error:
            return False, error
        
        injected_count = 0
        failed_cookies = []
        for cookie in cookies_list:
            try:
                driver.add_cookie(cookie)
                injected_count += 1
                debug_log(f"注入 Cookie: {cookie['name']}")
            except Exception as e:
                failed_cookies.append(cookie['name'])
                debug_log(f"Cookie 注入失败: {cookie['name']}, 错误: {e}")
        
        log(f"✅ 成功注入 {injected_count}/{len(cookies_list)} 个 Cookie")
        if failed_cookies:
            log(f"⚠️ 失败的 Cookie: {', '.join(failed_cookies)}")
        
        # Step 3: 刷新页面并检查登录状态
        log("[3/6] 刷新页面并验证登录")
        driver.refresh()
        if not wait_for_page_load(driver, max_wait=60):
            return False, "刷新后页面加载超时"
        time.sleep(random.uniform(2, 3))
        
        debug_log(f"刷新后 URL: {driver.current_url}")
        
        html = driver.page_source
        logged_in, login_msg = check_login_status(html)
        
        if not logged_in:
            # 保存页面用于调试
            if DEBUG_MODE:
                try:
                    with open("/tmp/52pojie_login_failed.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    debug_log("已保存失败页面到 /tmp/52pojie_login_failed.html")
                except:
                    pass
            return False, login_msg
        
        log(f"✅ {login_msg}")
        
        # Step 4: 检查是否已签到
        log("[4/6] 检查签到状态")
        already, msg = check_already_signed_status(html)
        if already:
            log(f"✅ {msg}")
            return True, msg
        
        log("未签到，继续执行签到流程")
        
        # Step 5: 申请签到任务
        log(f"[5/6] 申请签到任务 {URL_TASK_APPLY}")
        driver.get(URL_TASK_APPLY)
        if not wait_for_page_load(driver, max_wait=60):
            return False, "签到任务页加载超时"
        time.sleep(random.uniform(2, 3))
        
        debug_log(f"任务页 URL: {driver.current_url}")
        
        # Step 6: 领取签到奖励
        log(f"[6/6] 领取签到奖励 {URL_TASK_DRAW}")
        driver.get(URL_TASK_DRAW)
        if not wait_for_page_load(driver, max_wait=60):
            return False, "奖励页加载超时"
        time.sleep(random.uniform(2, 3))
        
        debug_log(f"奖励页 URL: {driver.current_url}")
        
        html = driver.page_source
        success, message = parse_signin_result(html)
        
        # 保存结果页面用于调试
        if DEBUG_MODE:
            try:
                filename = f"/tmp/52pojie_result_{'success' if success else 'failed'}.html"
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(html)
                debug_log(f"已保存结果页面到 {filename}")
            except:
                pass
        
        log(f"{'✅' if success else '❌'} {message}")
        return success, message
        
    except Exception as e:
        log(f"❌ 浏览器签到异常: {e}")
        import traceback
        error_trace = traceback.format_exc()
        debug_log(f"完整错误堆栈:\n{error_trace}")
        return False, f"签到出错: {str(e)}"
    
    finally:
        if driver:
            try:
                driver.quit()
                log("✅ 浏览器已关闭")
            except:
                pass
        if display:
            try:
                display.stop()
            except:
                pass


# --- API 模式签到（增强版）---
def signin_api(cookie_str: str, token: str) -> Tuple[bool, str]:
    """使用 API 签到"""
    session = requests.Session()
    
    try:
        cookies_dict, _, error = parse_cookie_str(cookie_str)
        if error:
            return False, error
        
        debug_log(f"Cookie 字段数: {len(cookies_dict)}")
        
        # Step 1: 检查登录状态
        log("检查登录状态...")
        debug_log(f"请求 URL: {URL_HOME}")
        
        response = session.get(
            URL_HOME, 
            headers=COMMON_HEADERS, 
            cookies=cookies_dict, 
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        response.raise_for_status()
        
        debug_log(f"响应状态码: {response.status_code}")
        debug_log(f"响应 URL: {response.url}")
        debug_log(f"响应头: {dict(response.headers)}")
        debug_log(f"响应长度: {len(response.text)} 字符")
        
        logged_in, login_msg = check_login_status(response.text)
        if not logged_in:
            # 保存失败页面
            if DEBUG_MODE:
                try:
                    with open("/tmp/52pojie_api_login_failed.html", "w", encoding="utf-8") as f:
                        f.write(response.text)
                    debug_log("已保存失败页面到 /tmp/52pojie_api_login_failed.html")
                except:
                    pass
            return False, login_msg
        
        log(f"✅ {login_msg}")
        
        # Step 2: 检查是否已签到
        log("检查签到状态...")
        already, msg = check_already_signed_status(response.text)
        if already:
            log(f"✅ {msg}")
            return True, msg
        
        log("未签到，继续执行签到流程")
        
        # Step 3: 获取签到参数
        log("获取签到参数...")
        task_response = session.get(
            URL_TASK_APPLY + "&referer=%2F", 
            headers=COMMON_HEADERS, 
            cookies=cookies_dict, 
            timeout=REQUEST_TIMEOUT
        )
        task_response.raise_for_status()
        task_text = task_response.text
        
        debug_log(f"任务页响应长度: {len(task_text)} 字符")
        
        match_lz_lj = re.search(r"renversement\('(\d{4,})'\).*renversement\('(\d{4,})'\)", task_text, re.S)
        if not match_lz_lj:
            match_lz_lj = re.search(r".*='([0-9]{4,})'.*='([0-9]{4,})'.*", task_text, re.S)
        
        if not match_lz_lj:
            debug_log("未找到 lz/lj 参数，页面片段:")
            debug_log(task_text[:1000])
            return False, "未查询到签到参数 (lz, lj)"
        
        lz, lj = match_lz_lj.group(1), match_lz_lj.group(2)
        
        match_le = re.search(r".*='([a-zA-Z0-9/+]{40,})'.*", task_text, re.S)
        if not match_le:
            debug_log("未找到 le 参数")
            return False, "未查询到签到参数 (le)"
        
        le = match_le.group(1)
        log(f"✅ 获取到签到参数: lz={lz}, lj={lj}")
        debug_log(f"le 参数: {le[:50]}...")
        
        # Step 4: 调用外部 API
        log("调用外部签名API...")
        api_payload = {"lz": lz, "lj": lj, "le": le, "token": token}
        debug_log(f"API 请求 URL: {URL_EXTERNAL_API}")
        debug_log(f"API 请求 payload: {api_payload}")
        
        api_response = requests.post(URL_EXTERNAL_API, json=api_payload, timeout=REQUEST_TIMEOUT)
        
        debug_log(f"API 响应状态码: {api_response.status_code}")
        
        if api_response.status_code != 200:
            try:
                error_msg = api_response.json().get('msg', api_response.text)
            except:
                error_msg = api_response.text
            debug_log(f"API 错误响应: {error_msg}")
            return False, f"外部API调用失败 ({api_response.status_code}): {error_msg}"
        
        waf_payload = api_response.text
        debug_log(f"API 返回数据长度: {len(waf_payload)} 字符")
        log("✅ API调用成功")
        
        # Step 5: 提交 WAF 验证
        log("提交WAF验证...")
        waf_response = session.post(
            URL_WAF_VERIFY, 
            headers=COMMON_HEADERS, 
            cookies=cookies_dict, 
            data=waf_payload, 
            timeout=REQUEST_TIMEOUT
        )
        waf_response.raise_for_status()
        debug_log(f"WAF 验证响应状态码: {waf_response.status_code}")
        log("✅ WAF验证已提交")
        
        # Step 6: 确认签到结果
        log("确认签到结果...")
        final_response = session.get(
            URL_TASK_APPLY, 
            headers=COMMON_HEADERS, 
            cookies=cookies_dict, 
            timeout=REQUEST_TIMEOUT
        )
        final_response.raise_for_status()
        
        debug_log(f"最终结果页长度: {len(final_response.text)} 字符")
        
        success, message = parse_signin_result(final_response.text)
        
        # 保存结果页面
        if DEBUG_MODE:
            try:
                filename = f"/tmp/52pojie_api_result_{'success' if success else 'failed'}.html"
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(final_response.text)
                debug_log(f"已保存结果页面到 {filename}")
            except:
                pass
        
        log(f"{'✅' if success else '❌'} {message}")
        return success, message
        
    except requests.exceptions.RequestException as e:
        debug_log(f"网络请求错误详情: {e}")
        return False, f"网络请求失败: {e}"
    except Exception as e:
        log(f"❌ API 签到异常: {e}")
        import traceback
        error_trace = traceback.format_exc()
        debug_log(f"完整错误堆栈:\n{error_trace}")
        return False, f"签到过程异常: {e}"


# --- 处理单个账号（带智能降级）---
def process_single_user(
    user_idx: int,
    cookie_str: str,
    primary_mode: str,
    token: Optional[str] = None,
    auto_fallback: bool = True
) -> Dict[str, Any]:
    """处理单个用户的签到，支持失败自动切换模式"""
    log(f"\n{'='*60}")
    log(f"开始处理第 {user_idx} 个账号")
    log(f"{'='*60}")
    
    if not cookie_str:
        msg = "Cookie信息缺失"
        log(f"❌ {msg}")
        return {"msg": msg, "status_code": "CONFIG_ERROR"}
    
    # === 第一次尝试：使用主模式 ===
    log(f"🔹 主模式: {primary_mode.upper()}")
    
    if primary_mode == "api":
        if not token:
            msg = "API模式需要 PJ52_TOKEN"
            log(f"❌ {msg}")
            # 如果没有 token，直接切换到浏览器模式
            if auto_fallback and HAS_UC:
                log("⚠️ 缺少 TOKEN，自动切换到浏览器模式")
                success, message = signin_browser(cookie_str)
            else:
                return {"msg": msg, "status_code": "CONFIG_ERROR"}
        else:
            success, message = signin_api(cookie_str, token)
    else:
        success, message = signin_browser(cookie_str)
    
    # === 判断是否需要切换模式 ===
    should_fallback = (
        auto_fallback and
        not success and
        "已签到" not in message  # 已签到不算失败
    )
    
    # 特殊判断：如果是 Cookie 失效，API 模式也帮不了
    if "Cookie" in message and "失效" in message:
        log("⚠️ Cookie 失效，两种模式都无法使用")
        should_fallback = False  # 不切换了，没意义
    
    if should_fallback:
        # 确定备用模式
        fallback_mode = "api" if primary_mode == "browser" else "browser"
        
        # 检查备用模式是否可用
        can_fallback = False
        if fallback_mode == "api" and token:
            can_fallback = True
        elif fallback_mode == "browser" and HAS_UC:
            can_fallback = True
        
        if can_fallback:
            log(f"\n⚠️ 主模式失败: {message}")
            log(f"🔄 自动切换到备用模式: {fallback_mode.upper()}")
            log("="*60)
            
            # 等待一小段时间避免请求过快
            time.sleep(random.uniform(3, 5))
            
            # === 第二次尝试：使用备用模式 ===
            if fallback_mode == "api":
                success_retry, message_retry = signin_api(cookie_str, token)
            else:
                success_retry, message_retry = signin_browser(cookie_str)
            
            # 更新结果
            if success_retry:
                success = True
                message = f"{message_retry} (备用模式成功)"
                log(f"✅ 备用模式成功: {message_retry}")
            else:
                # 两种模式都失败了
                message = f"主模式失败: {message} | 备用模式失败: {message_retry}"
                log(f"❌ 备用模式也失败了: {message_retry}")
        else:
            log(f"⚠️ 备用模式 {fallback_mode.upper()} 不可用（缺少依赖或TOKEN），跳过切换")
    
    # 判断状态码
    status_code = "SUCCESS" if success else "FAILURE"
    if "已签到" in message:
        status_code = "ALREADY_SIGNED"
    elif any(k in message for k in ["失效", "配置", "未安装", "未找到"]):
        status_code = "CONFIG_ERROR"
    
    log(f"\n{'='*60}")
    log(f"第 {user_idx} 个账号最终状态: {'✅' if success else '❌'} {message}")
    log(f"{'='*60}")
    
    return {"msg": message, "status_code": status_code}


# --- 主程序 ---
def main():
    global DEBUG_MODE
    
    log("="*60)
    log("吾爱破解自动签到脚本")
    log("="*60)
    
    # 读取环境变量
    cookies_env = os.environ.get("PJ52_COOKIE", "").strip()
    token = os.environ.get("PJ52_TOKEN", "").strip()
    mode = os.environ.get("PJ52_MODE", "browser").strip().lower()
    test_mode = os.environ.get("PJ52_TEST_MODE", "").strip() == "1"
    auto_fallback = os.environ.get("PJ52_AUTO_FALLBACK", "1").strip() == "1"  # 默认开启自动切换
    DEBUG_MODE = os.environ.get("PJ52_DEBUG", "").strip() == "1"  # 调试模式
    
    if not cookies_env:
        log("❌ 错误: 请设置环境变量 PJ52_COOKIE")
        send_notify("【吾爱破解签到】", "❌ 未设置环境变量 PJ52_COOKIE")
        sys.exit(1)
    
    # 分割多账号
    user_configs = [c.strip() for c in cookies_env.split("&") if c.strip()]
    
    log(f"\n检测到 {len(user_configs)} 个账号")
    log(f"签到模式: {mode.upper()}")
    log(f"自动降级: {'开启' if auto_fallback else '关闭'}")
    log(f"测试模式: {'是' if test_mode else '否'}")
    log(f"调试模式: {'是' if DEBUG_MODE else '否'}")
    
    # 检查依赖
    if mode == "browser" or auto_fallback:
        if not HAS_UC:
            log("⚠️ 警告: 未安装 undetected-chromedriver，浏览器模式不可用")
            if mode == "browser" and token:
                log("⚠️ 自动切换到 API 模式")
                mode = "api"
            elif mode == "browser":
                log("❌ 错误: 浏览器模式不可用且无 API Token")
                sys.exit(1)
    
    # 初次随机延迟
    if test_mode:
        delay = random.randint(1, 5)
    else:
        delay = random.randint(60, 1200)  # 1-20分钟
    
    minutes, seconds = divmod(delay, 60)
    log(f"\n⏰ 随机延迟 {minutes} 分 {seconds} 秒后开始执行...")
    time.sleep(delay)
    log("✅ 延迟结束\n")
    
    # 处理每个账号
    results = []
    for idx, cookie in enumerate(user_configs, 1):
        # 账号间延迟（第一个账号不延迟）
        if idx > 1:
            sleep_range = TEST_SLEEP_RANGE if test_mode else SLEEP_TIME_RANGE
            sleep_duration = random.randint(sleep_range[0], sleep_range[1])
            log(f"\n⏰ 等待 {sleep_duration} 秒后处理下一个账号...")
            time.sleep(sleep_duration)
        
        # 处理签到（带自动降级）
        result = process_single_user(idx, cookie, mode, token, auto_fallback)
        results.append(result)
        
        # 发送通知
        status_icon = "✅" if result["status_code"] in ["SUCCESS", "ALREADY_SIGNED"] else "❌"
        send_notify(
            f"【吾爱破解签到】账号 {idx}",
            f"{status_icon} {result['msg']}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    # 汇总统计
    success_count = sum(1 for r in results if r["status_code"] in ["SUCCESS", "ALREADY_SIGNED"])
    failure_count = len(results) - success_count
    
    log("\n" + "="*60)
    log(f"所有账号处理完毕: 成功 {success_count}/{len(results)}")
    if failure_count > 0:
        log(f"失败账号:")
        for idx, r in enumerate(results, 1):
            if r["status_code"] not in ["SUCCESS", "ALREADY_SIGNED"]:
                log(f"  账号 {idx}: {r['msg']}")
    log("="*60)


if __name__ == "__main__":
    main()

