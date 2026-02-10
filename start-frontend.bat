@echo off
REM Start Proxi Frontend - Windows Batch Script
REM This opens two terminals for backend and frontend

echo.
echo ============================================================
echo   Proxi Frontend Startup
echo ============================================================
echo.
echo Starting Backend Server (Terminal 1)...
start cmd /k "uv run uvicorn proxi.server.app:app --reload --port 8000"

timeout /t 2 /nobreak

echo.
echo Starting Frontend Dev Server (Terminal 2)...
echo (This will auto-install npm packages if needed)
start cmd /k "cd frontend && npm install && npm run dev"

timeout /t 2 /nobreak

echo.
echo ============================================================
echo   Servers should be starting...
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:8000
echo ============================================================
echo.
echo Keep these windows open while developing.
echo Press Ctrl+C in either window to stop.
echo.
