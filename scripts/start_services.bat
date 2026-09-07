@echo off
setlocal
set "PROJECT_DIR=E:\mye盘项目\jianli project\customer-service-ai-agent"

echo ============================================
echo   Aegis-CS 智能客服工作台 - 启动器
echo   项目: %PROJECT_DIR%
echo ============================================

rem 单服务架构：LangGraph 图已内嵌 Flask，无需 2024 编排服务

netstat -ano | findstr /C:":5000 " | findstr /C:"LISTENING" >nul
if errorlevel 1 (
    echo [1/2] 启动 Web 服务（内嵌 AI 编排）- 端口 5000 ...
    start "Aegis-CS Web 5000" cmd /k "cd /d "%PROJECT_DIR%" && ".venv\Scripts\python.exe" web_app.py"
) else (
    echo [1/2] Web 服务已在运行，跳过。
)

echo [2/2] 等待服务就绪后打开浏览器 ...
timeout /t 10 /nobreak >nul
start "" "http://localhost:5000/"

echo.
echo 完成：客户入口 http://localhost:5000/chat ，坐席入口 /agent/login
echo 停止服务请关闭服务窗口或在其中按 Ctrl+C。
timeout /t 8 >nul
endlocal
