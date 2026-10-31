@echo off
if not "%~1"=="--hidden" (
  wscript.exe "%~dp0launch_hidden.vbs" "%~f0"
  exit /b
)
@echo off
title 计算机课程学习助手

echo ==============================================
echo   计算机课程学习助手 - 本地启动器
echo ==============================================
echo.

cd /d "%~dp0app"
if not exist "server.py" (
  echo [错误] 找不到 app\server.py
  echo 请把本文件放在 AIassistant 目录下再运行。
  if not "%~1"=="--hidden" pause
  exit /b 1
)

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py -3" )
if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PY (
  if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
)

if not defined PY (
  echo [错误] 没有找到 Python。
  echo 请先安装 Python 3.10 或更高版本： https://www.python.org/downloads/
  echo 安装时记得勾选 Add python.exe to PATH
  if not "%~1"=="--hidden" pause
  exit /b 1
)

echo 使用 Python: %PY%
echo 正在启动，稍后会自动打开浏览器
echo 访问地址: http://127.0.0.1:8737
echo.
echo 提示：本窗口可以最小化，也可以直接关掉浏览器页面。
echo       关掉最后一个页面约 25 秒后，服务会自动停止，本窗口随之退出。
echo       想立刻停止：本窗口按 Ctrl+C，或直接关闭本窗口。
echo ----------------------------------------------

rem 本机账号认证服务（单独的最小化窗口；已在运行时新窗口会因端口占用自行退出）
start "" /b %PY% "%~dp0auth_server\auth_server.py"

%PY% server.py --open --exit-on-close

echo.
echo 服务已停止。
if not "%~1"=="--hidden" pause
