@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ===========================================
echo   YouTube 视频下载器
echo   本地网页: http://127.0.0.1:5123
echo ===========================================
echo.

set PYTHON=runtime\python\python.exe

if not exist "%PYTHON%" (
    echo [错误] 找不到 %PYTHON%
    echo 请先双击 setup.bat 完成初始化安装。
    pause
    exit /b 1
)

if not exist "runtime\node\node.exe" (
    echo [错误] 找不到 runtime\node\node.exe
    echo 请先双击 setup.bat 完成初始化安装。
    pause
    exit /b 1
)

if not exist "yt-dlp.exe" (
    echo [错误] 找不到 yt-dlp.exe
    echo 请先双击 setup.bat 完成初始化安装。
    pause
    exit /b 1
)

"%PYTHON%" -c "import flask" 2>nul
if errorlevel 1 (
    echo [错误] Python 依赖未安装,请先运行 setup.bat
    pause
    exit /b 1
)

echo [警告] 不要直接双击 yt-dlp.exe,否则会导致文件损坏!
echo.

"%PYTHON%" app.py

pause
