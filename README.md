# JD-Taobao Browser MCP

一个本地运行、人工参与的 MCP Server。它通过 Playwright 打开真实、可见的 Chromium 浏览器，让 Codex 或其他 MCP 客户端在京东、淘宝、天猫页面中进行低频浏览、商品搜索、详情提取和截图。

> 本项目默认只读。用户必须自己完成扫码、密码、验证码、滑块和安全验证；工具不会绕过平台风控，也不会自动购买、加购、结算或支付。

## 功能

- 打开京东、淘宝登录页，并复用独立浏览器资料目录中的登录状态。
- 搜索京东或淘宝商品，返回标题、价格、店铺、评论文本、商品链接和图片。
- 打开商品详情页，提取标题、价格、店铺、规格、图片、产品参数、好评、差评、Meta、JSON-LD 和页面文本摘要。
- 商品详情输出带硬约束：必须包含 `product_url`、`product_parameters`、`good_reviews`、`bad_reviews` 及对应 `status` 字段；`good_reviews` 最多 5 条，`bad_reviews` 最多 2 条。
- 京東保留通用瀏覽器操作；淘寶／天貓啟用 Taobao Safe Mode，禁止自動點擊、輸入、滾動及返回上一頁。
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

服務進入等待狀態只代表程序仍在執行，不能證明 MCP 握手成功。按 `Ctrl+C` 退出；請使用下方「離線回歸測試」核對 `initialize`、`tools/list` 及 Mock `tools/call`。

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
| `click_page_element` | 京東：受安全檢查的普通點擊；淘寶／天貓：禁止 |
| `type_into_element` | 京東：拒絕敏感欄位的普通輸入；淘寶／天貓：禁止 |
| `scroll_page` | 京東：頁面滾動；淘寶／天貓：禁止 |
| `go_back` | 京東：返回上一頁；淘寶／天貓：禁止 |
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
| `TAOBAO_SEARCH_MODE` | `mobile` | Taobao Safe Mode 只接受 `mobile`；設定為 `pc` 時搜尋會被拒絕 |
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

工具可能回傳 `requires_user_verification=true`、`automation_paused=true` 或工具錯誤。淘寶／天貓遇到登入或驗證頁後會持久保存暫停狀態；完成手動驗證或重新啟動 MCP 都不會自動解除暫停。請依照下方 Safe Mode 的人工恢復步驟處理，切勿自動重試。

## Taobao Safe Mode

淘寶／天貓的 browser controller 固定啟用 Safe Mode；`ALLOW_STATE_CHANGING_ACTIONS=true` 亦不能解除以下限制：

- 禁止自動點擊、輸入、滾動、切換詳情分頁、展開內容及返回上一頁。
- 搜尋只提取首次載入的結果。`include_details=true` 不會逐件開啟淘寶商品；回傳的 `filters.include_details=false` 及 `details_skipped_for_safety=true` 會說明此限制。
- 每次受控導航須相隔至少 30 秒，每小時最多 10 次；額度在導航前寫入。同一 profile 的程序共用狀態及檔案鎖。
- 登入／驗證頁、導航逾時、HTTP 401／403／429／5xx、缺失 HTTP response 或導航檢查失敗會觸發持久暫停。被拒絕後不得自動重試。
- 淘寶 `check_login` 只檢查目前頁面，不會為檢查登入而導航。
- Safe Mode 不保證商品欄位齊全，也不保證平台不會要求驗證。

JD controller 會核對導航目標、目前頁面，以及導航／互動後的實際平台；若發現淘寶／天貓頁面，會拒絕繼續操作，不會自動返回或重新導航作補救。已知的淘寶／天貓連結會在點擊前被拒絕。正常淘寶操作須由獨立、受 guard 控制的 controller 處理。這是 MCP 操作邊界，不是瀏覽器網絡 sandbox：由 JD 觸發的未知 redirect 可能已載入目標頁面，檢查會阻止其後操作，不能保證瀏覽器沒有送出該請求。

狀態儲存於 `<BROWSER_PROFILE_DIR>/taobao/taobao-safety-state.json`。人工恢復前，先在官方頁面自行完成驗證，再停止所有 MCP server instances。由使用者在本機執行：

```powershell
.\.venv\Scripts\python.exe scripts/taobao_guard_admin.py status
.\.venv\Scripts\python.exe scripts/taobao_guard_admin.py resume
```

`resume` 要求使用者輸入 `RESUME TAOBAO`，並保留導航歷史及限額；MCP 沒有解除暫停工具。不得刪除 state file 或更換 profile 來繞過暫停及限額。

