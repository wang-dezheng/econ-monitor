# 卸载 Windows 计划任务
$ErrorActionPreference = "Stop"
$taskName = "EconDailyMonitor"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "没有找到计划任务 $taskName。" -ForegroundColor Yellow
    exit 0
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "已删除计划任务：$taskName" -ForegroundColor Green
