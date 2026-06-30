"""
52破解论坛自动签到脚本（浏览器 + Cookie 注入版）
环境变量：
  PJ52_COOKIE       必填，浏览器会注入这个 Cookie
  PJ52_UA           可选
  PJ52_PROXY        可选
  PJ52_TEST_MODE    可选，设置为 1 启用测试模式（1-5秒延迟）

依赖安装:
  pip install undetected-chromedriver

cron: 0 8 * * *
"""

import os
import re
import time
import shutil
import random
from datetime import datetime
from typing import Optional, Tuple


try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    HAS_UC = True
except ImportError:
    HAS_UC = False

try:
    from pyvirtualdisplay import Display
    HAS_XVFB = True
except ImportError:
    HAS_XVFB = False

try:
    from notify import send as ql_send
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

SITE_URL = "https://www.52pojie.cn/"
INDEX_URL = "https://www.52pojie.cn/forum.php"
SIGNIN_URL = "https://www.52pojie.cn/home.php?mod=task&do=apply&id=2"
TASK_URL = "https://www.52pojie.cn/home.php?mod=task&do=draw&id=2"
DONE_URL = "https://www.52pojie.cn/home.php?mod=task&item=done"

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def send_notify(title: str, content: str):
    if HAS_NOTIFY:
        try:
            ql_send(title, content)
        except Exception as e:
            log(f"通知发送失败: {e}")
    else:
        log(f"[通知] {title}\n{content}")


def parse_cookie_string(cookie_str: str) -> list:
    """将 Cookie 字符串解析为字典列表"""
    cookies = []
    if not cookie_str:
        return cookies
    
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            key, value = item.split('=', 1)
            cookies.append({
                'name': key.strip(),
                'value': value.strip(),
                'domain': '.52pojie.cn',
                'path': '/',
            })
    
    return cookies


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
            log(f"找到 Chrome: {path}")
            return path
    
    log("⚠️ 未找到 Chrome 浏览器")
    return None


def find_chromedriver():
    """查找匹配的 ChromeDriver"""
    possible_paths = [
        '/usr/local/bin/chromedriver-149',
        '/usr/local/bin/chromedriver',
        '/usr/bin/chromedriver',
        shutil.which('chromedriver'),
    ]
    
    for path in possible_paths:
        if path and os.path.exists(path):
            log(f"找到 ChromeDriver: {path}")
            return path
    
    log("⚠️ 未找到 ChromeDriver")
    return None


def random_delay(min_sec=1.0, max_sec=3.0):
    """随机延迟"""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


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
    
    return any(keyword in html for keyword in waf_keywords)


def wait_for_page_load(driver, max_wait=60):
    """等待页面加载完成"""
    log("等待页面加载...")
    
    start_time = time.time()
    last_check = ""
    stable_count = 0
    
    while time.time() - start_time < max_wait:
        try:
            html = driver.page_source
            
            # 检查是否还在 WAF 页面
            if not check_waf_challenge(html):
                # 检查页面内容是否稳定（连续2次相同）
                if html == last_check:
                    stable_count += 1
                    if stable_count >= 2:
                        log("✅ 页面加载完成")
                        return True
                else:
                    stable_count = 0
                
                last_check = html
            
            time.sleep(2)
        except:
            pass
    
    log("⚠️ 页面加载超时")
    return False


def check_already_signed(html: str) -> Tuple[bool, str]:
    """检查是否已签到"""
    if not html:
        return False, ""
    
    # 方法1: 导航栏签到链接
    pattern = r'<a[^>]*href=["\']home\.php\?mod=task&do=apply&id=2["\'][^>]*>([^<]+)</a>'
    match = re.search(pattern, html)
    
    if match:
        text = match.group(1).strip()
        log(f"签到链接文本: {text}")
        
        if "签到已得" in text or "已签" in text:
            days_match = re.search(r'(\d+)', text)
            if days_match:
                return True, f"今日已签到 (已签 {days_match.group(1)} 天)"
            return True, f"今日已签到 ({text})"
    
    # 方法2: 页面内容
    if "您今天已经签到" in html or "今天已经签到过" in html or "您今天已经申请过" in html:
        return True, "今日已签到"
    
    return False, ""


