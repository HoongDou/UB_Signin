"""
UBits 自动签到脚本
环境变量：
  UBITS_USERNAME      必填，用于浏览器登录
  UBITS_PASSWORD      必填
  UBITS_TOTP_SECRET   必填
  UBITS_COOKIE        可选，自动保存/更新
  UBITS_UA            可选，自动保存/更新
  UBITS_PROXY         可选，代理地址
  UBITS_ClientID      可选，青龙面板 Client ID（用于自动更新环境变量）
  UBITS_ClientSecret  可选，青龙面板 Client Secret


cron: 0 8 * * *
"""

import os
import re
import pyotp
import time
import shutil
import json
from datetime import datetime
from typing import Optional, Tuple



try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    from selenium.webdriver.common.action_chains import ActionChains
    HAS_UC = True
except ImportError:
    HAS_UC = False

try:
    import ddddocr
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

try:
    from pyvirtualdisplay import Display
    HAS_XVFB = True
except ImportError:
    HAS_XVFB = False

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

LOGIN_URL = "https://ubits.club/login.php"
SIGNIN_URL = "https://ubits.club/attendance.php"
SITE_URL = "https://ubits.club/"
TIMEOUT = 60

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def send_notify(title: str, content: str):
    """发送通知（青龙 notify.py）"""
    if HAS_NOTIFY:
        try:
            log(f"[调试] 准备发送通知: {title}")
            ql_send(title, content)
            log(f"[调试] 通知已调用 ql_send")
        except Exception as e:
            log(f"❌ 通知发送异常: {e}")
            import traceback
            log(traceback.format_exc())
    else:
        log(f"⚠️ notify.py 未导入，无法发送通知")
        log(f"[通知] {title}\n{content}")

class QingLongAPI:
    """青龙面板 API 操作类"""
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "http://localhost:5700"
        self.token = None
    
    def get_token(self) -> bool:
        """获取 API Token"""
        try:
            url = f"{self.base_url}/open/auth/token"
            params = {
                "client_id": self.client_id,
                "client_secret": self.client_secret
            }
            resp = cffi_requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200:
                    self.token = data["data"]["token"]
                    log("✅ 获取青龙 API Token 成功")
                    return True
                else:
                    log(f"❌ 获取 Token 失败: {data.get('message')}")
                    return False
            else:
                log(f"❌ 获取 Token 失败，状态码: {resp.status_code}")
                return False
        except Exception as e:
            log(f"❌ 获取 Token 异常: {e}")
            return False
    
    def get_envs(self) -> Optional[list]:
        """获取所有环境变量"""
        if not self.token:
            return None
        
        try:
            url = f"{self.base_url}/open/envs"
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = cffi_requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200:
                    return data["data"]
                else:
                    log(f"❌ 获取环境变量失败: {data.get('message')}")
                    return None
            else:
                log(f"❌ 获取环境变量失败，状态码: {resp.status_code}")
                return None
        except Exception as e:
            log(f"❌ 获取环境变量异常: {e}")
            return None
    
    def update_env(self, env_id: int, name: str, value: str) -> bool:
        """更新环境变量"""
        if not self.token:
            return False
        
        try:
            url = f"{self.base_url}/open/envs"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            data = {
                "id": env_id,
                "name": name,
                "value": value
            }
            resp = cffi_requests.put(url, headers=headers, json=data, timeout=10)
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 200:
                    log(f"✅ 更新环境变量 {name} 成功")
                    return True
                else:
                    log(f"❌ 更新环境变量 {name} 失败: {result.get('message')}")
                    return False
            else:
                log(f"❌ 更新环境变量 {name} 失败，状态码: {resp.status_code}")
                return False
        except Exception as e:
            log(f"❌ 更新环境变量 {name} 异常: {e}")
            return False
    
    def add_env(self, name: str, value: str) -> bool:
        """添加环境变量"""
        if not self.token:
            return False
        
        try:
            url = f"{self.base_url}/open/envs"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            data = [{"name": name, "value": value}]
            resp = cffi_requests.post(url, headers=headers, json=data, timeout=10)
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 200:
                    log(f"✅ 添加环境变量 {name} 成功")
                    return True
                else:
                    log(f"❌ 添加环境变量 {name} 失败: {result.get('message')}")
                    return False
            else:
                log(f"❌ 添加环境变量 {name} 失败，状态码: {resp.status_code}")
                return False
        except Exception as e:
            log(f"❌ 添加环境变量 {name} 异常: {e}")
            return False
    
    def update_or_add_env(self, name: str, value: str) -> bool:
        """更新或添加环境变量"""
        envs = self.get_envs()
        if envs is None:
            return False
        
        # 查找是否已存在
        for env in envs:
            if env.get("name") == name:
                return self.update_env(env["id"], name, value)
        
        # 不存在则添加
        return self.add_env(name, value)


