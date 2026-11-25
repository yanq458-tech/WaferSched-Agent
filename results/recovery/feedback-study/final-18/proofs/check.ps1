param([string]$Project, [string]$Python='python', [int]$Workers=2, [int]$Seconds=1800, [switch]$RerunCuts, [string]$Cache)
$ErrorActionPreference='Stop'
if (-not $Project) { $Project=(git -C $PSScriptRoot rev-parse --show-toplevel) }
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$bin=Join-Path ([IO.Path]::GetTempPath()) ('wafersched-proof-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $bin | Out-Null
if (-not $Cache) { $Cache=Join-Path $bin 'cache' }
$files=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'native-sources.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($item in $files.PSObject.Properties) {
    $source=Join-Path $PSScriptRoot $item.Value.file
    if ((Get-FileHash -LiteralPath $source).Hash -ne $item.Value.sha256) { throw "Hash mismatch: $source" }
    $out=Join-Path $bin ($item.Name+'.exe')
    & $compiler /nologo /optimize+ /unsafe "/out:$out" $source
    if ($LASTEXITCODE -ne 0) { throw "Compile failed: $source" }
}
$env:PYTHONPATH=Join-Path $Project 'src'
& $Python (Join-Path (Split-Path $PSScriptRoot) 'verify_results.py')
if ($LASTEXITCODE -ne 0) { throw 'Frozen input or replay check failed' }
& $Python (Join-Path $PSScriptRoot 'verify.py') 16-h-1 16-h-2 20-h-3 24-h-1 --repo $Project --engines $bin --workers $Workers --seconds $Seconds
if ($LASTEXITCODE -ne 0) { throw 'Exhaustive route verification failed' }
$extra=@()
if ($RerunCuts) { $extra+='--rerun' }
& $Python (Join-Path $PSScriptRoot 'check_hard.py') 24-h-2 24-h-3 --repo $Project --engines $bin --workers $Workers --seconds $Seconds --cache $Cache @extra
if ($LASTEXITCODE -ne 0) { throw 'Terminal coverage or cut verification failed' }
