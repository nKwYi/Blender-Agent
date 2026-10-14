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
#   powershell -ExecutionPolicy Bypass -File dev\run_all.ps1 -SkipGen

param(
    [string]$Filter = '',
    [switch]$SkipGen
)

$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)

$B = 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
if (-not (Test-Path $B)) { Write-Output "BLENDER MISSING: $B"; exit 2 }

$PY = 'python'

$OUT = Join-Path $PSScriptRoot 'out'
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

# Runs one script and returns everything the verdict logic needs.
# engine 'bpy' -> blender --background -P (needs bpy), engine 'py' -> plain python.
# NOTE: never truncate these logs. Select-Object -Last N hides the real error.
function Invoke-Script {
    param([string]$Name, [string]$Engine, [string]$Path)

    $o = Join-Path $OUT ("ra_$Name.out.txt")
    $e = Join-Path $OUT ("ra_$Name.err.txt")
    $sw = [Diagnostics.Stopwatch]::StartNew()
    if ($Engine -eq 'bpy') {
        & $B --background --factory-startup -P $Path 1> $o 2> $e
    }
    else {
        & $PY $Path 1> $o 2> $e
    }
    $rc = $LASTEXITCODE
    $sw.Stop()

    $so = (Get-Content $o -Raw -ErrorAction SilentlyContinue)
    $se = (Get-Content $e -Raw -ErrorAction SilentlyContinue)
    [pscustomobject]@{
        out  = @(("$so`n$se") -split "`n")
        rc   = $rc
        secs = [int]$sw.Elapsed.TotalSeconds
    }
}

# summary   : regex the script must print to be considered green
# mustMatch : $false means "skip if the script intentionally prints no summary line"
# engine    : 'bpy' (blender --background -P) or 'py' (plain python)
# expectSec : measured on this machine, printed in the table so a slow run
#             is not mistaken for a hung run
$TESTS = @(
    @{ name = 'test_tools';          summary = 'RESULT tools:\s*0 failed';           mustMatch = $true; engine = 'bpy'; expectSec = 5 },
    @{ name = 'test_loop_mock';      summary = 'RESULT loop:\s*0 failed';            mustMatch = $true; engine = 'bpy'; expectSec = 10 },
    @{ name = 'test_http_errors';    summary = 'RESULT http:\s*0 failed';            mustMatch = $true; engine = 'bpy'; expectSec = 5 },
    @{ name = 'test_p0_contract';    summary = 'RESULT p0:\s*0 failed';              mustMatch = $true; engine = 'bpy'; expectSec = 5 },
    @{ name = 'test_provider_minimax'; summary = 'RESULT provider_minimax:\s*0 failed'; mustMatch = $true; engine = 'bpy'; expectSec = 5 },
    @{ name = 'test_native_ui';      summary = 'RESULT native_ui:\s*0 failed';       mustMatch = $true; engine = 'bpy'; expectSec = 10 },

    # ui_workbench chain: ids -> states -> constraints/vocabulary -> layout -> data.js
    @{ name = 'test_ids';            summary = 'PASS \d+\s+FAIL 0';                  mustMatch = $true; engine = 'bpy'; expectSec = 5 },
    @{ name = 'test_states';         summary = 'PASS \d+\s+FAIL 0';                  mustMatch = $true; engine = 'bpy'; expectSec = 5 },
    @{ name = 'test_constraints';    summary = 'PASS \d+\s+FAIL 0';                  mustMatch = $true; engine = 'py';  expectSec = 2 },
    @{ name = 'test_recorder';       summary = 'PASS \d+\s+FAIL 0';                  mustMatch = $true; engine = 'py';  expectSec = 2 },
    @{ name = 'test_pipeline';       summary = 'PASS \d+\s+FAIL 0';                  mustMatch = $true; engine = 'py';  expectSec = 2 },

    # The next two each spawn headless Edge 7-8 times (--headless=new --dump-dom)
    # to read the rendered DOM. Measured 5s each on this machine when Edge is warm;
    # on a cold first launch budget up to ~1 min EACH. A quiet console here is normal.
    # Their dom_* assertions go RED when no browser is found on purpose -- no fake green.
    @{ name = 'test_workbench_data'; summary = 'PASS \d+\s+FAIL 0';                  mustMatch = $true; engine = 'py';  expectSec = 60 },
    @{ name = 'test_proposal_vocab'; summary = 'PASS \d+\s+FAIL 0';                  mustMatch = $true; engine = 'py';  expectSec = 60 }
)

