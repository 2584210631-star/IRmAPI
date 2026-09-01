# IRmAPI

一个**类似 Chat2API** 的多通道 OpenAI 兼容 API 网关，**内置豆包（Doubao）**，并集成 DeepSeek / 通义千问 Qwen，帮你实现「词元自由」。

> Chat2API 的思路是：把网页版 ChatGPT 的会话凭据，包装成 OpenAI 格式的 API 接口。
> IRmAPI 做同样的事，但主角换成**豆包**，并且同时支持豆包官方 API、DeepSeek、通义千问和任意 OpenAI 兼容上游。

```
你的客户端（任何 OpenAI 兼容工具 / SDK / Dify / LobeChat / NextChat...）
        │  POST /v1/chat/completions  （标准 OpenAI 格式，支持流式）
        ▼
   IRmAPI 网关  ── 按模型名路由 ──►  豆包网页版（免 Key，浏览器 Cookie / 软件内一键登录）
        │                                   豆包火山方舟（官方 API，有免费额度）
        │                                   DeepSeek（网页版免 Key / 官方 API）
        │                                   通义千问 Qwen（阿里云百炼，官方免费额度）
        │                                   任意 OpenAI 兼容上游（Kimi / 硅基流动 / Ollama...）
        ▼
  返回标准 OpenAI 格式响应（流式 / 非流式）
```

## 五大通道

| 通道 | 模型名示例 | 凭据 | 特点 |
|---|---|---|---|
| **豆包网页版**（逆向，免 Key） | `doubao-web` / `doubao` / `doubao-free` | 浏览器 Cookie（`DOUBAO_COOKIE_1`），**桌面版可软件内一键登录自动抓取** | 免费、与网页版同额度；逆向接口，豆包改版可能失效 |
| **豆包火山方舟**（官方） | `doubao-seed-...` / `ark-*` | API Key（`ARK_API_KEY`） | 稳定、合规，lite 模型每天有免费 token 额度 |
| **DeepSeek** | `deepseek-chat` / `deepseek-reasoner` | 网页版 Cookie（`DEEPSEEK_COOKIE_1..N`）或 `DEEPSEEK_TOKEN` 或官方 `DEEPSEEK_API_KEY` | 网页版免 Key，官方 API 按量兜底；多 Cookie 自动轮询 |
| **通义千问 Qwen** | `qwen-turbo` / `qwen-plus` / `qwen-max` / `qwen-long` | 网页版 Cookie（`QWEN_COOKIE_1`，免 Key）或百炼 `QWEN_API_KEY` | 网页版免 Key 逆向；官方免费额度兜底 |
| **通用 OpenAI 兼容** | `kimi-*` / `glm-*` / `moonshot-*` / `compat-*` | `COMPAT_BASE_URL`(需带 `/v1`) + `COMPAT_API_KEY` | 把 Kimi/智谱/硅基流动/本地 Ollama 等统一进来 |

## 快速开始

```bash
# 1. 安装依赖（Python 3.9+）
pip install -r requirements.txt

# 2. 配置（至少配一个通道）
cp .env.example .env
# 编辑 .env，填入 DOUBAO_COOKIE_1 或 DEEPSEEK_COOKIE_1 或 QWEN_API_KEY 等

# 3. 启动
python app.py          # 默认 0.0.0.0:5005

# 4. 测试
curl http://127.0.0.1:5005/v1/models
curl -N http://127.0.0.1:5005/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 你的凭据" \
  -d '{"model":"doubao-web","messages":[{"role":"user","content":"你好"}],"stream":true}'
```

## 控制台（Web UI）

浏览器打开 **<http://127.0.0.1:5005/console>** 即可使用自带的深色控制台，四个页签：

- **概览**：运行时长 / 请求量 / 成功率 / **五通道**配置状态 / 可用模型
- **凭据**：五通道配置状态 + 各通道获取凭据教程（豆包 / DeepSeek / Qwen 都有） + 排查报错
- **调试**：在线 Playground，选模型 → 填提示词 → 直接对话（走服务端凭据，不暴露密钥）
- **说明**：curl / Python(OpenAI SDK) 接入示例（一键复制）