def save_session(cookie: str, ua: str):
    """保存 Cookie 和 UA"""
    client_id = os.environ.get("UBITS_ClientID", "").strip()
    client_secret = os.environ.get("UBITS_ClientSecret", "").strip()
    
    if client_id and client_secret:
        log("=== 自动更新环境变量 ===")
        api = QingLongAPI(client_id, client_secret)
        
        if api.get_token():
            cookie_updated = api.update_or_add_env("UBITS_COOKIE", cookie)
            ua_updated = api.update_or_add_env("UBITS_UA", ua)
            
            if cookie_updated and ua_updated:
                log("✅ Cookie 和 UA 已自动更新到青龙面板")
                return
            else:
                log("⚠️ 部分环境变量更新失败，请检查日志")
        else:
            log("⚠️ 无法连接青龙 API，将打印 Cookie 和 UA 供手动更新")
    else:
        log("⚠️ 未配置 UBITS_ClientID 和 UBITS_ClientSecret")
    
    # 如果自动更新失败或未配置，打印日志供手动更新
    log("\n=== 请手动更新环境变量 ===")
    log(f"UBITS_COOKIE={cookie}")
    log(f"UBITS_UA={ua}")
    log("提示：在青龙面板「环境变量」中更新上述值\n")
    
    # 同时保存到文件备份
    try:
        session_file = "/ql/data/scripts/ubits_session.json"
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({
                "cookie": cookie,
                "ua": ua,
                "updated_at": datetime.now().isoformat()
            }, f, indent=2)
        log(f"✅ Session 已备份到 {session_file}")
    except Exception as e:
        log(f"⚠️ 无法保存 session 文件: {e}")


