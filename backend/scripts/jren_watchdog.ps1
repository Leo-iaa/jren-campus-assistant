# JREN Campus Assistant 服务看门狗
# 若 28070 端口无监听，则用仓库 venv 启动 uvicorn 后端。
# 幂等：服务已在运行则直接退出，不会重复拉起。
$ErrorActionPreference = "SilentlyContinue"

$PORT = 28070
$VENV_PY = "C:\Users\LEO\jren-campus-assistant\.venv\Scripts\python.exe"
$WDIR    = "C:\Users\LEO\jren-campus-assistant"
$LOG     = "C:\Users\LEO\jren-campus-assistant\backend\data\server.log"

# 通过 netstat 判断是否已在监听（比 Get-NetTCPConnection 更稳，无需管理员）
$listening = netstat -ano 2>$null | Select-String ":$PORT " | Select-String "LISTENING"
if ($listening) {
    exit 0
}

# 否则启动服务（独立进程，脱离调度器会话，可长期存活）
# -UseNewEnvironment 规避 PowerShell 的 Path/PATH 环境键重复 bug
Start-Process -FilePath $VENV_PY `
    -ArgumentList "-m","uvicorn","backend.main:app","--host","0.0.0.0","--port","$PORT" `
    -WorkingDirectory $WDIR `
    -RedirectStandardOutput $LOG `
    -WindowStyle Hidden `
    -UseNewEnvironment

exit 0
