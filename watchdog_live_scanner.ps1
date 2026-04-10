# Q-17 OS-level watchdog for live_pump_scanner
# 실행 방법: Windows Task Scheduler에 5분 간격으로 등록
# setup_os_watchdog.bat으로 자동 등록 가능

$workDir = "C:\Users\Home\Documents\ClaudeCode\morning-report"
$hbPath = Join-Path $workDir "live_scanner_heartbeat.txt"
$logPath = Join-Path $workDir "watchdog.log"
$pyExe = "python"
$pyArgs = @("-u", "live_pump_scanner.py", "--burst", "--watch")

$needRestart = $false
$reason = ""

# 1. heartbeat age check
if (-not (Test-Path $hbPath)) {
    $needRestart = $true
    $reason = "heartbeat file missing"
} else {
    try {
        $content = (Get-Content $hbPath -Raw).Trim()
        $hbTs = [long](($content -split '\|')[0])
        $nowTs = [long]([double]::Parse((Get-Date -UFormat %s)))
        $age = $nowTs - $hbTs
        if ($age -gt 180) {
            $needRestart = $true
            $reason = "heartbeat stale ${age}s"
        }
    } catch {
        $needRestart = $true
        $reason = "heartbeat parse error: $_"
    }
}

# 2. python process check
$pyProcs = Get-Process python -ErrorAction SilentlyContinue
if (-not $pyProcs) {
    $needRestart = $true
    if (-not $reason) { $reason = "no python process" }
}

# 3. restart if needed
if ($needRestart) {
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    # kill stale python first
    if ($pyProcs) {
        $pyProcs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    # start new
    Start-Process -FilePath $pyExe -ArgumentList $pyArgs -WorkingDirectory $workDir -WindowStyle Hidden
    "$timestamp [OS-WATCHDOG] restarted: $reason" | Out-File -Append -FilePath $logPath -Encoding utf8
}