Server 與管理 CLI 共用 `load_settings`，從專案根目錄載入 `.env`，且不覆蓋已明確設定的程序環境變數。相對 `BROWSER_PROFILE_DIR`、`ARTIFACTS_DIR` 及 `PLAYWRIGHT_BROWSERS_PATH` 均以專案根目錄解析，不隨呼叫者的工作目錄改變；CLI 不會更改工作目錄。若 MCP client 另行設定環境變數，執行 CLI 時亦須提供相同設定，並先核對 `status` 顯示的 State file。`status` 只讀取暫停狀態，不讀取 Cookie 或列出環境變數。

## 淘寶參數來源及輸出契約

`get_product_detail` 直接回傳詳情欄位；`extract_current_page` 的詳情位於 `product_like_data`。搜尋結果中的 `detail_output_contract` 只是欄位說明，並不代表每個搜尋項目已取得詳情證據。

| 欄位 | 解讀方式 |
|---|---|
| `product_parameter_evidence` | 每項參數的選定值、`source` 及同頁相同值的 `corroborated_by` |
| `product_parameter_conflicts` | 選定值以外的已觀察來源及值；應先檢查衝突再引用規格 |
| `parameter_evidence_status=provided` | 已提供 evidence 及 conflict arrays；空陣列只描述本次提取所得 |
| `parameter_evidence_status=not_provided` | 未提供證據陣列，不能推斷沒有衝突 |
| `parameter_evidence_status=not_extracted` | 未執行詳情提取，例如 `get_product_detail` 被驗證頁攔截 |

來源優先次序為 `visible_text` → `dom_parameters` → `dom_detail` → `json_ld` → `text_content`；所有參數來源都沒有結果時，才使用 `fallback_text`。`corroborated_by` 只代表同一頁的其他位置有相同值，並非獨立查證。

`visible_text` 只使用 `document.body.innerText`；`text_content` 使用 `document.body.textContent`，可能包含隱藏文字，不會被標成可見來源。兩者分開保存至 evidence／conflict 建立階段，同名不同值會保留為衝突。`text_content` 是新增的來源值；既有必須欄位、evidence／conflict 結構及三個狀態值維持不變。

`extract_current_page` 會檢查 snapshot 及目前頁面的登入／驗證訊號；被攔截時回傳 `success=false`、`requires_user_verification=true`，淘寶的 `product_like_data.parameter_evidence_status=not_extracted`，不呼叫商品 extractor。無法檢查 DOM 時會拒絕提取；淘寶 controller 亦會保存暫停狀態。

`product_parameters_status.complete=true` 只代表至少提取到一項參數，並不代表規格完整。好評最多 5 條、差評最多 2 條；缺失或不足時，以空陣列／部分結果及 `status.reason` 表示，不會為補齊資料而操作淘寶頁面。`price_source=url_upStreamPrice` 代表價格來自原始連結的參數，不能當作已核實的即時售價。該參數只接受有限正數，`NaN`、`Infinity`、溢位及其他非法值會被忽略，不覆蓋頁面價格。

## 離線回歸測試

只需安裝 Python 依賴，毋須安裝或啟動 Playwright 瀏覽器。以下命令使用 Python 內建 `unittest`，不需要額外安裝 `pytest`：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

只執行跨程序 stdio 回歸：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mcp_stdio.py -v
```

`tests/test_mcp_stdio.py` 透過真正的 `ClientSession`、stdio pipes 及獨立 Python 程序核對：

- 生產 `server.py` 的 `__main__` 路徑、`initialize`、`tools/list`、工具說明及輸入 schema；此握手案例不呼叫工具。
- 三個 Mock `tools/call` 的 JSON text／`structuredContent`、Unicode、巢狀資料、來源衝突及參數傳遞。
- 缺少必要參數、不存在的工具及 Mock `SafetyError` 的錯誤回應；錯誤後 session 仍可用，Mock service 不會被重試。
- 測試 fixture 的啟動封鎖及正常關閉；每個 session 有時間上限，profile 與 artifacts 均使用臨時路徑。

測試子程序在匯入 server 前封鎖 Playwright 啟動、額外子程序及非 loopback socket 連線，並停用 `.env` 載入。Windows asyncio 內部 socket pair 可使用 loopback。這是測試防護，不是生產網絡 sandbox。Mock `tools/call` 驗證的是協定及序列化，不能替代 service／guard 測試，也不能證明真實淘寶 DOM、登入、風控或商品資料完整性。

### GitHub 主页为什么会空？

GitHub 只会把仓库根目录的 `README.md` 显示在项目主页。详细文档必须放在仓库根目录，而不是只放在子目录或缺失的路径下。

## 开发命令

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

```powershell
.\scripts\start_windows.bat
```

## License

MIT
