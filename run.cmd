@echo off
rem Launch GUI-of-Edge-TTS.  No packaging, no gates -- just start it.
rem
rem Double-click this file, or from a terminal:
rem     run.cmd --settings
rem     run.cmd --selftest
rem
rem NOTE: keep this file ASCII-only.  cmd.exe reads .cmd files in the OEM code
rem page, so UTF-8 text here gets mis-parsed as commands and the script breaks.

setlocal
set "REPO=%~dp0"
set "ENTRY=%REPO%src\GUI-of-Edge-TTS.py"

set "PY="
if exist "%REPO%edge-tts-env\python.exe" set "PY=%REPO%edge-tts-env\python.exe"
if not defined PY if exist "D:\Coding\GUI-of-Edge-TTS\etts-dev\python.exe" set "PY=D:\Coding\GUI-of-Edge-TTS\etts-dev\python.exe"
if not defined PY if exist "D:\Coding\GUI-of-Edge-TTS\edge-tts-env\python.exe" set "PY=D:\Coding\GUI-of-Edge-TTS\edge-tts-env\python.exe"

if not defined PY (
    echo No usable Python found.  This project needs an interpreter with
    echo edge-tts and tkinter installed.
    pause
    exit /b 1
)

echo Running from source: %PY%
"%PY%" -X utf8 "%ENTRY%" %*
exit /b %ERRORLEVEL%
