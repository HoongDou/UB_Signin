# UBits 自动签到

自动完成 [UBits.club](https://ubits.club/) 每日签到，支持青龙面板部署。
代码使用Claude Opus 4.8进行优化。
---

## 特性

- **Cookie 快速签到**：优先使用已保存的 Cookie 快速完成签到
- **自动浏览器登录**：Cookie 失效时自动启动浏览器登录并签到
- **智能状态检测**：避免重复签到，已签到时直接返回
- **自动更新 Cookie**：浏览器登录后自动更新环境变量（需配置 API）
- **Cloudflare 绕过**：支持 `curl_cffi` 和 `undetected-chromedriver` 双重绕过方案，前者效果不佳。

---

## 依赖

### Python 依赖

在青龙面板「依赖管理」中添加以下 Python 依赖：curl_cffi、requests、undetected-chromedriver、pyotp、selenium、ddddocr

### 系统依赖

在青龙面板「依赖管理」中添加以下 Linux 依赖：chromium、xvfb。
注意：需要手动下载并指定 ChromeDriver 149，因为青龙面板默认带的chromium是149版本的，如果你在里面添加crhomedriver的话是150版本的，会无法兼容。

具体操作如下：
#### 进入容器
docker exec -it qinglong bash

##### 下载 ChromeDriver 149
``` bash
cd /tmp
wget https://storage.googleapis.com/chrome-for-testing-public/149.0.7827.196/linux64/chromedriver-linux64.zip
unzip chromedriver-linux64.zip
mv chromedriver-linux64/chromedriver /usr/local/bin/chromedriver-149
chmod +x /usr/local/bin/chromedriver-149
rm -rf chromedriver-linux64*
```

## 部署

### 手动部署

1. 在青龙面板「脚本管理」中新建文件夹 `ubits_signin`，上传 `ubits_signin.py`
2. 添加定时任务：
   - **命令**：`python ubits_signin/ubits_signin.py`
   - **定时规则**：`0 8 * * *`（每天 08:00 执行）
3. 配置环境变量（见下方）
4. 手动运行一次，确认正常

### 自动部署

1. 在青龙面板中添加订阅：`https://github.com/HoongDou/UB_Signin.git`
2. 订阅分支留空，但通常为 `master`（仓库使用 `main`的话请改为 `main`）
3. 订阅完成后，任务会自动带出到青龙面板中
4. 手动运行一次测试，确认正常

---

## 环境变量

在青龙面板「环境变量」中添加。

### 必填变量

| 变量名 | 说明 |
|--------|------|
| `UBITS_USERNAME` | UBits.club 用户名 |
| `UBITS_PASSWORD` | UBits.club 密码 |
| `UBITS_TOTP_SECRET` | 两步验证密钥（TOTP Secret） |

### 可选变量

| 变量名 | 说明 |
|--------|------|
| `UBITS_COOKIE` | Cookie（自动保存/更新，首次运行后自动生成） |
| `UBITS_UA` | User-Agent（自动保存/更新） |
| `UBITS_PROXY` | 代理地址，如 `http://127.0.0.1:7890` |
| `UBITS_ClientID` | 青龙面板 Client ID（用于自动更新环境变量） |
| `UBITS_ClientSecret` | 青龙面板 Client Secret |

### 如何获取 TOTP Secret

1. 登录 UBits.club，进入「安全设置」→「两步验证」
2. 在设置两步验证时，保存显示的密钥（通常是 Base32 格式的字符串）
3. 如已启用，可能需要先禁用再重新启用以获取密钥，或者可参考otpauth这个github。

### 如何获取青龙 API 凭据（可选）

配置后脚本可自动更新 `UBITS_COOKIE` 和 `UBITS_UA`：

1. 青龙面板「系统设置」→「应用设置」
2. 新建应用，获取 Client ID 和 Client Secret
3. 权限选择：环境变量（读取、新建、更新）

---

### 如何获取 Cookie

1. 浏览器登录 [UBits.club](https://ubits.club/)
2. 按 `F12` 打开开发者工具，切换到「网络」标签
3. 刷新页面，点击任意请求，在请求头中找到 `Cookie` 字段
4. 复制完整值粘贴到环境变量中

---

## 通知

脚本支持青龙内置通知（`notify.py`）。在青龙面板「配置文件」→「config.sh」中配置好通知渠道后，签到结果会自动推送。

---

## 常见问题

### 提示「未设置环境变量」

检查 `UBITS_USERNAME`、`UBITS_PASSWORD`、`UBITS_TOTP_SECRET` 是否都已正确填写。

### 提示「被 Cloudflare 拦截」

1. **Cookie 模式**：Cookie 中的 `cf_clearance` 已过期，脚本会自动切换到浏览器登录
2. **浏览器模式**：检查 Chrome 和 ChromeDriver 是否正确安装

### 提示「Cookie 已失效」

脚本会自动启动浏览器登录并更新 Cookie，无需手动处理。

### 提示「未找到 Chrome 浏览器」

参考「系统依赖」部分安装 Chrome 或 Chromium。

### 提示「验证码识别失败」

脚本会自动重试最多 3 次，通常能识别成功。若持续失败，可能是 `ddddocr` 依赖未正确安装。

### Cookie 和 UA 未自动更新

1. 检查是否配置了 `UBITS_ClientID` 和 `UBITS_ClientSecret`
2. 检查青龙 API 应用权限是否包含环境变量的读写权限
3. 如未配置 API，脚本会在日志中打印 Cookie 和 UA，可手动复制更新

---

## 高级配置

### 自定义 ChromeDriver 路径

脚本默认使用 `/usr/local/bin/chromedriver-149`，如需修改：

```python
# 修改 signin_with_uc() 函数中的路径
chromedriver_path = '/path/to/your/chromedriver'

```

### 调整 Cloudflare 验证参数
#### 修改 handle_cloudflare_continuously() 调用参数
handle_cloudflare_continuously(driver, max_attempts=15, interval=5)
##### max_attempts: 最大尝试次数
##### interval: 每次检查间隔（秒）

### 修改签到时间
在青龙面板定时任务中修改 cron 表达式：

- 0 8 * * * - 每天 08:00
- 0 0 * * * - 每天 00:00
- 0 */6 * * * - 每 6 小时一次
