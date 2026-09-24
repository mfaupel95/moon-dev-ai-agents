@echo off
REM [MOON] Quick validation test script for Windows
REM Run this to verify everything is working

echo.
echo ======================================
echo [MOON] VALIDATION TEST SCRIPT
echo ======================================
echo.

echo [1] Environment Validation...
python src/utils/validate_env.py
if %ERRORLEVEL% NEQ 0 (
    echo [NO] Environment validation failed
    pause
    exit /b 1
)

echo.
echo [2] Ollama Health Check...
python -c "import sys; sys.path.insert(0, '.'); from src.utils.ollama_health import verify_ollama_ready; result = verify_ollama_ready(); print('RESULT: Ready' if result else 'RESULT: Not ready')"
if %ERRORLEVEL% NEQ 0 (
    echo [NO] Ollama health check failed
    pause
    exit /b 1
)

echo.
echo [3] GUI Startup Pre-flight Checks...
python startup.py
if %ERRORLEVEL% NEQ 0 (
    echo [NO] GUI startup failed
    pause
    exit /b 1
)

echo.
echo ======================================
echo [OK] All validations passed!
echo ======================================
echo.
pause
