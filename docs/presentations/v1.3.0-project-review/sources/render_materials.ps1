param([string]$Root = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath($Root)
$pptx = Join-Path $Root 'WaferSched-Agent_v1.3.0_研究汇报.pptx'
$docx = Join-Path $Root 'WaferSched-Agent_v1.3.0_逐页讲稿.docx'
$renderDir = Join-Path $Root ('build/render-' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
$slidesDir = Join-Path $renderDir 'slides'
$wordDir = Join-Path $renderDir 'word'
New-Item -ItemType Directory -Force -Path $slidesDir,$wordDir | Out-Null
$report = [ordered]@{ renderer = 'Native Microsoft PowerPoint and Word via COM'; slides = @(); text_fit_candidates = @(); word_pages = 0 }
$ppt = New-Object -ComObject PowerPoint.Application
$ppt.DisplayAlerts = 1
$deck = $null
try {
    $deck = $ppt.Presentations.Open($pptx, -1, 0, 0)
    for ($i=1; $i -le $deck.Slides.Count; $i++) {
        $slide = $deck.Slides.Item($i)
        $slide.Export((Join-Path $slidesDir ('slide-{0:D2}.png' -f $i)), 'PNG', 1280, 720)
        $row = [ordered]@{ page=$i; shapes=$slide.Shapes.Count; charts=0; tables=0 }
        foreach ($s in $slide.Shapes) {
            if ($s.HasChart -eq -1) { $row.charts++ }
            if ($s.HasTable -eq -1) { $row.tables++ }
            if ($s.HasTextFrame -eq -1 -and $s.TextFrame2.HasText -eq -1) {
                $range = $s.TextFrame2.TextRange
                if ($range.BoundHeight -gt ($s.Height + 3) -or $range.BoundWidth -gt ($s.Width + 3)) {
                    $report.text_fit_candidates += [ordered]@{slide=$i; text=$range.Text; shape_width=$s.Width; shape_height=$s.Height; bound_width=$range.BoundWidth; bound_height=$range.BoundHeight}
                }
            }
        }
        $report.slides += $row
    }

} finally {
    if ($null -ne $deck) {$deck.Close()}
    $ppt.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$document = $null
try {
    $document=$word.Documents.Open($docx,$false,$true,$false)
    $document.Repaginate()
    $report.word_pages=$document.ComputeStatistics(2)
    $document.ExportAsFixedFormat((Join-Path $wordDir '讲稿渲染.pdf'),17)
} finally {
    if ($null -ne $document) {$document.Close(0)}
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $renderDir 'native-office-inspection.json') -Encoding utf8
$runtime = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime'
$poppler = Join-Path $runtime 'dependencies/native/poppler/Library/bin/pdftoppm.exe'
if (-not (Test-Path -LiteralPath $poppler)) {throw 'Bundled Poppler was not found'}
& $poppler -png -scale-to 1500 (Join-Path $wordDir '讲稿渲染.pdf') (Join-Path $wordDir 'page')
if ($LASTEXITCODE -ne 0) {throw 'Word PDF rasterization failed'}
Write-Output $renderDir
Write-Output ($report | ConvertTo-Json -Depth 4 -Compress)