# Re-generate the workbench artifacts BEFORE testing them, so the batch proves the
# whole chain rebuilds (constraints -> vocabulary -> layout trees -> data.js) instead
# of re-reading whatever happens to sit on disk. -SkipGen keeps the old read-only run.
$GENERATORS = @(
    @{ name = 'build_constraints'; engine = 'py';  ok = 'CONSTRAINTS_OK' },
    @{ name = 'capture_layout';    engine = 'bpy'; ok = 'CAPTURE_LAYOUT_OK' },
    @{ name = 'build_vocabulary';   engine = 'py';  ok = 'VOCAB_OK' },
    @{ name = 'build_data_js';      engine = 'py';  ok = 'DATA_JS_OK' }
)

$genRows = @()
if ($SkipGen) {
    Write-Output 'GENERATORS: skipped (-SkipGen)'
}
else {
    foreach ($g in $GENERATORS) {
        $script = Join-Path $PSScriptRoot ($g.name + '.py')
        if (-not (Test-Path $script)) {
            $genRows += [pscustomobject]@{ step = $g.name; verdict = 'SKIP'; rc = '-'; secs = 0; note = 'script not found' }
            continue
        }
        $r = Invoke-Script -Name ("gen_" + $g.name) -Engine $g.engine -Path $script
        $okLine = ($r.out | Where-Object { $_ -match $g.ok } | Select-Object -Last 1)
        $verdict = 'PASS'
        $note = ''
        if (-not $okLine) {
            $verdict = 'FAIL'
            $note = 'no ok marker matched - artifacts may be stale'
        }
        elseif ($r.rc -ne 0) {
            $verdict = 'FAIL'
            $note = "rc=$r.rc while marker looked ok - crash/abort risk"
        }
        else { $note = $okLine.Trim() }
        $genRows += [pscustomobject]@{ step = $g.name; verdict = $verdict; rc = $r.rc; secs = $r.secs; note = $note }
    }
    $genPass = @($genRows | Where-Object { $_.verdict -eq 'PASS' }).Count
    $genFail = @($genRows | Where-Object { $_.verdict -eq 'FAIL' }).Count
    $genSkip = @($genRows | Where-Object { $_.verdict -eq 'SKIP' }).Count
    Write-Output ''
    Write-Output '================ ARTIFACT REGENERATION ================'
    $genRows | Format-Table -AutoSize | Out-String -Width 220 | Write-Output
    Write-Output ("PASS {0}  FAIL {1}  SKIP {2}" -f $genPass, $genFail, $genSkip)
    if ($genFail) { Write-Output 'GENERATOR FAIL: downstream results would be meaningless. Stopping.'; exit 1 }
}

if ($Filter) { $TESTS = $TESTS | Where-Object { $_.name -like "*$Filter*" } }

$rows = @()
foreach ($t in $TESTS) {
    $script = Join-Path $PSScriptRoot ($t.name + '.py')
    if (-not (Test-Path $script)) {
        $rows += [pscustomobject]@{ test = $t.name; engine = $t.engine; verdict = 'SKIP'; rc = '-'; secs = 0; expectSec = $t.expectSec; note = 'script not found' }
        continue
    }

    $r = Invoke-Script -Name $t.name -Engine $t.engine -Path $script

    $sumLine   = ($r.out | Where-Object { $_ -match $t.summary } | Select-Object -Last 1)
    $failMark  = ($r.out | Where-Object { $_ -match 'FAIL\s+[1-9]|RESULT[^:]*:\s*[1-9]\d*\s+failed' } | Select-Object -First 1)

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
    elseif ($r.rc -ne 0) {
        $verdict = 'FAIL'
        $note = "rc=$($r.rc) while summary looked ok - crash/abort risk"
    }
    elseif ($sumLine) { $note = $sumLine.Trim() }

    $rows += [pscustomobject]@{ test = $t.name; engine = $t.engine; verdict = $verdict; rc = $r.rc; secs = $r.secs; expectSec = $t.expectSec; note = $note }
}

$passN = @($rows | Where-Object { $_.verdict -eq 'PASS' }).Count
$failN = @($rows | Where-Object { $_.verdict -eq 'FAIL' }).Count

Write-Output ''
Write-Output '================ HEADLESS REGRESSION ================'
Write-Output 'secs = measured wall clock; expectSec = measured/cold-start budget. A slow test is not a hung test.'
$rows | Format-Table -AutoSize | Out-String -Width 220 | Write-Output
Write-Output ("PASS {0}  FAIL {1}  SKIP {2}" -f $passN, $failN, @($rows | Where-Object { $_.verdict -eq 'SKIP' }).Count)
Write-Output ("total wall clock: {0}s" -f (@($rows | Measure-Object -Property secs -Sum).Sum + @($genRows | Measure-Object -Property secs -Sum).Sum))
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