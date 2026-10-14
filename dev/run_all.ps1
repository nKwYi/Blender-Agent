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

# Lines BLENDER prints on exit, which are not the script speaking: the version
# banner and "Blender quit". Which of them appear varies by exit path (a script
# that raises SystemExit prints both; one that returns prints neither), so match
# the shape, not the exact text. Without this every bpy test would look like it
# "died after reporting", and with the looser match a real crash corpse printed
# after the summary would be excused too -- so keep this list as narrow as it can
# be: only these two shapes are ever skipped.
$ENGINE_NOISE = @(
    '^Blender quit$',
    '^Blender \d'
)

# Pure separator rules like "======". Several scripts print one as a closing
# flourish AFTER their summary, so a strict last-line rule would fail them.
# This cannot hide a failure: a line made only of = - _ # * carries no text, and
# no traceback, assertion name or error message can ever look like one.
$DECORATION = '^[=\-_#*]{3,}$'

function Get-TailLine {
    param([string[]]$Lines)
    for ($i = $Lines.Count - 1; $i -ge 0; $i--) {
        $t = $Lines[$i].Trim()
        if (-not $t) { continue }
        if ($t -match $DECORATION) { continue }
        $isNoise = $false
        foreach ($n in $ENGINE_NOISE) { if ($t -match $n) { $isNoise = $true; break } }
        if ($isNoise) { continue }
        return $t
    }
    return ''
}

# summary   : regex the script must print to be considered green
# mustMatch : $false means "skip if the script intentionally prints no summary line"
# engine    : 'bpy' (blender --background -P) or 'py' (plain python)
#
# NOTE on the summary regexes: 'PASS [1-9]\d*\s+FAIL 0' deliberately requires at
# least ONE assertion. The looser 'PASS \d+' also matches 'PASS 0  FAIL 0', and a
# harness that aborts before asserting anything still exits 0 -- that reads as
# green while nothing was checked. Zero assertions is never a pass.
$TESTS = @(
    @{ name = 'test_tools';          summary = 'RESULT tools:\s*0 failed';           mustMatch = $true; engine = 'bpy' },
    @{ name = 'test_loop_mock';      summary = 'RESULT loop:\s*0 failed';            mustMatch = $true; engine = 'bpy' },
    @{ name = 'test_http_errors';    summary = 'RESULT http:\s*0 failed';            mustMatch = $true; engine = 'bpy' },
    @{ name = 'test_p0_contract';    summary = 'RESULT p0:\s*0 failed';              mustMatch = $true; engine = 'bpy' },
    @{ name = 'test_provider_minimax'; summary = 'RESULT provider_minimax:\s*0 failed'; mustMatch = $true; engine = 'bpy' },
    @{ name = 'test_native_ui';      summary = 'RESULT native_ui:\s*0 failed';       mustMatch = $true; engine = 'bpy' },

    # ui_workbench chain: ids -> states -> constraints/vocabulary -> layout -> data.js
    @{ name = 'test_ids';            summary = 'PASS [1-9]\d*\s+FAIL 0';              mustMatch = $true; engine = 'bpy' },
    @{ name = 'test_states';         summary = 'PASS [1-9]\d*\s+FAIL 0';              mustMatch = $true; engine = 'bpy' },
    @{ name = 'test_constraints';    summary = 'PASS [1-9]\d*\s+FAIL 0';              mustMatch = $true; engine = 'py'  },
    @{ name = 'test_recorder';       summary = 'PASS [1-9]\d*\s+FAIL 0';              mustMatch = $true; engine = 'py'  },
    @{ name = 'test_pipeline';       summary = 'PASS [1-9]\d*\s+FAIL 0';              mustMatch = $true; engine = 'py'  },

    # The next two each spawn headless Edge 7-8 times (--headless=new --dump-dom)
    # to read the rendered DOM. Measured 4-5s each on this machine; a cold first
    # Edge launch (fresh profile) can take a minute. A quiet console here is normal.
    # No fake green: BOTH record a FAILing dom_browser_present assertion when no
    # browser is found (UW_SKIP_DOM=1 is the explicit opt-out). Neither one may
    # WARN-and-return with its dom_* assertions silently dropped while rc stays 0.
    @{ name = 'test_workbench_data'; summary = 'PASS [1-9]\d*\s+FAIL 0';              mustMatch = $true; engine = 'py'  },
    @{ name = 'test_proposal_vocab'; summary = 'PASS [1-9]\d*\s+FAIL 0';              mustMatch = $true; engine = 'py'  }
)

# Re-generate the workbench artifacts BEFORE testing them, so the batch proves the
# whole chain rebuilds (constraints -> vocabulary -> layout trees -> data.js) instead
# of re-reading whatever happens to sit on disk. -SkipGen keeps the old read-only run.
#
# ok   : marker that must appear for the step to have done its job
# tail : regex the script's LAST line must match, so a generator that prints its
#        marker and then dies is FAIL (Blender -P crashes still exit 0).
$GENERATORS = @(
    @{ name = 'build_constraints'; engine = 'py';  ok = 'CONSTRAINTS_OK';  tail = 'ENTRIES \d+' },
    @{ name = 'capture_layout';    engine = 'bpy'; ok = 'CAPTURE_LAYOUT_OK'; tail = 'PASS [1-9]\d*\s+FAIL 0' },
    @{ name = 'build_vocabulary';   engine = 'py';  ok = 'VOCAB_OK';        tail = 'UNMAPPED_OK |REJECT ' },
    @{ name = 'build_data_js';      engine = 'py';  ok = 'DATA_JS_OK';      tail = 'KEYS ' }
)

