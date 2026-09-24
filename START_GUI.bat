@echo off
REM 🌙 Moon Dev GUI Launcher for Windows
REM One-click start with pre-flight checks

color 0B
title Moon Dev AI Agents - Startup

echo.
echo ╔════════════════════════════════════════════════════════════════════╗
echo ║                   🌙 MOON DEV AI AGENTS 🚀                         ║
echo ║                    Pre-flight Checks & Launch                      ║
echo ╚════════════════════════════════════════════════════════════════════╝
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found! Please install Python 3.10+
    echo 📥 Download from: https://python.org
    pause
    exit /b 1
)

echo ✅ Python detected
echo.

REM Run preflight checks
echo 🚀 Running pre-flight checks...
python startup.py
if %errorlevel% neq 0 (
    echo.
    echo ❌ Pre-flight checks failed
    pause
    exit /b 1
)

echo.
echo ✨ All systems go! Launching Moon Dev GUI...
echo.
pause

exit /b 0