> 支持 `#凭据` `#调试` 等锚点直达页面（打开 `http://127.0.0.1:5005/console#creds` 直接到凭据页）。
> 控制台为单文件零外部依赖（内联 CSS/JS），无 CDN、无数据库，占用极小，手机也能正常打开。
> 若在 `.env` 设置了 `CONSOLE_KEY`，控制台的 API 需要口令：页面会自动弹出口令输入框，也可以手动在请求头加 `X-Console-Key: <口令>`。

## 桌面版（Windows 原生 exe，不占浏览器）

不想开浏览器？桌面版把网关 + 控制台打包成一个**原生 exe 窗口**，双击即用，弹出的窗口就是软件界面（基于 pywebview，用系统自带的 WebView2，体积小、无浏览器外壳）。

1. 在 Windows 电脑上装好 Python 3.9+
2. **双击 `build.bat`** —— 自动装依赖、PyInstaller 一键打包（约 1-3 分钟）
3. 产出 **`dist\IRmAPI.exe`**，双击运行即可
   - 单文件、无黑色控制台黑窗、自带 IRm 艺术字图标
   - 网关随程序自动在后台启动，关窗口即退出，卸载 = 删掉文件，无残留

**软件内一键登录豆包（自动抓 Cookie）**：桌面版凭据页点「一键登录豆包（桌面版）」，程序会自动弹出豆包登录窗口 → 扫码/输验证码登录 → 自动抓取 Cookie 写入 `.env` 并热生效，全程不用开 F12。

- 不想打包也能跑：`pip install pywebview pyinstaller` 后 `python desktop.py`（源码直接开桌面窗口）
- 命令行 `python desktop.py --check` 可不带图形环境快速自检网关与资源

## 安卓 APK（手机上跑，功能一致）

整个项目可以打包成 Android APK，界面 + 网关 + 一键登录全都有：

- **界面**：Kivy 原生控制面板（服务状态 + 打开控制台 + 一键登录三通道）
- **控制台**：APK 内嵌 WebView 显示 `http://127.0.0.1:5005/console`，与桌面版/网页版完全一致
- **一键登录**：豆包 / DeepSeek / 通义千问 三通道都能在 APK 里点「一键登录」，用 Android 原生 WebView 打开登录页，登录成功后**自动抓 Cookie 写入 .env 并热生效**，不用手动 F12

### 拿到 APK 的三种方式（推荐第 1 种）

**方式一：GitHub Actions 云端免费构建（推荐，不用装任何工具链）**
1. 把这个项目推到 GitHub（新建仓库 → 上传全部文件）
2. Actions 里会自动运行 `build-apk.yml`，构建完成后在 Actions 页面下载 `irmapi-apk` 工件
3. 得到 `bin/IRmAPI-1.3.0-arm64-v8a-debug.apk`，传到手机安装即可（首次安装需允许"未知来源"）

**方式二：本地 buildozer 构建（需要装 Android 工具链，约 20-40 分钟）**
```bash
pip install --user buildozer cython
# 已带 buildozer.spec，直接构建：
buildozer android debug
# 产物在 bin/IRmAPI-1.3.0-*.apk
```
> 首次会自动下载 Android SDK/NDK（约 3-5GB），请保证磁盘空间和网络。

**方式三：Pydroid 3 手机直跑（不用 APK，立即能用）**
1. 手机装 **Pydroid 3**（应用市场/官网）
2. 把源码包解压到手机任意目录，在 Pydroid 的终端里：
   ```bash
   pip install -r requirements.txt
   python app.py
   ```
3. 手机浏览器打开 `http://127.0.0.1:5005/console` 即可用
> Pydroid 模式下没有"一键登录"按钮（无原生 WebView），请按各通道教程手动填 Cookie / Key。

> APK 里的「一键登录」走 Android 原生 WebView + CookieManager，首次建议在真机上完整验证一次登录→自动抓 Cookie→热生效 的链路。

### Docker