$genRows = @()
# -Filter means "run this one thing", not "rebuild everything then run it".
# Regenerating during a filtered run would silently rewrite ui_workbench/ artifacts
# for someone who only wanted to re-check one test, so skip it and say so.
if ($SkipGen) {
    Write-Output 'GENERATORS: skipped (-SkipGen)'
}
elseif ($Filter) {
    Write-Output "GENERATORS: skipped (-Filter $Filter). A filtered run does not rebuild artifacts."
}
else {
    foreach ($g in $GENERATORS) {
        $script = Join-Path $PSScriptRoot ($g.name + '.py')
        if (-not (Test-Path $script)) {
            # NOT a SKIP: this stage exists precisely to keep stale artifacts from
            # being blessed. A missing generator means nothing was rebuilt, so the
            # batch must stop instead of testing whatever was already on disk.
            $genRows += [pscustomobject]@{ step = $g.name; verdict = 'FAIL'; rc = '-'; secs = 0; note = 'generator script not found - refusing to bless possibly stale artifacts' }
            continue
        }
        $r = Invoke-Script -Name ("gen_" + $g.name) -Engine $g.engine -Path $script
        $okLine = ($r.out | Where-Object { $_ -match $g.ok } | Select-Object -Last 1)
        $tail = Get-TailLine -Lines $r.out
        $verdict = 'PASS'
        $note = ''
        if (-not $okLine) {
            $verdict = 'FAIL'
            $note = 'no ok marker matched - artifacts may be stale'
        }
        elseif ($tail -notmatch $g.tail) {
            $verdict = 'FAIL'
            $note = "ok marker printed but the last line was not '$($g.tail)': $tail"
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
    Write-Output ''
    Write-Output '================ ARTIFACT REGENERATION ================'
    $genRows | Format-Table -AutoSize | Out-String -Width 220 | Write-Output
    Write-Output ("PASS {0}  FAIL {1}" -f $genPass, $genFail)
    if ($genFail) { Write-Output 'GENERATOR FAIL: downstream results would be meaningless. Stopping.'; exit 1 }
}

if ($Filter) {
    $TESTS = $TESTS | Where-Object { $_.name -like "*$Filter*" }
    if (@($TESTS).Count -eq 0) {
        # A typo in -Filter used to run nothing at all and still exit 0 with a
        # "PASS 0" summary -- a green run that checked nothing.
        Write-Output "FILTER '$Filter' matched no test in the list - refusing to report an empty green run."
        exit 2
    }
}

$rows = @()
foreach ($t in $TESTS) {
    $script = Join-Path $PSScriptRoot ($t.name + '.py')
    if (-not (Test-Path $script)) {
        $rows += [pscustomobject]@{ test = $t.name; engine = $t.engine; verdict = 'SKIP'; rc = '-'; secs = 0; note = 'script not found' }
        continue
    }

    $r = Invoke-Script -Name $t.name -Engine $t.engine -Path $script

    $sumLine   = ($r.out | Where-Object { $_ -match $t.summary } | Select-Object -Last 1)
    $failMark  = ($r.out | Where-Object { $_ -match 'FAIL\s+[1-9]|RESULT[^:]*:\s*[1-9]\d*\s+failed' } | Select-Object -First 1)
    $tail      = Get-TailLine -Lines $r.out

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
    elseif ($sumLine -and $tail -ne $sumLine.Trim()) {
        # The summary is not the last thing the script said. Blender -P can crash
        # (or be killed) with exit code 0, so a summary printed before the crash is
        # not evidence that the run finished. Anything after it is the corpse.
        $verdict = 'FAIL'
        $note = "summary matched but was not the last line the script printed - last line was: $tail"
    }
    elseif ($r.rc -ne 0) {
        $verdict = 'FAIL'
        $note = "rc=$($r.rc) while summary looked ok - crash/abort risk"
    }
    elseif ($sumLine) { $note = $sumLine.Trim() }

    $rows += [pscustomobject]@{ test = $t.name; engine = $t.engine; verdict = $verdict; rc = $r.rc; secs = $r.secs; note = $note }
}

$passN = @($rows | Where-Object { $_.verdict -eq 'PASS' }).Count
$failN = @($rows | Where-Object { $_.verdict -eq 'FAIL' }).Count

Write-Output ''
Write-Output '================ HEADLESS REGRESSION ================'
Write-Output 'secs = measured wall clock on this machine. test_workbench_data and test_proposal_vocab'
Write-Output 'each spawn headless Edge 7-8 times: ~5s warm, up to ~1 min on a cold first launch.'
Write-Output 'A slow test is not a hung test.'
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