def parse_signin_result(html: str) -> Tuple[Optional[bool], str]:
    """解析签到结果"""
    if not html:
        return None, "页面为空"
    
    # 已签到
    if "您今天已经签到" in html or "已经签到过" in html or "您今天已经申请过" in html:
        return True, "今日已签到"
    
    # 签到成功 - 多种格式匹配
    # 格式1: 获得了 X 个CB
    cb_match = re.search(r'获得了?\s*(\d+)\s*个?CB', html)
    if cb_match:
        return True, f"签到成功，获得 {cb_match.group(1)} CB"
    
    # 格式2: 积分 吾爱币 X CB
    cb_match2 = re.search(r'积分[^>]*吾爱币\s*(\d+)\s*CB', html)
    if cb_match2:
        return True, f"签到成功，获得 {cb_match2.group(1)} CB"
    
    # 格式3: 完成于 YYYY-M-D
    complete_match = re.search(r'完成于\s*(\d{4}-\d{1,2}-\d{1,2})', html)
    if complete_match:
        return True, f"签到成功，完成于 {complete_match.group(1)}"
    
    # 关键词匹配
    if "恭喜" in html or "成功" in html:
        return True, "签到成功"
    
    # 签到失败
    if "失败" in html or "错误" in html:
        return False, "签到失败"
    
    return None, "未识别到签到结果"


def verify_signin_done(driver) -> Tuple[bool, str]:
    """访问任务完成页面确认签到"""
    try:
        log(f"\n=== Step 8: 验证签到结果 ===")
        log(f"访问任务完成页 {DONE_URL}")
        driver.get(DONE_URL)
        
        if not wait_for_page_load(driver, max_wait=60):
            return False, "任务完成页加载超时"
        
        random_delay(1, 2)
        html = driver.page_source
        
        # 检查今日签到记录 - 支持多种日期格式
        now = datetime.now()
        today_patterns = [
            now.strftime("%Y-%m-%d"),           # 2026-06-29
            now.strftime("%Y-%-m-%-d"),         # 2026-6-29 (Linux)
            now.strftime("%Y-%#m-%#d"),         # 2026-6-29 (Windows)
            f"{now.year}-{now.month}-{now.day}" # 2026-6-29 (通用)
        ]
        
        for today in today_patterns:
            if f"完成于 {today}" in html or f"完成于\n{today}" in html or f"完成于 {today.strip()}" in html:
                log(f"✅ 找到今日签到记录: {today}")
                cb_match = re.search(r'吾爱币\s*(\d+)\s*CB', html)
                if cb_match:
                    return True, f"签到成功，获得 {cb_match.group(1)} CB"
                return True, "签到成功"
        
        # 简化匹配：只要看到"每日签到"和"完成于"和今天的数字
        if "每日签到红包任务" in html and "完成于" in html:
            # 提取日期数字
            date_match = re.search(r'完成于\s*(\d{4})[^\d]*(\d{1,2})[^\d]*(\d{1,2})', html)
            if date_match:
                year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                if year == now.year and month == now.month and day == now.day:
                    log(f"✅ 找到今日签到记录: {year}-{month}-{day}")
                    cb_match = re.search(r'吾爱币\s*(\d+)\s*CB', html)
                    if cb_match:
                        return True, f"签到成功，获得 {cb_match.group(1)} CB"
                    return True, "签到成功"
        
        log("⚠️ 未在任务完成页找到今日签到记录")
        return False, "未在任务完成页找到今日签到记录"
        
    except Exception as e:
        log(f"验证异常: {e}")
        import traceback
        log(traceback.format_exc())
        return False, f"验证失败: {str(e)}"