```bash
docker build -t irmapi .
docker run -d --name irmapi -p 5005:5005 --env-file .env irmapi
```
docker run -d --name irmapi -p 5005:5005 --env-file .env irmapi
```

### Termux（手机）

```bash
pkg install python -y
pip install -r requirements.txt
python app.py
```

手机/局域网其它设备访问时，把 base_url 指向运行设备的 `http://<IP>:5005/v1` 即可。

## 认证（Authorization）两种用法

和 Chat2API 保持一致：

1. **客户端直传凭据**：请求头 `Authorization: Bearer <cookie 或 sessionid>`，网关直接拿它去调豆包。
2. **服务端账号池**：在 `.env` 设置 `AUTHORIZATION=你的授权码`，客户端用这个授权码当 Key；
   网关自动从服务端凭据池（`DOUBAO_COOKIE_1..N` / `DEEPSEEK_COOKIE_1..N` / `ARK_API_KEY` 等）随机挑选账号，支持多账号轮询、请求失败自动换下一个。

## 获取各通道凭据

### 豆包网页版
1. 用电脑浏览器登录 <https://www.doubao.com/chat/>
2. F12 → 网络(Network) → 在输入框发一句话
3. 找到 `completion` 请求 → 右键 → 复制 → **复制为 cURL (bash)**
4. 取出 `--cookie '...'` 里的整串，粘到 `.env` 的 `DOUBAO_COOKIE_1=`
5. **桌面版用户直接点「一键登录豆包（桌面版）」按钮，自动抓取，无需手动操作**

> 推荐用完整 Cookie（含 `sessionid`、`ttwid`、`uid_tt` 等），稳定性最好。

### DeepSeek（免费）
- **网页版免 Key**：登录 <https://chat.deepseek.com> → F12 → 网络 → 发一句话 → 找 `chat/completions` 请求 → 复制 cURL → 取 `--cookie '...'` 整串填 `DEEPSEEK_COOKIE_1=`（网关自动提取 token；可填 `DEEPSEEK_COOKIE_2..N` 多账号轮询）。也可直接填 `DEEPSEEK_TOKEN=`（请求头 Authorization: Bearer 后那串）。
- **官方 API**（按量，兜底用）：<https://platform.deepseek.com> 创建 Key 填 `DEEPSEEK_API_KEY=`。

### 通义千问 Qwen
- <https://bailian.console.aliyun.com> 开通百炼 → 创建 **API-KEY** → 填 `QWEN_API_KEY=`。新用户有免费 token 额度，速度很快。

## 遇到 400/403/风控怎么办

豆包网页版有反爬签名（`a_bogus`）。网关默认用"假签名"，多数情况下可用；被风控时：

1. 从浏览器任意一个 `completion` 请求的 URL 里复制真实的 `msToken` 和 `a_bogus`，填到 `.env`：
   ```
   DOUBAO_MS_TOKEN=...
   DOUBAO_A_BOGUS=...
   ```
2. 更新 Cookie（sessionid 过期了会返回 `user invalid`）。
3. 还是不行就换 IP / 用官方方舟通道兜底。

## 模型路由规则

| 模型名 | 走哪个通道 |
|---|---|
| `doubao-web` / `doubao-free` / `web-*` | 豆包网页版 |
| `doubao-*`（配了 ARK_API_KEY 时） | 火山方舟官方 |
| `ark-*` / `doubao-ark-*` | 火山方舟官方 |
| `deepseek-chat` / `deepseek-reasoner` / `deepseek-*` | DeepSeek（网页版免 Key，无凭据时报错提示） |
| `qwen-turbo` / `qwen-plus` / `qwen-max` / `qwen-long` / `qwen-*` | 通义千问（百炼） |
| `kimi-*` / `glm-*` / `moonshot-*` / `compat-*` | 通用兼容上游 |
| 其它任意模型名 | 默认豆包网页版 |

> 配置变更后无需重启：`curl -X POST http://127.0.0.1:5005/api/reload` 即可热生效（桌面版登录豆包后也会自动 reload）。

## 功能清单

