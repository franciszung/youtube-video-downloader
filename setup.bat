@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ===========================================
echo   YouTube 下载器 - 初始化安装
echo   将下载 Python / Node.js / yt-dlp 并安装依赖
echo ===========================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo [错误] 安装失败,请检查上方输出
    pause
    exit /b 1
)

echo.
echo 现在可以双击 start.bat 启动工具。
pause
