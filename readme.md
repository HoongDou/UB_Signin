# UBits 自动签到

自动完成 [UBits.club](https://ubits.club/) 每日签到，青龙面板部署。

---

## 依赖

脚本优先使用 `curl_cffi` 绕过 Cloudflare 检测，不可用时回退到 `requests`。

在青龙面板「依赖管理」中添加以下 Python 依赖：curl_cffi、requests

---

## 部署

1. 在青龙面板「脚本管理」中新建文件夹 `ubits_signin`，上传 `ubits_signin.py`
2. 添加定时任务：
   - **命令**：`python ubits_signin/ubits_signin.py`
   - **定时规则**：`0 8 * * *`（每天 08:00 执行）
3. 配置环境变量（见下方）
4. 手动运行一次，确认正常

---

## 环境变量

在青龙面板「环境变量」中添加，**Name 字段填 `ubits_signin`** 以关联到对应任务。

| 变量名 | 必填 | 说明 |
|---|---|---|
| `UBITS_COOKIE` | ✅ | 登录 UBits.club 后从浏览器开发者工具复制的完整 Cookie |
| `UBITS_UA` | 可选 | User-Agent，建议与获取 Cookie 时的浏览器保持一致 |
| `UBITS_PROXY` | 可选 | 代理地址，如 `http://127.0.0.1:7890` |

### 如何获取 Cookie

1. 浏览器登录 [UBits.club](https://ubits.club/)
2. 按 `F12` 打开开发者工具，切换到「网络」标签
3. 刷新页面，点击任意请求，在请求头中找到 `Cookie` 字段
4. 复制完整值粘贴到环境变量中

---

## 通知

脚本支持青龙内置通知（`notify.py`）。在青龙面板「配置文件」中配置好通知渠道后，签到结果会自动推送。

---

## 常见问题

**提示「未设置环境变量 UBITS_COOKIE」**
检查环境变量 Name 字段是否填写了 `ubits_signin`，保存后重新运行。

**提示「被 Cloudflare 拦截」**
Cookie 中的 `cf_clearance` 已过期，需要重新从浏览器获取完整 Cookie。

**提示「Cookie 可能已失效」**
重新登录站点并更新 `UBITS_COOKIE` 环境变量。

