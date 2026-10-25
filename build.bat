@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem ============================================================
rem  电力公司 打包脚本
rem     build.bat            生成 dist\电力公司\ （推荐：启动快、杀软误报少）
rem     build.bat onefile    生成 dist\电力公司.exe（单文件，首次启动慢）
rem
rem  会自动寻找可用的 Python（跳过 Windows 应用商店的占位程序），
rem  也可以用 set PYTHON=C:\path\to\python.exe 指定。
rem ============================================================

set "MODE=--onedir"
if /i "%~1"=="onefile" set "MODE=--onefile"

rem ---------- 1. 找 Python ----------
set "PY="
if defined PYTHON set "PY=%PYTHON%"

if not defined PY (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        set "CAND=%%I"
        echo !CAND! | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if not defined PY (
                "!CAND!" -c "import tkinter" >nul 2>nul
                if not errorlevel 1 set "PY=!CAND!"
            )
        )
    )
)
if not defined PY (
    for /f "delims=" %%I in ('where py 2^>nul') do (
        set "CAND=%%I"
        echo !CAND! | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if not defined PY (
                "!CAND!" -3 -c "import tkinter" >nul 2>nul
                if not errorlevel 1 set "PY=!CAND!"
            )
        )
    )
)
if not defined PY (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "C:\Python3*" "%ProgramFiles%\Python3*") do (
        if exist "%%~fD\python.exe" if not defined PY set "PY=%%~fD\python.exe"
    )
)
if not defined PY (
    for /d %%D in ("%USERPROFILE%\.dsh\dsh-runtimes\*\dependencies\python") do (
        if exist "%%~fD\python.exe" if not defined PY set "PY=%%~fD\python.exe"
    )
)

if not defined PY goto :nopython

"%PY%" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [错误] 这个 Python 没有 tkinter，无法打包图形版：
    echo        %PY%
    echo        请安装官方 python.org 版本，或用 set PYTHON=... 指定别的解释器。
    exit /b 1
)

set "PYTHONPATH=%CD%\build_tools"
echo [1/5] 使用 Python: %PY%
"%PY%" -c "import sys;print('  版本', sys.version.split()[0], sys.executable)"

rem ---------- 2. PyInstaller ----------
if not exist "%CD%\build_tools\PyInstaller" (
    echo [2/5] 抓取 PyInstaller ...
    "%PY%" tools\fetch_pyinstaller.py || goto :fail
) else (
    echo [2/5] PyInstaller 已就绪
)

rem ---------- 3. 图标 ----------
if not exist "%CD%\assets\app.ico" (
    echo [3/5] 生成图标 ...
    "%PY%" tools\make_icon.py || goto :fail
) else (
    echo [3/5] 图标已就绪
)

rem ---------- 4. 源码自检 ----------
echo [4/5] 源码自检 ...
"%PY%" main.py --selftest || goto :fail

rem ---------- 5. 打包 ----------
echo [5/5] 打包中（%MODE%）...
"%PY%" -m PyInstaller --noconfirm --clean %MODE% --windowed ^
    --name "电力公司" ^
    --icon "%CD%\assets\app.ico" ^
    --distpath dist --workpath build --specpath build ^
    --log-level WARN main.py
if errorlevel 1 goto :fail

echo [6/6] 生成安全告知 ...
"%PY%" tools\make_notice.py

echo.
if /i "%~1"=="onefile" (
    echo 完成：dist\电力公司.exe
    echo 自检：dist\电力公司.exe --selftest
) else (
    echo 完成：dist\电力公司\电力公司.exe
    echo 自检：dist\电力公司\电力公司.exe --selftest
    echo 分发：把 dist\电力公司 整个文件夹压成 zip 发出去即可。
)
goto :eof

:nopython
echo.
echo [错误] 没找到可用的 Python（需要 3.10+ 且带 tkinter）。
echo   1. 安装官方版本：https://www.python.org/downloads/windows/
echo   2. 或者手动指定：set PYTHON=D:\Python312\python.exe  然后重新运行 build.bat
exit /b 1

:fail
echo.
echo 打包失败，请检查上面的报错。
exit /b 1