def build_headers(cookie: str, ua: str, referer: str = None) -> dict:
    """构建 HTTP 请求头"""
    return {
        "Cookie": cookie,
        "User-Agent": ua,
        "Referer": referer or SITE_URL,
        "Origin": SITE_URL.rstrip("/"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }


def fetch(url: str, cookie: str, ua: str, proxies: Optional[dict]) -> Optional[object]:
    """发起 GET 请求"""
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


def under_challenge(html: str) -> bool:
    """检测 Cloudflare 拦截"""
    return any(k in html for k in [
        "Just a moment",
        "Checking your browser",
        "cf-browser-verification",
        "Enable JavaScript and cookies to continue",
    ])


def is_cookie_invalid(final_url: str, html: str) -> bool:
    """检测 Cookie 是否失效"""
    if "login.php" in final_url:
        return True
    invalid_keywords = ["login.php", "takelogin.php", "登录", "登入", "用户名", "密码"]
    logged_in_keywords = ["logout.php", "userdetails.php", "attendance.php", "签到", "控制面板"]
    return any(k in html for k in invalid_keywords) and not any(k in html for k in logged_in_keywords)


def check_already_signed(index_html: str) -> Tuple[bool, str]:
    """检查首页导航栏是否已签到"""
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
    """解析签到结果"""
    # 优先匹配已签到
    m = re.search(r"签到已得\s*(\d+)", html, re.S)
    if m:
        return True, f"今日已签到，已得 {m.group(1)} U币"
    
    # 匹配签到成功
    m = re.search(r"本次签到获得\s*<[^>]+>\s*(\d+)\s*</[^>]+>\s*个U币", html, re.S)
    if m:
        return True, f"签到成功，获得 {m.group(1)} U币"
    
    m = re.search(r"本次签到获得\s*(\d+)\s*个U币", html, re.S)
    if m:
        return True, f"签到成功，获得 {m.group(1)} U币"
    
    if re.search(r"<h2[^>]*>\s*签到成功\s*</h2>", html, re.S):
        return True, "签到成功"
    
    if any(k in html for k in ["今天已签到", "今日已签到", "已经签到", "您今天已经签到过"]):
        return True, "今日已签到"
    
    # 匹配失败
    for k in ["签到失败", "发生错误", "非法请求", "权限不足"]:
        if k in html:
            return False, f"签到失败，页面提示：{k}"
    
    return None, ""


def signin_with_cookie(cookie: str, ua: str, proxies: Optional[dict]) -> Tuple[bool, str]:
    """使用 Cookie 快速签到"""
    log("=== 阶段 1: Cookie 快速签到 ===")
    
    # 1. 检查首页是否已签到
    log(f"检查首页 {SITE_URL}")
    index_res = fetch(SITE_URL, cookie, ua, proxies)
    
    if index_res is not None and index_res.status_code == 200:
        index_html = index_res.text or ""
        
        if under_challenge(index_html):
            log("⚠️ Cookie 被 Cloudflare 拦截")
            return False, "Cookie 被 Cloudflare 拦截"
        
        if is_cookie_invalid(str(index_res.url), index_html):
            log("⚠️ Cookie 已失效")
            return False, "Cookie 已失效"
        
        already, msg = check_already_signed(index_html)
        if already:
            log(f"✅ {msg}")
            return True, msg
    else:
        log("⚠️ 首页检查失败")
        return False, "首页请求失败"
    
    # 2. 请求签到页
    log(f"请求签到页 {SIGNIN_URL}")
    res = fetch(SIGNIN_URL, cookie, ua, proxies)
    
    if res is None:
        return False, "签到页请求失败"
    
    log(f"HTTP {res.status_code}，最终地址：{res.url}")
    html = res.text or ""
    
    if res.status_code == 403:
        if under_challenge(html):
            return False, "签到页被 Cloudflare 拦截"
        return False, f"签到失败，403"
    
    if res.status_code not in (200, 500):
        return False, f"签到失败，状态码：{res.status_code}"
    
    if under_challenge(html):
        return False, "签到页被 Cloudflare 拦截"
    
    if is_cookie_invalid(str(res.url), html):
        return False, "Cookie 已失效"
    
    success, message = parse_signin_result(html)
    if success is not None:
        return success, message
    
    return True, "签到完成，但未识别到具体返回文字"


def find_chrome_binary():
    """查找 Chrome 浏览器路径"""
    possible_paths = [
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
    
    for path in possible_paths:
        if path and os.path.exists(path):
            log(f"找到 Chrome: {path}")
            return path
    
    log("⚠️ 未找到 Chrome 浏览器")
    return None


def recognize_captcha(image_element, driver):
    """识别验证码"""
    if not HAS_OCR:
        log("⚠️ 未安装 ddddocr")
        return None
    
    try:
        screenshot = image_element.screenshot_as_png
        ocr = ddddocr.DdddOcr(show_ad=False)
        result = ocr.classification(screenshot)
        result = result.strip().upper().replace(' ', '')
        log(f"识别验证码: {result}")
        return result
    except Exception as e:
        log(f"验证码识别失败: {e}")
        return None


def has_cloudflare_challenge(driver):
    """检测是否存在 Cloudflare 验证"""
    try:
        title = driver.title.lower()
        if 'cloudflare' in title or 'just a moment' in title:
            return True
        
        body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        if any(keyword in body_text for keyword in [
            'verify you are human',
            'performing security verification',
            'checking your browser',
            'just a moment',
            '人机验证',
            '安全验证'
        ]):
            return True
        
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = iframe.get_attribute('src') or ''
            if any(keyword in src.lower() for keyword in ['cloudflare', 'turnstile', 'challenges']):
                return True
        
        return False
    except:
        return False


def click_cloudflare_checkbox(driver):
    """尝试点击 Cloudflare 验证框"""
    try:
        log("尝试定位并点击 Cloudflare 验证框...")
        
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        
        for idx, iframe in enumerate(iframes):
            try:
                src = iframe.get_attribute('src') or ''
                if any(keyword in src.lower() for keyword in ['cloudflare', 'turnstile', 'challenges']):
                    log(f"找到 Cloudflare iframe (索引 {idx})")
                    
                    driver.switch_to.frame(iframe)
                    time.sleep(1)
                    
                    checkboxes = driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
                    if checkboxes:
                        checkboxes[0].click()
                        log("✅ 已点击复选框")
                        driver.switch_to.default_content()
                        return True
                    
                    clickable_elements = driver.find_elements(By.CSS_SELECTOR, '[role="checkbox"]')
                    if not clickable_elements:
                        clickable_elements = driver.find_elements(By.CSS_SELECTOR, 'label')
                    
                    if clickable_elements:
                        clickable_elements[0].click()
                        log("✅ 已点击验证框")
                        driver.switch_to.default_content()
                        return True
                    
                    driver.switch_to.default_content()
            except Exception as e:
                log(f"处理 iframe {idx} 时出错: {e}")
                try:
                    driver.switch_to.default_content()
                except:
                    pass
        
        log("使用坐标点击方式...")
        try:
            positions = [(75, 193), (100, 193), (140, 193)]
            actions = ActionChains(driver)
            for x, y in positions:
                try:
                    log(f"尝试点击坐标: ({x}, {y})")
                    actions.move_by_offset(x, y).click().perform()
                    time.sleep(1)
                    actions = ActionChains(driver)
                except Exception as e:
                    actions = ActionChains(driver)
            
            log("✅ 已执行坐标点击")
            return True
            
        except Exception as e:
            log(f"坐标点击失败: {e}")
        
        return False
        
    except Exception as e:
        log(f"点击验证框时出错: {e}")
        return False


def handle_cloudflare_continuously(driver, max_attempts=10, interval=5):
    """持续处理 Cloudflare 验证"""
    log("开始持续处理 Cloudflare 验证...")
    
    for attempt in range(max_attempts):
        log(f"第 {attempt + 1}/{max_attempts} 次检查...")
        
        if not has_cloudflare_challenge(driver):
            time.sleep(2)
            if not has_cloudflare_challenge(driver):
                log("✅ 未检测到 Cloudflare 验证")
                return True
        
        log("检测到 Cloudflare 验证")
        click_cloudflare_checkbox(driver)
        
        log(f"等待 {interval} 秒...")
        time.sleep(interval)
    
    log("⚠️ 达到最大尝试次数")
    return False


def signin_with_uc(username: str, password: str, totp_secret: str) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """使用 undetected-chromedriver 登录并签到，返回 (成功, 消息, cookie, ua)"""
    log("=== 阶段 2: 浏览器登录签到 ===")
    
    if not HAS_UC:
        return False, "未安装 undetected-chromedriver", None, None
    
    if not HAS_OCR:
        return False, "未安装 ddddocr", None, None
    
    display = None
    driver = None
    
    if HAS_XVFB:
        try:
            log("启动虚拟显示 (Xvfb)...")
            display = Display(visible=False, size=(1920, 1080))
            display.start()
            log("✅ 虚拟显示已启动")
        except Exception as e:
            log(f"⚠️ 虚拟显示启动失败: {e}")
    
    try:
        log("启动 undetected-chromedriver...")
        
        chromium_path = find_chrome_binary()
        if not chromium_path:
            return False, "未找到 Chrome 浏览器", None, None
        
        chromedriver_path = '/usr/local/bin/chromedriver-149'
        if not os.path.exists(chromedriver_path):
            return False, f"chromedriver 不存在: {chromedriver_path}", None, None
        
        log(f"使用 chromedriver: {chromedriver_path}")
        log(f"使用 chromium: {chromium_path}")
        
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        driver = uc.Chrome(
            options=options,
            driver_executable_path=chromedriver_path,
            browser_executable_path=chromium_path,
            use_subprocess=False
        )
        
        log("✅ 浏览器已启动")
        
        # 访问登录页
        log(f"访问登录页 {LOGIN_URL}")
        driver.get(LOGIN_URL)
        time.sleep(5)
        
        # 处理初始 Cloudflare
        log("处理初始 Cloudflare 验证")
        if not handle_cloudflare_continuously(driver, max_attempts=15, interval=5):
            return False, "初始 Cloudflare 验证失败", None, None
        
        log("✅ Cloudflare 验证通过")
        time.sleep(3)
        
        # 尝试登录（最多3次）
        for login_attempt in range(3):
            log(f"\n=== 登录尝试 {login_attempt + 1}/3 ===")
            
            try:
                username_input = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.NAME, "username"))
                )
                
                if has_cloudflare_challenge(driver):
                    log("登录表单加载时又出现 Cloudflare")
                    if not handle_cloudflare_continuously(driver, max_attempts=10, interval=5):
                        return False, "登录前 Cloudflare 验证失败", None, None
                    username_input = WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.NAME, "username"))
                    )
                
                log("填写用户名...")
                username_input.clear()
                username_input.send_keys(username)
                time.sleep(0.5)
                
                log("填写密码...")
                password_input = driver.find_element(By.NAME, "password")
                password_input.clear()
                password_input.send_keys(password)
                time.sleep(0.5)
                
                log("识别图片验证码...")
                captcha_img = driver.find_element(By.CSS_SELECTOR, 'img[alt="CAPTCHA"]')
                captcha_text = recognize_captcha(captcha_img, driver)
                
                if not captcha_text:
                    log("⚠️ 验证码识别失败，重新加载")
                    driver.refresh()
                    time.sleep(3)
                    continue
                
                log(f"验证码识别结果: {captcha_text}")
                
                imagestring_input = driver.find_element(By.NAME, "imagestring")
                imagestring_input.clear()
                imagestring_input.send_keys(captcha_text)
                time.sleep(0.5)
                
                log("生成两步验证码...")
                totp = pyotp.TOTP(totp_secret)
                twofa_code = totp.now()
                log(f"两步验证码: {twofa_code}")
                
                twofa_input = driver.find_element(By.NAME, "two_step_code")
                twofa_input.clear()
                twofa_input.send_keys(twofa_code)
                time.sleep(0.5)
                
                log("提交登录表单...")
                submit_button = driver.find_element(By.CSS_SELECTOR, 'input[type="submit"][value="登录"]')
                submit_button.click()
                time.sleep(8)
                
                if has_cloudflare_challenge(driver):
                    log("登录后出现 Cloudflare")
                    if not handle_cloudflare_continuously(driver, max_attempts=10, interval=5):
                        return False, "登录后 Cloudflare 验证失败", None, None
                
                time.sleep(3)
                current_url = driver.current_url
                log(f"当前 URL: {current_url}")
                
                if "login.php" not in current_url:
                    log("✅ 登录成功！")
                    break
                else:
                    log(f"⚠️ 登录失败，可能是验证码错误 ({login_attempt + 1}/3)")
                    driver.get(LOGIN_URL)
                    time.sleep(3)
                    
            except TimeoutException:
                log("❌ 登录表单未出现")
                return False, "登录表单未出现", None, None
        
        # 检查最终登录状态
        current_url = driver.current_url
        if "login.php" in current_url:
            return False, "登录失败（3次尝试后仍失败）", None, None
        
        # 提取 Cookie 和 UA
        log("提取 Cookie 和 UA...")
        cookies = driver.get_cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        ua = driver.execute_script("return navigator.userAgent")
        
        log(f"✅ 已提取 Cookie (长度: {len(cookie_str)})")
        log(f"✅ 已提取 UA: {ua[:80]}...")
        
        # 访问签到页
        log(f"\n访问签到页 {SIGNIN_URL}")
        driver.get(SIGNIN_URL)
        time.sleep(5)
        
        if has_cloudflare_challenge(driver):
            log("签到页出现 Cloudflare")
            if not handle_cloudflare_continuously(driver, max_attempts=10, interval=5):
                return False, "签到页 Cloudflare 验证失败", cookie_str, ua
        
        time.sleep(3)
        html = driver.page_source
        
        success, message = parse_signin_result(html)
        
        return success, message, cookie_str, ua
        
    except Exception as e:
        log(f"异常: {str(e)}")
        import traceback
        log(f"详细错误: {traceback.format_exc()}")
        return False, f"签到出错: {str(e)}", None, None
    
    finally:
        if driver:
            try:
                driver.quit()
                log("浏览器已关闭")
            except:
                pass
        
        if display:
            try:
                display.stop()
                log("虚拟显示已关闭")
            except:
                pass


