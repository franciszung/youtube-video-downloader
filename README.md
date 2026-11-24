# YouTube 视频下载器（本地网页版）

一个跑在你自己电脑上的 YouTube 视频下载工具。Flask 提供本地网页界面，底层调用
[yt-dlp](https://github.com/yt-dlp/yt-dlp)，支持**自由选择清晰度**、批量下载、
关键帧抽取和自动清理临时文件。

**不需要安装 Python 或 Node.js** —— `setup.bat` 会把运行时下载到本地 `runtime/`
目录，整个工具可以随时打包带走。

> ⚠️ 仅供个人学习和合法用途。请遵守 YouTube 服务条款与相关版权法规，不要用于
> 绕过付费墙或 DRM。

---

## 特性

| | |
|---|---|
| 🎯 **清晰度可选** | 最高 2160p / 1440p / 1080p / 720p / 480p / 360p，也可选「最高可用」 |
| 🔁 **自动降级** | 目标清晰度不可用时自动回退到下一档，而不是直接失败 |
| 🧹 **自动清理** | 下载完成后自动删除 `.part` / `.ytdl` / 分片临时文件，目录保持干净 |
| 🎞️ **关键帧抽取** | 可选从视频中提取 8 张关键帧 JPG，方便做封面或分镜参考 |
| 🔐 **Cookies 支持** | 通过 Edge DevTools Protocol 导出登录态，支持 age-restricted 视频 |
| 🧩 **纯本地** | 只监听 `127.0.0.1`，视频不上传到任何第三方服务器 |
| 🪟 **免安装** | Python / Node.js / yt-dlp 全部由 `setup.bat` 自动准备 |

---

## 快速开始

### Windows

1. **下载或克隆本仓库**
   ```bash
   git clone https://github.com/franciszung/youtube-video-downloader.git
   cd youtube-video-downloader
   ```
   （也可以直接下载 ZIP 解压，路径尽量避免中文和空格）

2. **双击 `setup.bat`**
   自动完成：
   - 下载 Python 3.13 嵌入式发行版 → `runtime/python/`
   - 下载 Node.js 22（只取 `node.exe`）→ `runtime/node/`
   - 下载 yt-dlp nightly → `yt-dlp.exe`
   - 引导 pip 并安装 Python 依赖

   首次运行约需 3–5 分钟（下载约 120MB），之后重复运行会自动跳过已完成的步骤。

3. **双击 `start.bat`**
   浏览器打开 <http://127.0.0.1:5123>

4. 粘贴 YouTube 链接 → 选清晰度 → 开始下载

### 或者：直接下便携包

在 [Releases](https://github.com/franciszung/youtube-video-downloader/releases) 页面下载
`youtube-video-downloader-*.zip`，解压即用 —— 运行时已经打包在里面，不用跑 `setup.bat`。

### macOS / Linux

`setup.ps1` 依赖 PowerShell，跨平台支持有限。手动准备运行时：

```bash
# Python 3.11+ 与依赖
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# yt-dlp
curl -L https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp \
  -o yt-dlp && chmod +x yt-dlp

# Node.js（解 JS 签名必需）
# https://nodejs.org/dist/

python app.py
```

---

## 使用说明

### 下载流程

1. 在输入框粘贴视频链接（支持单条链接或频道/播放列表链接）
2. 选择目标清晰度
3. 可选：勾选「提取关键帧」
4. 点「开始下载」，页面实时显示进度日志

下载产物在 `downloads/` 目录，关键帧在 `thumbnails/`。

### 清晰度说明

- 选了 **1080p** 但视频本身只有 720p？会自动降级到 720p，日志里会写明
- 选了 **最高可用** 时由 yt-dlp 自行决定
- 需要登录才能拿到的清晰度（1080p+）需要配置 cookies，见下文

### 导出 YouTube Cookies（下载 age-restricted / 会员视频）

Chromium 130+ 启用了 App-Bound Encryption，`yt-dlp --cookies-from-browser edge`
读不到 cookie 了。本项目用 Edge DevTools Protocol 绕过：

1. **完全关闭所有 Edge 窗口**
2. 用调试端口启动 Edge：
   ```bash
   "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" \
     --remote-debugging-port=9222 \
     --user-data-dir=D:\edge_temp_profile
   ```
3. 在打开的 Edge 里访问 youtube.com 并**登录**
4. 保持 Edge 窗口开着，执行：
   ```bash
   runtime\python\python.exe export_cookies.py
   ```
   `cookies.txt` 会生成在仓库根目录
5. 在网页「设置」里勾选 **使用 cookies**（`cookies_source` 填 `cookies.txt`）

> 🔒 `cookies.txt` 等同于你的账号凭证，**不要提交到 Git**（已在 `.gitignore` 中排除），
> 也不要分享给别人。

---

## 设置项

点击网页右上角「设置」：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| HTTP 代理 | `http://127.0.0.1:7892` | 本地代理端口，按你的实际情况改；不需要代理就关掉「使用代理」 |
| Node.js 路径 | `runtime/node/node.exe` | 相对路径基于工具根目录，也可填绝对路径 |
| 下载目录 | `downloads` | 相对路径基于工具根目录，也可填绝对路径 |
| Cookies 来源 | `cookies.txt` | 填 `cookies.txt` 用本地文件；填 `edge`/`chrome`/`firefox` 等让 yt-dlp 直接读浏览器 |
| 使用 Node.js runtime | 开 | 解 YouTube 的 JS 签名，**关掉会大量 403**，别关 |
| 默认清晰度 | `1080p` | — |

配置文件存在 `config.json`，删掉会恢复默认值。

---

## 常见问题

**网页打不开（127.0.0.1:5123）**
- 确认 `start.bat` 的黑色窗口没被关掉（关掉 = 服务停止）
- 试试 <http://localhost:5123>
- 检查端口是否被占用：`netstat -ano | findstr :5123`

**提示 `runtime\python\python.exe` 不存在**
- 没跑 `setup.bat`，或者只克隆了源码没跑初始化

**下载报 403 Forbidden**
- 检查代理是否启动（默认 `127.0.0.1:7892`）
- 确认「使用 Node.js runtime」是勾上的
- yt-dlp 版本太旧 → 删掉 `yt-dlp.exe` 重跑 `setup.bat` 拉最新 nightly

**画质选项只有 360p / 240p，选不了 1080p**
- 签名求解失败，YouTube 那边把高画质格式藏起来了
- 排查顺序：① 确认 Node.js runtime 路径存在；② 清掉 `NODE_OPTIONS` 环境变量；
  ③ 删掉 `yt-dlp.exe` 重跑 `setup.bat` 拿最新 nightly
- 用命令行自查：
  ```bash
  yt-dlp.exe --js-runtimes node:<node路径> -F <视频链接>
  ```
  正常会列出 `1920x1080` / `2560x1440` 等格式

**页面报 `'NoneType' object has no attribute 'splitlines'`**
- 子进程输出解码失败。多半是系统 locale 不是 UTF-8（中文 Windows 默认 GBK）
- 确认用的是最新代码：`subprocess` 调用都应带 `encoding="utf-8", errors="replace"`

**age-restricted 视频下载失败**
- 需要配置 cookies，见上文「导出 YouTube Cookies」

**提示 `yt-dlp.exe` 损坏**
- 直接双击 `yt-dlp.exe` 会损坏它（Windows 下 PE 文件被当作文本打开）
- 正确用法只有两个：双击 `start.bat`，或命令行 `runtime\python\python.exe app.py`
- 修复：删掉重新 `setup.bat`

**下载完目录里还有 `.part` / `.ytdl` / `.f*.mp4` 残留**
- 正常情况下会自动清理。若手工跑过 yt-dlp，网页上有「清理垃圾文件」按钮可手动清

**Python 依赖装不上**
- `setup.bat` 需要联网拉 pip 包
- 手动执行：`runtime\python\python.exe -m pip install -r requirements.txt`

---

## 项目结构

```
youtube-video-downloader/
├── app.py                 # Flask 后端（所有路径相对工具根目录解析）
├── export_cookies.py      # Edge CDP cookies 导出脚本
├── setup.ps1              # 运行时下载 + 依赖安装（幂等）
├── setup.bat              # setup.ps1 的双击入口
├── start.bat              # 启动服务
├── requirements.txt       # Python 依赖
├── templates/index.html   # 网页界面
├── static/                # 前端 JS / CSS
├── runtime/               # ← setup.bat 自动下载，不进版本库
│   ├── python/            #   Python 3.13 嵌入式
│   └── node/              #   Node.js 22
├── yt-dlp.exe             # ← setup.bat 自动下载，不进版本库
├── downloads/             # 下载产物
└── thumbnails/            # 关键帧
```

---

## 实现要点

- **路径全部相对工具根目录**：`resolve_path()` 把配置里的相对路径按 `BASE_DIR`
  解析，因此整个文件夹可以随便挪位置，不会有写死路径的问题
- **DASH 合并**：yt-dlp 下载的是音视频分片，用 ffmpeg (`-c copy`，不重编码)
  合并成单个 mp4
- **JS 签名**：通过 `--js-runtimes node:<path>` 让 yt-dlp 用 Node.js 执行
  YouTube 的签名脚本，绕开纯 Python 解析不了的 challenge
- **必须加 `--no-js-runtimes`**：yt-dlp 默认启用 deno 且优先级高于 node。
  用户机器上装了 deno 时会盖掉自带的 node，导致签名求解失败。
  `--no-js-runtimes` 必须排在 `--js-runtimes` 之前才能清掉默认值
- **清掉 `NODE_OPTIONS`**：某些沙箱 / IDE / 企业终端策略会通过 `NODE_OPTIONS`
  注入自己的 shim。yt-dlp 调 node 时带 `--experimental-permission`，权限模型会
  阻止 shim 读取自身文件，报 `Access to this API has been restricted`，
  结果是 1080p+ 格式全部消失。启动子进程前把这个变量删掉最稳妥
- **子进程统一 `encoding="utf-8"`**：`text=True` 默认用系统 locale 解码。
  中文 Windows 是 GBK，yt-dlp 输出里只要有非 ASCII 字符就会
  `UnicodeDecodeError`，进而 `stdout` 变 `None`、`.splitlines()` 崩溃
- **清理四级回退**：`os.remove` → `pathlib.unlink` → PowerShell `Remove-Item`
  → `Get-Item | Remove-Item`，兼容各种沙箱/权限环境
- **Netscape cookies 格式**：`initial_dot` 字段必须与 domain 的 `.` 前缀一致，
  否则 Python cookiejar 会抛 `AssertionError`

---

## License

[MIT](LICENSE)

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) —— 核心下载引擎
- [Flask](https://flask.palletsprojects.com/) —— 本地 web 框架
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) —— ffmpeg 分发
- [moviepy](https://github.com/Zulko/moviepy) —— 视频元数据解析