- [x] OpenAI 兼容 `/v1/chat/completions`、`/v1/models`、`/ping`
- [x] 流式（SSE）与非流式，格式与真实 OpenAI API 一致
- [x] 豆包网页版免 Key 通道（完整 Cookie + 浏览器指纹 + 多轮上下文合并）
- [x] 豆包火山方舟官方通道（OpenAI 兼容直连）
- [x] **DeepSeek 通道**（网页版 Cookie 免 Key / Token / 官方 API 三方式，多账号轮询）
- [x] **通义千问 Qwen 通道**（网页版 Cookie 免 Key 逆向 / 阿里云百炼官方免费额度）
- [x] 通用 OpenAI 兼容上游（Kimi / 硅基流动 / Ollama ...）
- [x] 多账号轮询、失败重试、会话不留痕（自动删除豆包侧会话）
- [x] 服务端账号池 + 客户端直传凭据两种认证模式
- [x] 配置热重载 `/api/reload`（改 .env 不用重启）
- [x] Docker / Termux 均可运行
- [x] 深色 Web 控制台（概览 / 凭据教程 / 在线调试 / 接入说明，零外部依赖，支持锚点直达）
- [x] 桌面版 exe（`build.bat` 一键打包，pywebview 原生窗口，带 IRm 艺术字图标）
- [x] **桌面版/APK 软件内一键登录豆包·DeepSeek·千问自动抓 Cookie**
- [x] 单元测试 47 项

## 测试

```bash
python -m pytest tests/ -v
```

## 已知限制（务必读）

- **豆包网页版 / DeepSeek 网页版通道属于逆向接口**：依赖网页版当前的反爬与接口结构，服务方随时可能调整导致失效。正式/生产场景推荐用**官方通道**（火山方舟 / 百炼 / DeepSeek API，合规、稳定）。
- 豆包网页版通道暂不支持图片/文件上传（社区 ImageX 管道，后续可扩展）。
- 逆向接口原则上仅供个人学习与自用，请勿商业化、勿大规模对外提供服务。
- 桌面版「一键登录豆包」依赖 pywebview 登录窗口（Windows 下用系统 WebView2），Cookie 抓取后自动写入 `.env` 并热生效。

## 项目结构

```
irmapi/
├── app.py                 # 启动入口
├── desktop.py             # 桌面版入口（网关 + 原生窗口 + 三通道一键登录，打包 exe 用）
├── android_main.py        # 安卓版入口（Kivy：网关 + 控制面板 + Android WebView 一键登录）
├── main.py                # APK 的 Kivy 入口（python-for-android 约定）
├── buildozer.spec         # buildozer 打包 APK 的配置
├── build.bat              # Windows 一键打包脚本（双击即出 dist\IRmAPI.exe）
├── IRmAPI.spec            # PyInstaller 打包配置
├── server.py              # FastAPI 网关（路由 / 认证 / 流式 / 控制台 API / 热重载）
├── console/
│   └── index.html         # 控制台（单文件，内联 CSS/JS，零外部依赖，五通道凭据页）
├── resources/
│   └── icon.ico           # exe 图标（IRm 艺术字）
├── gateway/
│   ├── config.py          # .env 配置（含 DeepSeek / Qwen / 一键登录字段）
│   ├── routing.py         # 模型名 -> 通道（deepseek->DeepSeek，qwen->千问）
│   ├── tokens.py          # 认证与账号池
│   ├── stats.py           # 运行统计（请求量 / 成功率 / 错误）
│   ├── sse.py             # SSE 编解码
│   ├── response.py        # OpenAI 响应构建
│   └── models.py          # 请求模型
├── providers/
│   ├── doubao_web.py      # 豆包网页版逆向通道（核心）
│   ├── doubao_ark.py      # 豆包火山方舟官方通道
│   ├── deepseek_web.py    # DeepSeek 网页版逆向 + 官方 API 兜底
│   ├── qwen_api.py        # 通义千问（阿里云百炼）官方通道
│   ├── qwen_web.py        # 通义千问网页版逆向通道（免 Key，浏览器 Cookie）
│   ├── openai_compat.py   # 通用 OpenAI 兼容通道
│   └── registry.py        # 通道注册表
└── tests/                 # 单元测试（47 项）
```