def main():
    username = os.environ.get("UBITS_USERNAME", "").strip()
    password = os.environ.get("UBITS_PASSWORD", "").strip()
    totp_secret = os.environ.get("UBITS_TOTP_SECRET", "").strip()
    cookie = os.environ.get("UBITS_COOKIE", "").strip()
    ua = os.environ.get("UBITS_UA", "").strip() or DEFAULT_UA
    proxy = os.environ.get("UBITS_PROXY", "").strip()
    
    if not username or not password or not totp_secret:
        log("❌ 需要设置 UBITS_USERNAME、UBITS_PASSWORD 和 UBITS_TOTP_SECRET")
        send_notify("【UBits 签到】", "❌ 环境变量未设置完整")
        return
    
    proxies = {"http": proxy, "https": proxy} if proxy else None
    
    log("开始 UBits 自动签到")
    success = False
    message = ""
    
    # 策略 1: 如果有 Cookie，先尝试快速签到
    if cookie:
        log("检测到已保存的 Cookie，尝试快速签到")
        success, message = signin_with_cookie(cookie, ua, proxies)
        
        if success:
            log(f"✅ Cookie 签到成功: {message}")
        else:
            log(f"⚠️ Cookie 签到失败: {message}")
            log("将切换到浏览器登录模式")
    else:
        log("未检测到 Cookie，使用浏览器登录")
    
    # 策略 2: Cookie 失败或不存在，使用浏览器登录
    if not success:
        success, message, new_cookie, new_ua = signin_with_uc(username, password, totp_secret)
        
        # 如果登录成功且获取到新 Cookie，保存
        if new_cookie and new_ua:
            log("✅ 已获取新的 Cookie 和 UA")
            save_session(new_cookie, new_ua)
    
    # 发送通知
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "✅ 成功" if success else "❌ 失败"
    log(f"{status}: {message}")
    
    send_notify(
        "【UBits 自动签到】",
        f"{status}\n结果: {message}\n时间: {now_str}"
    )


if __name__ == "__main__":
    main()
