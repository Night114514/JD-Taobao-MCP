# JD-Taobao Browser MCP

一个本地运行、人工参与的 MCP Server。它通过 Playwright 打开真实、可见的 Chromium 浏览器，让 Codex 或其他 MCP 客户端在京东、淘宝、天猫页面中进行低频浏览、商品搜索、详情提取和截图。

> 本项目默认只读。用户必须自己完成扫码、密码、验证码、滑块和安全验证；工具不会绕过平台风控，也不会自动购买、加购、结算或支付。

## 功能

- 打开京东、淘宝登录页，并复用独立浏览器资料目录中的登录状态。
- 搜索京东或淘宝商品，返回标题、价格、店铺、评论文本、商品链接和图片。
- 打开商品详情页，提取标题、价格、店铺、规格、图片、产品参数、好评、差评、Meta、JSON-LD 和页面文本摘要。
- 商品详情输出带硬约束：必须包含 `product_url`、`product_parameters`、`good_reviews`、`bad_reviews` 及对应 `status` 字段；`good_reviews` 最多 5 条，`bad_reviews` 最多 2 条。
- 支持通用浏览器操作：打开 URL、页面快照、列出可交互元素、点击普通元素、普通输入、滚动、返回、截图。
- 只允许访问 `*.jd.com`、`*.360buy.com`、`*.taobao.com`、`*.tmall.com`。

## 项目结构

```text
JD-Taobao-MCP/
├─ server.py                       MCP 工具入口
├─ jd_taobao_mcp/
│  ├─ browser.py                   Playwright 持久化浏览器与通用操作
│  ├─ service.py                   搜索和详情页流程
│  ├─ safety.py                    域名、敏感输入与交易动作防护
│  └─ extractors/                  京东/淘宝页面提取器
├─ config_examples/
│  ├─ codex-config.toml            Codex 配置示例
│  └─ mcp-client.json              Cursor、Claude Desktop 等配置示例
├─ scripts/
│  ├─ install_windows.ps1          Windows 安装脚本
│  └─ start_windows.bat            Windows 启动脚本
├─ .env.example                    环境变量示例
├─ pyproject.toml                  Python 包配置
└─ README.md                       项目主页文档
```

## Windows 安装

要求：

- Windows 10/11
- Python 3.11+，推荐 Python 3.12
- Codex CLI 或其他支持 MCP 的客户端

在 PowerShell 中执行：

```powershell
git clone https://github.com/HaonanYu123/JD-Taobao-MCP.git
cd JD-Taobao-MCP
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_windows.ps1
```

脚本会完成：

- 创建 `.venv`
- 安装本项目和 MCP SDK
- 安装 Playwright Chromium
- 首次复制 `.env.example` 为 `.env`
- 设置本地 Playwright 浏览器目录 `.ms-playwright`

手动安装：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e "."
.\.venv\Scripts\python.exe -m playwright install chromium
copy .env.example .env
```

本地启动测试：

```powershell
.\.venv\Scripts\python.exe server.py
```

如果服务进入等待状态，没有立即退出，说明 MCP stdio 服务可以被客户端拉起。按 `Ctrl+C` 退出。

## Codex 配置

Codex 的 MCP 配置文件通常位于：

```text
%USERPROFILE%\.codex\config.toml
```

把下面配置追加到 `config.toml`，并把 `<PROJECT_DIR>` 替换为本仓库的绝对路径，例如：

```text
C:\Users\你的用户名\Desktop\JD-Taobao-MCP
```

```toml
[mcp_servers.jd_taobao_browser]
command = "<PROJECT_DIR>/.venv/Scripts/python.exe"
args = ["<PROJECT_DIR>/server.py"]
cwd = "<PROJECT_DIR>"
enabled = true
required = false
startup_timeout_sec = 30
tool_timeout_sec = 120
default_tools_approval_mode = "prompt"

