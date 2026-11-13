param(
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $env:TEMP "avito-watch-install.log"

function Write-Step($text) {
    Write-Host $text
    Add-Content -LiteralPath $log -Value $text -Encoding UTF8
}

function Find-Python {
    $candidates = @()
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $found = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($found) { $candidates += $found.Trim() }
        } catch { }
    }
    foreach ($path in $candidates) {
        try {
            $version = & $path -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($version) {
                $parts = $version.Trim().Split(".")
                if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) { return $path }
            }
        } catch { }
    }
    return $null
}

Write-Step "== установка зависимостей Avito Watch =="

$python = Find-Python
if (-not $python) {
    Write-Step "Python 3.10+ не найден."
    if (-not $Silent) {
        $answer = Read-Host "Открыть страницу загрузки Python? (y/n)"
        if ($answer -eq "y") { Start-Process "https://www.python.org/downloads/windows/" }
    }
    exit 2
}

Write-Step "Python: $python"

& $python -m pip install --upgrade pip --quiet 2>&1 | ForEach-Object { Add-Content -LiteralPath $log -Value $_ -Encoding UTF8 }
Write-Step "ставлю playwright и psutil..."
& $python -m pip install --upgrade playwright psutil 2>&1 | ForEach-Object { Add-Content -LiteralPath $log -Value $_ -Encoding UTF8 }
if ($LASTEXITCODE -ne 0) {
    Write-Step "pip завершился с ошибкой $LASTEXITCODE, смотри $log"
    exit 3
}

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($chrome) {
    Write-Step "Chrome найден: $chrome"
} else {
    Write-Step "Chrome не найден — ставлю Chromium для Playwright (может занять пару минут)"
    & $python -m playwright install chromium 2>&1 | ForEach-Object { Add-Content -LiteralPath $log -Value $_ -Encoding UTF8 }
}

Write-Step "готово"
exit 0
