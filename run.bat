@echo off
setlocal enableextensions
rem NOTE: keep everything above the "AWFM_UTF8_READY" block below ASCII-only.
rem cmd.exe reads a batch file line by line using the console code page. This file is
rem UTF-8; when the console is still GBK(936), Chinese lines get split in the middle
rem and the tail of a line is executed as a command, printing a run of
rem "... is not recognized as an internal or external command" errors.
rem The bootstrap below switches the console to UTF-8 and re-runs this very file once,
rem so the second pass reads the whole file as UTF-8 and nothing is truncated.
rem Do NOT wrap the bootstrap in an if (...) block: %ERRORLEVEL% inside a parenthesised
rem block expands at PARSE time, which swallows the child's exit code (caught by the
rem v0.1.2 stage-6 integration tests). goto keeps the lines executed one by one.
if defined AWFM_UTF8_READY goto :awfm_utf8_ready
chcp 65001 >nul 2>nul
set "AWFM_UTF8_READY=1"
"%COMSPEC%" /c ""%~f0" %*"
exit /b %ERRORLEVEL%

:awfm_utf8_ready

rem AWFM 普通启动入口（Windows）—— 真正的逻辑都在 scripts\launcher.py
rem 用法：双击即可（不带参数 = 普通启动：查环境、起服务、就绪后自动开浏览器）。
rem 带参数时按高级用法透传：run.bat status / stop / restart / logs / check / help / menu。
rem 需要完整菜单和诊断请用 run-advanced.bat，两者行为一致，只是默认动作不同。
rem 退出码：0 成功 / 1 失败 / 2 用法错误 / 3 已经在跑或没在跑（未做改动）。
rem
rem 上面那段引导为什么存在：cmd.exe 按控制台代码页逐行读批处理；文件是 UTF-8
rem 而控制台还在 GBK(936) 时，含中文的行会被从中间截断，后半截被当成命令执行，
rem 报一串「不是内部或外部命令」。引导段先 chcp 65001，再用子进程重跑一次自己，
rem 第二遍整份文件都在 UTF-8 下读取，就不会被截断（引导段本身必须保持纯 ASCII）。
rem 引导段为什么不用 if (...) 括号块：括号块里的 %ERRORLEVEL% 在解析时就展开，会把
rem 子进程的退出码吃成 0；换成 goto 之后每一行都是逐行执行的。

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