[mcp_servers.jd_taobao_browser.env]
PLAYWRIGHT_HEADLESS = "false"
ALLOW_STATE_CHANGING_ACTIONS = "false"
PLAYWRIGHT_BROWSERS_PATH = ".ms-playwright"
BROWSER_PROFILE_DIR = ".tmp/browser-profile"
ARTIFACTS_DIR = "artifacts"
TAOBAO_SEARCH_MODE = "mobile"
```

也可以用命令添加：

```powershell
codex mcp add jd-taobao-browser --env PLAYWRIGHT_HEADLESS=false --env ALLOW_STATE_CHANGING_ACTIONS=false --env PLAYWRIGHT_BROWSERS_PATH=.ms-playwright --env BROWSER_PROFILE_DIR=.tmp/browser-profile --env ARTIFACTS_DIR=artifacts --env TAOBAO_SEARCH_MODE=mobile -- C:\Users\你的用户名\Desktop\JD-Taobao-MCP\.venv\Scripts\python.exe C:\Users\你的用户名\Desktop\JD-Taobao-MCP\server.py
codex mcp list
```

配置后重启 Codex。看到 `jd-taobao-browser` 或 `jd_taobao_browser` 已启用后即可调用工具。

## Cursor、Claude Desktop 等 JSON 客户端配置

参考 `config_examples/mcp-client.json`：

```json
{
  "mcpServers": {
    "jd-taobao-browser": {
      "command": "<PROJECT_DIR>\\.venv\\Scripts\\python.exe",
      "args": ["<PROJECT_DIR>\\server.py"],
      "env": {
        "PLAYWRIGHT_HEADLESS": "false",
        "ALLOW_STATE_CHANGING_ACTIONS": "false",
        "PLAYWRIGHT_BROWSERS_PATH": ".ms-playwright",
        "BROWSER_PROFILE_DIR": ".tmp/browser-profile",
        "ARTIFACTS_DIR": "artifacts",
        "TAOBAO_SEARCH_MODE": "mobile"
      }
    }
  }
}
```

## 首次使用流程

1. 调用 `browser_start()` 启动可见浏览器。
2. 调用 `open_login(platform="jd")` 或 `open_login(platform="taobao")`。
3. 在浏览器里手动扫码、输入密码、完成验证码或安全验证。
4. 调用 `check_login(platform="jd")` 或 `check_login(platform="taobao")`。
5. 调用 `search_products(...)` 或 `get_product_detail(url)` 提取商品数据。

示例提示：

```text
用 jd-taobao-browser MCP 搜索京东的“RTX 5070 笔记本”，最多返回 10 个，价格 7000 到 12000 元，并按价格从低到高排序。不要点击购买或购物车。
```

```text
打开这个淘宝商品链接，提取标题、当前页面价格、店铺、产品参数、最多 5 条好评和最多 2 条差评；页面要求验证时停止并让我手动处理。
```

## 工具清单

| 工具 | 作用 |
|---|---|
| `browser_start` | 启动可见 Chromium 浏览器 |
| `browser_status` | 查看京东、淘宝浏览器状态 |
| `open_login` | 打开京东或淘宝登录页 |
| `check_login` | 检查是否可能已登录，不返回 Cookie 值 |
| `open_url` | 打开允许域名下的 URL |
| `search_products` | 搜索商品并结构化提取 |
| `get_product_detail` | 提取商品详情，包含硬约束字段 |
| `page_snapshot` | 获取当前页面文本、链接、表单和基础元数据 |
| `extract_current_page` | 对当前页面执行快照和商品字段提取 |
| `list_page_elements` | 列出当前可交互元素并分配临时 ref |
| `click_page_element` | 点击普通元素，默认阻止交易和状态变更动作 |
| `type_into_element` | 输入普通文本，拒绝密码、验证码、支付等敏感字段 |
| `scroll_page` | 页面滚动 |
| `go_back` | 返回上一页 |
| `take_screenshot` | 保存截图到 `ARTIFACTS_DIR` |
| `browser_close` | 关闭浏览器 |

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PLAYWRIGHT_HEADLESS` | `false` | 是否无头运行；建议保持 `false`，便于人工登录和验证 |
| `BROWSER_CHANNEL` | 空 | 可填 `msedge` 或 `chrome`，留空使用 Playwright Chromium |
| `BROWSER_EXECUTABLE_PATH` | 空 | 指定通用浏览器可执行文件路径 |
| `JD_BROWSER_EXECUTABLE_PATH` | 空 | 单独指定京东浏览器路径 |
| `TAOBAO_BROWSER_EXECUTABLE_PATH` | 空 | 单独指定淘宝/天猫浏览器路径 |
| `TAOBAO_SEARCH_MODE` | `mobile` | 淘宝搜索模式，可选 `mobile` 或 `pc` |
| `BROWSER_PROFILE_DIR` | `~/.jd-taobao-browser-mcp/browser-profile` | 独立浏览器资料目录 |
| `ARTIFACTS_DIR` | `~/.jd-taobao-browser-mcp/artifacts` | 截图等产物目录 |
| `PLAYWRIGHT_BROWSERS_PATH` | `.ms-playwright` | Playwright 浏览器下载目录 |
| `NAVIGATION_TIMEOUT_MS` | `45000` | 页面导航超时 |
| `ACTION_TIMEOUT_MS` | `15000` | 单步操作超时 |
| `ACTION_DELAY_MS` | `700` | 操作间隔 |
| `SLOW_MO_MS` | `80` | Playwright 慢动作延迟 |
| `MAX_PAGE_TEXT_CHARS` | `18000` | 页面文本摘要最大长度 |
| `MAX_SEARCH_RESULTS` | `30` | 单次搜索最多返回数量 |
| `ALLOW_STATE_CHANGING_ACTIONS` | `false` | 是否允许购买、加购、关注等状态变更动作；不建议开启 |
| `PROXY` | 空 | 可选代理，例如 `http://127.0.0.1:7897` |

## 安全边界

- 不绕过验证码、滑块、安全验证或平台风控。
- 不注入反检测脚本，不伪造浏览器环境。
- 不读取或返回 Cookie 值，只在登录检查时返回 Cookie 名称。
- 密码、验证码、支付密码、银行卡、身份证、OTP 等字段禁止自动输入。
- 默认拒绝购买、加购、结算、支付、关注、收藏、删除和账户信息修改。
- 不适合高频、大规模采集。

## 常见问题

### 为什么不要使用日常 Chrome/Edge 用户目录？

Playwright 持久化上下文会保存 Cookie、本地存储和登录状态。不要把 `BROWSER_PROFILE_DIR` 指向日常浏览器默认用户目录；浏览器可能拒绝并发使用，也会增加误操作风险。

### 页面要求验证怎么办？

工具会返回 `requires_user_verification=true` 或在状态字段里说明原因。此时需要用户在可见浏览器中手动完成验证，然后再继续调用工具。

### GitHub 主页为什么会空？

GitHub 只会把仓库根目录的 `README.md` 显示在项目主页。详细文档必须放在仓库根目录，而不是只放在子目录或缺失的路径下。

## 开发命令

```powershell
.\.venv\Scripts\python.exe -m pytest
```

```powershell
.\scripts\start_windows.bat
```

## License

MIT
