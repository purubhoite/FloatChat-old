@echo off
echo ===================================================
echo   FloatChat System Startup Script
echo ===================================================

REM ----------------------------------------------------
REM Configuration
REM ----------------------------------------------------
set LLM_BACKEND=local_ollama
set OLLAMA_MODEL=llama3-instruct
set OLLAMA_URL=http://localhost:11434/api/generate

REM If you want to use Gemini instead, uncomment below:
REM set LLM_BACKEND=gemini
REM set GEMINI_API_KEY=your_key_here

echo.
echo Configuration:
echo   LLM Backend: %LLM_BACKEND%
echo   Ollama Model: %OLLAMA_MODEL%
echo.

REM ----------------------------------------------------
REM 1. Start Ollama (if not already running)
REM ----------------------------------------------------
echo [1/3] Ensuring Ollama is running...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Ollama is already running.
) else (
    echo Starting Ollama...
    start /B ollama serve
    timeout /t 5
)

REM ----------------------------------------------------
REM 2. Start Backend
REM ----------------------------------------------------
echo.
echo [2/3] Starting Backend API (Port 8000)...
start "FloatChat Backend" uvicorn backend.api:app --reload --port 8000
timeout /t 2

REM ----------------------------------------------------
REM 3. Start Frontend
REM ----------------------------------------------------
echo.
echo [3/3] Starting Frontend (Port 8050)...
start "FloatChat Frontend" python frontend/app.py

echo.
echo ===================================================
echo System launched!
echo.
echo Frontend should open at: http://127.0.0.1:8050
echo.
echo NOTE: If you see "Connection refused" in the frontend,
echo check the "FloatChat Backend" window for errors.
echo ===================================================
pause
