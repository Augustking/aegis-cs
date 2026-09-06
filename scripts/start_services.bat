@echo off
setlocal
set "PROJECT_DIR=E:\mye盘项目\jianli project\customer-service-ai-agent"

echo ============================================
echo   智能客服工作台 - 启动器
echo   项目: %PROJECT_DIR%
echo ============================================

netstat -ano | findstr /C:":2024 " | findstr /C:"LISTENING" >nul
if errorlevel 1 (
    echo [1/3] 启动 LangGraph 编排服务 - 端口 2024 ...
    start "LangGraph Service 2024" cmd /k "cd /d "%PROJECT_DIR%" && ".venv\Scripts\langgraph.exe" dev --no-browser --port 2024"
) else (
    echo [1/3] LangGraph 已在运行，跳过。
)

netstat -ano | findstr /C:":5000 " | findstr /C:"LISTENING" >nul
if errorlevel 1 (
    echo [2/3] 启动 Flask Web 服务 - 端口 5000 ...
    start "Customer Service Web 5000" cmd /k "cd /d "%PROJECT_DIR%" && ".venv\Scripts\python.exe" web_app.py"
) else (
    echo [2/3] Flask 已在运行，跳过。
)

echo [3/3] 等待服务就绪后打开浏览器 ...
timeout /t 12 /nobreak >nul
start "" "http://localhost:5000/"

echo.
echo 完成：服务窗口已就绪。停止服务请关闭对应窗口或在其中按 Ctrl+C。
timeout /t 8 >nul
endlocal
