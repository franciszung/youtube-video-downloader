<#
.SYNOPSIS
    下载并准备本地运行时（Python / Node.js / yt-dlp），安装 Python 依赖。

.DESCRIPTION
    一键初始化脚本。重复运行是幂等的 —— 已存在的组件会跳过。

    组件:
      runtime/python/python.exe   Python 3.13 嵌入式发行版
      runtime/node/node.exe       Node.js 22（仅取 node.exe，够 yt-dlp 解 JS 签名用）
      yt-dlp.exe                  yt-dlp nightly

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1
#>

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Root "runtime"
$PyDir   = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"

$PythonVersion = "3.13.12"
$NodeVersion   = "v22.22.2"

# 注意: python.org 的 embeddable 发行版只在 /ftp/python/ 路径下,
#       /embed/<ver>/ 那个短链早已 404
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$NodeUrl   = "https://nodejs.org/dist/$NodeVersion/node-$NodeVersion-win-x64.zip"
$YtdlpUrl  = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp.exe"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"

# 老版本 Windows 默认不启用 TLS 1.2，HTTPS 下载会直接失败
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok   ($msg) { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Skip ($msg) { Write-Host "    [skip] $msg" -ForegroundColor DarkGray }

function Get-Archive($url, $destPath) {
    $ext = if ($url -match '\.zip$') { ".zip" } else { ".tmp" }
    $tmpFile = Join-Path $env:TEMP (([System.IO.Path]::GetRandomFileName()) + $ext)
    Write-Host "    下载 $url"

    $maxTry = 3
    for ($i = 1; $i -le $maxTry; $i++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $tmpFile -UseBasicParsing -TimeoutSec 600
            break
        } catch {
            Write-Host "    第 $i/$maxTry 次失败: $($_.Exception.Message)"
            if ($i -eq $maxTry) { throw }
            Start-Sleep -Seconds (3 * $i)
        }
    }

    # 防止把 404 的 HTML 错误页当成文件存下来
    $size = (Get-Item $tmpFile).Length
    if ($size -lt 1024) { throw "下载内容异常（仅 $size 字节），URL 可能已失效" }
    if ($ext -eq ".zip" -and $size -lt 100000) { throw "下载的压缩包异常（仅 $size 字节）" }

    Move-Item -Path $tmpFile -Destination $destPath -Force
    Write-Host "    下载完成 ($([math]::Round($size / 1MB, 1)) MB)"
    return $destPath
}

New-Item -ItemType Directory -Force -Path $Runtime, $NodeDir | Out-Null

# ---------------------------------------------------------------- Python
$PyExe = Join-Path $PyDir "python.exe"
if (Test-Path $PyExe) {
    Write-Skip "Python 已存在"
} else {
    Write-Step "下载 Python $PythonVersion (embeddable)"
    $zip = Join-Path $env:TEMP "python_embed.zip"
    Get-Archive $PythonUrl $zip | Out-Null
    Expand-Archive -Path $zip -DestinationPath $PyDir -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue

    # 嵌入式发行版默认禁用 site 模块，必须打开才能用 pip / site-packages
    $pth = Get-ChildItem -Path $PyDir -Filter "python*._pth" | Select-Object -First 1
    if ($pth) {
        $lines = Get-Content $pth.FullName
        $lines = $lines | ForEach-Object {
            if ($_ -match '^\s*#\s*import site') { "import site" }
            elseif ($_ -match '^\s*#\s*Lib\\site-packages') { "Lib\site-packages" }
            else { $_ }
        }
        if ($lines -notcontains "import site") { $lines += "import site" }
        if ($lines -notcontains "Lib\site-packages") { $lines += "Lib\site-packages" }
        Set-Content -Path $pth.FullName -Value $lines -Encoding ASCII
        Write-Ok "已启用 site 模块 (python313._pth)"
    }
    Write-Ok "Python 就绪: $PyExe"
}

# ---------------------------------------------------------------- Node.js
$NodeExe = Join-Path $NodeDir "node.exe"
if (Test-Path $NodeExe) {
    Write-Skip "Node.js 已存在"
} else {
    Write-Step "下载 Node.js $NodeVersion"
    $zip = Join-Path $env:TEMP "node_portable.zip"
    Get-Archive $NodeUrl $zip | Out-Null

    # 只取 node.exe —— npm / corepack / 文档对下载器没用，能省 100MB。
    # 直接走 System.IO.Compression 只解压单个条目，比 Expand-Archive 快一个数量级。
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $entry = $archive.Entries | Where-Object { $_.Name -eq "node.exe" } | Select-Object -First 1
        if (-not $entry) { throw "压缩包里找不到 node.exe" }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $NodeExe, $true)
    } finally {
        $archive.Dispose()
    }

    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Write-Ok "Node.js 就绪: $NodeExe"
}

# ---------------------------------------------------------------- yt-dlp
$YtdlpExe = Join-Path $Root "yt-dlp.exe"
if (Test-Path $YtdlpExe) {
    Write-Skip "yt-dlp.exe 已存在"
} else {
    Write-Step "下载 yt-dlp nightly"
    Get-Archive $YtdlpUrl $YtdlpExe | Out-Null
    Write-Ok "yt-dlp 就绪: $YtdlpExe"
}

# ---------------------------------------------------------------- pip 依赖
Write-Step "安装 Python 依赖"
$getPip = Join-Path $Root "get-pip.py"
if (-not (Test-Path $getPip)) {
    Get-Archive $GetPipUrl $getPip | Out-Null
}
& $PyExe $getPip --no-warn-script-location | Out-Null

$reqFile = Join-Path $Root "requirements.txt"
& $PyExe -m pip install --no-warn-script-location -r $reqFile
if ($LASTEXITCODE -ne 0) { throw "pip install 失败" }

# ---------------------------------------------------------------- 验证
Write-Step "验证"
& $PyExe -c "import flask, imageio_ffmpeg, websocket; print('    [OK] Python 依赖就绪')"
$ver = & $YtdlpExe --version 2>&1
Write-Host "    [OK] yt-dlp $ver"

Write-Host "`n===========================================" -ForegroundColor Green
Write-Host "  安装完成! 双击 start.bat 启动" -ForegroundColor Green
Write-Host "  http://127.0.0.1:5123" -ForegroundColor Green
Write-Host "===========================================`n" -ForegroundColor Green
