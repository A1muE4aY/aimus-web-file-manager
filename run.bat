@echo off
rem AWFM 统一入口（Windows）—— 真正的逻辑都在 scripts\launcher.py
rem 用法：run.bat [命令] [选项]；不带参数时显示交互菜单。
rem 退出码：0 成功 / 1 失败 / 2 用法错误 / 3 已经在跑或没在跑（未做改动）。
setlocal enableextensions
chcp 65001 >nul 2>nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 1) 切到本脚本所在目录：双击、快捷方式、从别的目录调用都能找对项目根。
cd /d "%~dp0"
if errorlevel 1 (
  echo [失败] 无法切换到脚本所在目录：%~dp0
  set "AWFM_CODE=1"
  goto :failed
)

rem 2) 找 Python：优先 py 启动器（能自己挑 3.x），其次 PATH 里的 python。
rem    具体版本检查交给启动器，它会给出「需要 3.10+，当前是 x.y.z」这样能看懂的话。
set "AWFM_PY="
where py >nul 2>nul && set "AWFM_PY=py -3"
if not defined AWFM_PY (
  where python >nul 2>nul && set "AWFM_PY=python"
)
if not defined AWFM_PY (
  echo [失败] 找不到 Python 解释器。
  echo        请安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
  echo        下载：https://www.python.org/downloads/windows/
  set "AWFM_CODE=1"
  goto :failed
)

rem 3) 转交启动器：参数原样转发（含带空格的路径）。分辨率检查、配置检查、
rem    端口检查、后台启动、PID 文件、停止与日志都在启动器里，批处理只负责找 Python。
%AWFM_PY% "scripts\launcher.py" %*
set "AWFM_CODE=%ERRORLEVEL%"
if not "%AWFM_CODE%"=="0" goto :failed
endlocal & exit /b 0

:failed
echo.
if "%AWFM_CODE%"=="3" (
  echo [提示] 状态和这次请求不一致，没有改动任何东西。
  echo [提示] 查看状态：run.bat status      启动服务：run.bat start
  endlocal & exit /b 3
)
if not "%AWFM_CODE%"=="" echo [提示] 本次没有成功完成，退出码 %AWFM_CODE%。
echo [提示] 查看帮助：run.bat help      启动前自检：run.bat check
rem 双击运行时窗口会一闪而过，所以出错后停一下等你看完；
rem 自动化脚本里请先 set AWFM_NO_PAUSE=1 跳过这个等待。
if not defined AWFM_NO_PAUSE pause
endlocal & exit /b %AWFM_CODE%
