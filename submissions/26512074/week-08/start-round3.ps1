param([switch]$Publish, [switch]$ReplaceWeek07)
$ErrorActionPreference = 'Stop'
$week08Python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not $Publish) {
    & $week08Python -X utf8 (Join-Path $PSScriptRoot 'launch.py')
    exit $LASTEXITCODE
}
if (-not $ReplaceWeek07) { throw 'Publication reuses the week-07 identity. Explicit -ReplaceWeek07 is required.' }
$week08Preflight = (& $week08Python -X utf8 (Join-Path $PSScriptRoot 'launch.py')) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $week08Preflight.ready) { throw 'Preflight failed; previous deployment was left untouched.' }
$week08PidFile = Join-Path $PSScriptRoot '.market/operator.pid'
if (Test-Path -LiteralPath $week08PidFile) {
    $week08Existing = Get-Process -Id ([int](Get-Content -LiteralPath $week08PidFile)) -ErrorAction SilentlyContinue
    if ($week08Existing) { throw 'A week-08 operator may already be running. Verify it before starting another.' }
}
# Check the round BEFORE stopping the previous running assignment.
$week08Board = Invoke-RestMethod 'https://market.ourolabs.ai/api/board?round=3'
if ($week08Board.current -lt 3) { throw 'Round 3 is not open. Previous process was left running.' }
$week08OldPidFile = Join-Path $PSScriptRoot '../week-07/.market/operator.pid'
if (Test-Path -LiteralPath $week08OldPidFile) {
    $week08OldPid = [int](Get-Content -LiteralPath $week08OldPidFile)
    $week08OldProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$week08OldPid"
    if ($week08OldProcess) {
        if ($week08OldProcess.CommandLine -notmatch 'run_market\.py') { throw 'Saved PID no longer identifies the week-07 operator.' }
        $week08Started = (Get-Process -Id $week08OldPid).StartTime
        if ([Math]::Abs(($week08Started - (Get-Item -LiteralPath $week08OldPidFile).LastWriteTime).TotalSeconds) -gt 30) {
            throw 'PID-file timestamp mismatch; verify the old operator manually.'
        }
        taskkill /PID $week08OldPid /T /F | Out-Null
    }
}
$env:ROUND3_RELEASE_APPROVED = 'yes'
$week08Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Start-Process -FilePath $week08Python -ArgumentList @('-X', 'utf8', '-u', 'launch.py', '--publish') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot "logs/operator-$week08Stamp.out.log") -RedirectStandardError (Join-Path $PSScriptRoot "logs/operator-$week08Stamp.err.log")
Write-Output 'Explicit Round 3 handoff started. Check logs/market-kit.log for registration and settlement.'
