$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$resumeMutex = New-Object System.Threading.Mutex($false, 'Local\AX-Round3-26512074-Resume')
if (-not $resumeMutex.WaitOne(0)) { exit 0 }
try {
$python = Join-Path $taskRoot '.venv\Scripts\python.exe'
$running = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' })
# The kit remains the sole registration/tunnel owner. Restore existing keys only.
if (-not ($running | Where-Object { $_.CommandLine -match 'launch_round3.py --publish' })) {
    foreach ($required in @('shop_key.pem','buyer_key.pem','.market\owner-code.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskRoot $required))) { throw "Missing existing state: $required" }
    }
    Start-Process -FilePath $python -ArgumentList '-X utf8 -u launch_round3.py --publish' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput 'logs\resume-market.out.log' -RedirectStandardError 'logs\resume-market.err.log'
}
if (-not ($running | Where-Object { $_.CommandLine -match 'optimizer.py' })) {
    Start-Process -FilePath $python -ArgumentList '-X utf8 -u optimizer.py' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput 'logs\optimizer.out.log' -RedirectStandardError 'logs\optimizer.err.log'
}
} finally { $resumeMutex.ReleaseMutex(); $resumeMutex.Dispose() }
