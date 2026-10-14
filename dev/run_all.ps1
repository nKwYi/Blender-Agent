# Full headless regression runner.
#
# WHY THIS FILE EXISTS
# Most test scripts in this repo only PRINT their failure list and then exit normally,
# so `rc=0` is FAKE GREEN. Real incident: dev\test_ui_v2.py had 26 failing assertions
# and still returned rc=0; that was reported as "all green" more than once. Wrong.
#
# Verdict rule (BOTH must hold to call a test PASS):
#   1. the script's own summary line matches, with a zero failure count
#   2. the process exit code is 0
# If either fails the test is FAIL. Full stdout/stderr is always written to disk,
# and FAIL prints the first 20 stderr lines per failing test.
#
# NOTE: keep this file ASCII-only on purpose. The Write tool emits UTF-8 without BOM
# and PowerShell 5.1 reads BOM-less .ps1 as ANSI; CJK bytes then decode into stray
# backticks/quotes that escape the newline and break parsing. ASCII sidesteps it.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File dev\run_all.ps1
#   powershell -ExecutionPolicy Bypass -File dev\run_all.ps1 -Filter panel

param(
    [string]$Filter = ''
)

$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)

$B = 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
if (-not (Test-Path $B)) { Write-Output "BLENDER MISSING: $B"; exit 2 }

$OUT = Join-Path $PSScriptRoot 'out'
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

# summary   : regex the script must print to be considered green
# mustMatch : $false means "skip if the script intentionally prints no summary line"
$TESTS = @(
    @{ name = 'test_tools';          summary = 'RESULT tools:\s*0 failed';           mustMatch = $true },
    @{ name = 'test_loop_mock';      summary = 'RESULT loop:\s*0 failed';            mustMatch = $true },
    @{ name = 'test_http_errors';    summary = 'RESULT http:\s*0 failed';            mustMatch = $true },
    @{ name = 'test_p0_contract';    summary = 'RESULT p0:\s*0 failed';              mustMatch = $true },
    @{ name = 'test_provider_minimax'; summary = 'RESULT provider_minimax:\s*0 failed'; mustMatch = $true },
    @{ name = 'test_native_ui';      summary = 'RESULT native_ui:\s*0 failed';       mustMatch = $true }
)

if ($Filter) { $TESTS = $TESTS | Where-Object { $_.name -like "*$Filter*" } }

$rows = @()
foreach ($t in $TESTS) {
    $script = Join-Path $PSScriptRoot ($t.name + '.py')
    if (-not (Test-Path $script)) {
        $rows += [pscustomobject]@{ test = $t.name; verdict = 'SKIP'; rc = '-'; note = 'script not found' }
        continue
    }

    $o = Join-Path $OUT ("ra_$($t.name).out.txt")
    $e = Join-Path $OUT ("ra_$($t.name).err.txt")

    & $B --background --factory-startup -P $script 1> $o 2> $e
    $rc = $LASTEXITCODE

    # Read in full. Never Select-Object -Last N: truncation hides the real error.
    $so = (Get-Content $o -Raw -ErrorAction SilentlyContinue)
    $se = (Get-Content $e -Raw -ErrorAction SilentlyContinue)
    $lines = @(("$so`n$se") -split "`n")

    $sumLine   = ($lines | Where-Object { $_ -match $t.summary } | Select-Object -Last 1)
    $failMark  = ($lines | Where-Object { $_ -match 'FAIL\s+[1-9]|RESULT[^:]*:\s*[1-9]\d*\s+failed' } | Select-Object -First 1)

    $verdict = 'PASS'
    $note = ''
    if ($failMark) {
        $verdict = 'FAIL'
        $note = "failure marker: $($failMark.Trim())"
    }
    elseif ($t.mustMatch -and -not $sumLine) {
        $verdict = 'FAIL'
        $note = 'no summary line matched - cannot be treated as green'
    }
    elseif ($rc -ne 0) {
        $verdict = 'FAIL'
        $note = "rc=$rc while summary looked ok - crash/abort risk"
    }
    elseif ($sumLine) { $note = $sumLine.Trim() }

    $rows += [pscustomobject]@{ test = $t.name; verdict = $verdict; rc = $rc; note = $note }
}

$passN = @($rows | Where-Object { $_.verdict -eq 'PASS' }).Count
$failN = @($rows | Where-Object { $_.verdict -eq 'FAIL' }).Count

Write-Output ''
Write-Output '================ HEADLESS REGRESSION ================'
$rows | Format-Table -AutoSize | Out-String -Width 220 | Write-Output
Write-Output ("PASS {0}  FAIL {1}  SKIP {2}" -f $passN, $failN, @($rows | Where-Object { $_.verdict -eq 'SKIP' }).Count)
Write-Output "logs: $OUT\ra_*.out.txt / ra_*.err.txt"

if ($failN) {
    Write-Output ''
    Write-Output '--- FAIL detail (first 20 stderr lines each) ---'
    foreach ($t in $TESTS) {
        $e = Join-Path $OUT ("ra_$($t.name).err.txt")
        if ((Test-Path $e) -and (Get-Item $e).Length -gt 0) {
            Write-Output "### $($t.name)"
            Get-Content $e -Encoding UTF8 | Where-Object { $_.Trim() } | Select-Object -First 20 | Write-Output
        }
    }
    exit 1
}
exit 0