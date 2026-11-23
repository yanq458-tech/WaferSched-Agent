[CmdletBinding()]
param(
    [ValidateRange(1, 86400)] [int] $Seconds = 180,
    [ValidateRange(0, 3600)] [int] $Slice = 0,
    [string] $Output = 'results/local/boundary-campaign-009'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$oldPythonPath = $env:PYTHONPATH
Push-Location -LiteralPath $repoRoot
try {
    $env:PYTHONPATH = (Resolve-Path src).Path
    $remaining = [double]$Seconds
    $checkpoint = Join-Path $Output 'state.json'
    $summary = Join-Path $Output 'summary.json'
    while ($remaining -gt 0.1) {
        $allocation = $Slice
        $epoch = $remaining
        if ($Slice -eq 0) {
            $allocation = 5
            if (Test-Path -LiteralPath $checkpoint) {
                $state = Get-Content -Raw -LiteralPath $checkpoint | ConvertFrom-Json
                $recent = @($state.history | Where-Object tool -eq 'maximize_repair' | Select-Object -Last 8)
                if ($recent.Count -ge 4 -and @($recent | Where-Object status -ne 'UNKNOWN').Count -eq 0) {
                    $typical = ($recent | Measure-Object -Property solver_seconds -Average).Average
                    $allocation = [Math]::Min(40,[Math]::Max(10,[Math]::Ceiling(2*$typical+2)))
                }
            }
            $epoch = [Math]::Min($remaining,[Math]::Max(90,6*$allocation))
        }
        $epochText = $epoch.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
        Write-Host "Offline search: epoch $epochText s, slice $allocation s"
        & '.\.venv-langgraph\Scripts\python.exe' -m wafer_sched.recovery.feedback.boundary_campaign --seconds $epochText --slice $allocation --out $Output
        if ($LASTEXITCODE -ne 0) { throw "Recovery campaign exited with code $LASTEXITCODE" }
        $result = Get-Content -Raw -LiteralPath $summary | ConvertFrom-Json
        if ($result.stop -eq 'all_proved') { break }
        $remaining -= $result.elapsed_search_seconds
    }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}

