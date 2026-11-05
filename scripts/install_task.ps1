# 注册 Windows 计划任务：每天自动生成经济观察报告
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time "08:30","18:30" -OpenReport

param(
    [string[]]$Time = @("08:30"),
    [switch]$OpenReport
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$taskName = "EconDailyMonitor"

$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $pythonw = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $pythonw) {
    Write-Host "没有找到 pythonw.exe / python.exe，请先安装 Python 并加入 PATH。" -ForegroundColor Red
    exit 1
}

$arguments = "`"$root\run.py`""
if ($OpenReport) {
    $arguments += " --open"
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $root
$triggers = @()
foreach ($t in $Time) {
    $triggers += New-ScheduledTaskTrigger -Daily -At $t
}
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

$userId = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description "每日经济观察：抓取宏观数据与新闻，生成 HTML/Markdown 报告" `
        -Force | Out-Null
} catch {
    Write-Host "注册失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "可以尝试用管理员权限打开 PowerShell 后重试；或改用任务计划程序手动创建。" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "已注册计划任务：$taskName" -ForegroundColor Green
Write-Host "运行时间：$($Time -join ' / ')（每天）"
Write-Host "Python：$pythonw"
Write-Host "工作目录：$root"
Write-Host "报告目录：$root\reports"
Write-Host ""
Write-Host "查看任务：Get-ScheduledTask -TaskName $taskName"
Write-Host "立即测试：Start-ScheduledTask -TaskName $taskName"
Write-Host "卸载任务：powershell -ExecutionPolicy Bypass -File scripts\uninstall_task.ps1"
