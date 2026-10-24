@echo off
chcp 65001 >nul
cd /d "%~dp0app"
echo 正在启动计算机课程学习助手...
python server.py --open
if errorlevel 1 (
  echo.
  echo 启动失败。请确认已安装 Python 3.10 以上版本，并在命令行执行 python --version 查看。
  pause
)