def signin_with_browser(cookie_str: str) -> Tuple[bool, str]:
    """使用浏览器签到（注入 Cookie）"""
    log("=== 启动浏览器签到流程 ===")
    
    if not HAS_UC:
        return False, "未安装 undetected-chromedriver"
    
    display = None
    driver = None
    
    # 启动虚拟显示
    if HAS_XVFB:
        try:
            log("启动虚拟显示...")
            display = Display(visible=False, size=(1920, 1080))
            display.start()
            log("✅ 虚拟显示已启动")
        except Exception as e:
            log(f"⚠️ 虚拟显示启动失败: {e}")
    
    try:
        chrome_path = find_chrome_binary()
        if not chrome_path:
            return False, "未找到 Chrome 浏览器"
        
        chromedriver_path = find_chromedriver()
        if not chromedriver_path:
            return False, "未找到 ChromeDriver"
        
        log(f"使用 ChromeDriver: {chromedriver_path}")
        log(f"使用 Chromium: {chrome_path}")
        
        # 配置 Chrome 选项
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        # 启动浏览器（指定 ChromeDriver 路径）
        log("启动浏览器...")
        driver = uc.Chrome(
            options=options,
            driver_executable_path=chromedriver_path,
            browser_executable_path=chrome_path,
            use_subprocess=False
        )
        log("✅ 浏览器已启动")
        
        # Step 1: 访问首页（触发 WAF）
        log(f"\n=== Step 1: 访问首页 ===")
        log(f"访问 {SITE_URL}")
        driver.get(SITE_URL)
        
        if not wait_for_page_load(driver, max_wait=60):
            return False, "首页加载超时"
        
        log("✅ 首页加载成功")
        random_delay(2, 3)
        
        # Step 2: 注入 Cookie
        log("\n=== Step 2: 注入 Cookie ===")
        cookies = parse_cookie_string(cookie_str)
        
        if not cookies:
            return False, "Cookie 解析失败"
        
        log(f"准备注入 {len(cookies)} 个 Cookie")
        
        for cookie in cookies:
            try:
                driver.add_cookie(cookie)
                log(f"  ✓ {cookie['name']}")
            except Exception as e:
                log(f"  ✗ {cookie['name']}: {e}")
        
        log("✅ Cookie 注入完成")
        random_delay(1, 2)
        
        # Step 3: 刷新页面（使 Cookie 生效）
        log("\n=== Step 3: 刷新页面 ===")
        driver.refresh()
        
        if not wait_for_page_load(driver, max_wait=60):
            return False, "刷新后页面加载超时"
        
        random_delay(2, 3)
        
        # Step 4: 访问论坛首页检查登录状态
        log("\n=== Step 4: 检查登录状态 ===")
        log(f"访问 {INDEX_URL}")
        driver.get(INDEX_URL)
        
        if not wait_for_page_load(driver, max_wait=60):
            return False, "论坛首页加载超时"
        
        random_delay(2, 3)
        
        html = driver.page_source
        
        # 检查是否登录成功
        logged_in = any(k in html for k in ["退出", "个人资料", "我的帖子", "用户组"])
        
        if not logged_in:
            log("❌ Cookie 已失效，请手动更新")
            return False, "Cookie 已失效，请手动更新 PJ52_COOKIE"
        
        log("✅ 登录验证成功")
        
        # Step 5: 检查是否已签到
        log("\n=== Step 5: 检查签到状态 ===")
        already, msg = check_already_signed(html)
        
        if already:
            log(f"✅ {msg}")
            return True, msg
        
        log("📋 未检测到今日签到记录")
        
        # Step 6: 申请签到任务
        log("\n=== Step 6: 申请签到任务 ===")
        log(f"访问 {SIGNIN_URL}")
        driver.get(SIGNIN_URL)
        
        if not wait_for_page_load(driver, max_wait=60):
            return False, "签到任务页加载超时"
        
        random_delay(2, 3)
        
        html = driver.page_source
        
        if "您今天已经申请过" in html:
            log("✅ 任务已申请")
        elif "成功" in html or "恭喜" in html:
            log("✅ 任务申请成功")
        else:
            log("⚠️ 任务申请结果未知")
        
        # Step 7: 领取签到奖励
        log("\n=== Step 7: 领取签到奖励 ===")
        log(f"访问 {TASK_URL}")
        driver.get(TASK_URL)
        
        if not wait_for_page_load(driver, max_wait=60):
            return False, "奖励页加载超时"
        
        random_delay(2, 3)
        
        html = driver.page_source
        
        # 先尝试解析当前页面
        success, message = parse_signin_result(html)
        
        if success is True:
            log(f"✅ {message}")
            return True, message
        elif success is False:
            log(f"❌ {message}")
            return False, message
        else:
            # 未识别，访问任务完成页确认
            log(f"⚠️ {message}")
            log("尝试访问任务完成页确认...")
            
            verify_success, verify_msg = verify_signin_done(driver)
            return verify_success, verify_msg
        
    except Exception as e:
        log(f"❌ 异常: {e}")
        import traceback
        log(traceback.format_exc())
        return False, f"签到出错: {str(e)}"
    
    finally:
        if driver:
            try:
                log("\n关闭浏览器...")
                driver.quit()
                log("✅ 浏览器已关闭")
            except:
                pass
        
        if display:
            try:
                display.stop()
                log("✅ 虚拟显示已关闭")
            except:
                pass


def main():
    cookie = os.environ.get("PJ52_COOKIE", "").strip()
    test_mode = os.environ.get("PJ52_TEST_MODE", "").strip() == "1"
    
    if not cookie:
        log("❌ 未设置 PJ52_COOKIE")
        send_notify("【52破解签到】", "❌ 未设置环境变量 PJ52_COOKIE")
        return
    
    log("="*60)
    log("开始 52破解论坛自动签到（浏览器模式）")
    log("="*60)
    
    # 随机延迟
    if test_mode:
        delay = random.randint(1, 5)
        log(f"\n⏰ 测试模式：随机延迟 {delay} 秒...")
    else:
        delay = random.randint(60, 1200)  # 1-20分钟
        minutes = delay // 60
        seconds = delay % 60
        log(f"\n⏰ 随机延迟 {minutes} 分 {seconds} 秒...")
    
    time.sleep(delay)
    log("✅ 延迟结束，开始执行\n")
    
    success, message = signin_with_browser(cookie)
    
    # 发送通知
    status_icon = "✅" if success else "❌"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log("\n" + "="*60)
    log(f"{status_icon} 签到结果: {message}")
    log("="*60)
    
    send_notify(
        "【52破解签到】",
        f"{status_icon} {message}\n时间: {now_str}"
    )


if __name__ == "__main__":
    main()
