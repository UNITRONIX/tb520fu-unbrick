# Bump to 9008 and dump from there, in one sequence.
#
# Why this is worth trying
# ------------------------
# In 900E the memory table lists DDRCS0_0 at the LOWEST address (0x80000000) and the tool
# reads addresses ascending, so it hits CS0 first, stalls at 0x82800000, and never reaches
# DDR_DATA.BIN at 0x1000080000 (the highest address). Documented in
# docs/30-dump-order-blocks-ddr-data.md.
#
# In 9008 the device is in image-transfer mode rather than crashdump. The memory table may
# be different, or CS0 may serve fully. Nobody has checked.
#
# The sequence
# ------------
#   1. wait for a fresh 900E port (must be opened before HELLO arrives)
#   2. QSaharaServer with the programmer: that both uploads it AND switches to 9008
#   3. the port re-enumerates as a 9008 QDLoader port
#   4. QSaharaServer -m on that port to dump memory from 9008
#
# Nothing is written to storage. Step 2 uploads a programmer into RAM, exactly as every
# earlier attempt did.

param(
    [string]$WorkDir = "C:\Users\UNITRONIX\Downloads\tb520fu-unbrick\com_attempt",
    [string]$Melf    = ".\image\xbl_s_devprg_ns.melf"
)

$ErrorActionPreference = 'Continue'

function Get-QualcommPort {
    $k = 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM'
    if (-not (Test-Path $k)) { return $null }
    $v = (Get-ItemProperty $k).PSObject.Properties | Where-Object { $_.Name -match 'QCUSB_COM(\d+)' }
    if (-not $v) { return $null }
    $best = $null; $bestN = -1
    foreach ($p in $v) {
        if ($p.Name -match 'QCUSB_COM(\d+)') {
            $n = [int]$Matches[1]
            if ($n -gt $bestN) { $bestN = $n; $best = $p.Value }
        }
    }
    return $best
}

Set-Location $WorkDir
Write-Host ('=' * 72)
Write-Host '  BUMP TO 9008, THEN DUMP FROM 9008'
Write-Host ('=' * 72)

# ---- step 1: fresh 900E ------------------------------------------------
Write-Host ''
Write-Host 'Waiting for a fresh 900E port (power-cycle the tablet now if needed).'
Write-Host 'The port must be caught before HELLO is sent.'

$sawGone = $false
$deadline = (Get-Date).AddSeconds(180)
$p0 = $null
while ((Get-Date) -lt $deadline) {
    $cur = Get-QualcommPort
    if (-not $cur) { $sawGone = $true }
    elseif ($sawGone) { $p0 = $cur; break }
    Start-Sleep -Milliseconds 200
}
if (-not $p0) {
    if ($cur) { $p0 = $cur; Write-Host "  using existing port $p0 (no absence seen)" }
    else { Write-Host '  no port appeared' -ForegroundColor Red; exit 1 }
}
Write-Host "  900E port: $p0" -ForegroundColor Green

# ---- step 2: upload programmer -> switches to 9008 --------------------
Write-Host ''
Write-Host ('-' * 72)
Write-Host '  STEP 2: QSaharaServer with programmer (uploads, then switches to 9008)'
Write-Host ('-' * 72)

& .\QSaharaServer.exe -p "\\.\$p0" -x -s "13:$Melf" -v 2 2>&1 |
    Tee-Object -FilePath "bump_dump_step2.txt"
Write-Host "  exit=$LASTEXITCODE"

$log2 = Get-Content 'bump_dump_step2.txt' -Raw -ErrorAction SilentlyContinue
if ($log2 -match 'Sahara protocol completed') {
    Write-Host '  Sahara: COMPLETED' -ForegroundColor Green
} else {
    Write-Host '  Sahara: did not report completion' -ForegroundColor Yellow
}

# ---- step 3: wait for a new port --------------------------------------
Write-Host ''
Write-Host 'Waiting for the port to reappear (9008 QDLoader)...'
$p1 = $null
$deadline = (Get-Date).AddSeconds(90)
$sawAbsent = $false
while ((Get-Date) -lt $deadline) {
    $cur = Get-QualcommPort
    if (-not $cur) { $sawAbsent = $true }
    elseif ($sawAbsent -and $cur -ne $p0) { $p1 = $cur; break }
    elseif ($sawAbsent -and $cur) { $p1 = $cur; break }
    Start-Sleep -Milliseconds 200
}

if (-not $p1) {
    $cur = Get-QualcommPort
    if ($cur) { $p1 = $cur; Write-Host "  port still $p1 - using it" -ForegroundColor Yellow }
    else {
        Write-Host '  device did not come back. This is the known behaviour after an upload:' -ForegroundColor Red
        Write-Host '  the programmer starts, fails, and the device drops off USB. A power'
        Write-Host '  cycle is needed, and the 9008 dump cannot be taken this way.'
        exit 1
    }
}
Write-Host "  port now: $p1" -ForegroundColor Green

# check what the node looks like
$node = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -match 'VID_05C6' }
if ($node) {
    foreach ($n in $node) { Write-Host "  node: $($n.FriendlyName)" }
}

# ---- step 4: dump from the new port -----------------------------------
Write-Host ''
Write-Host ('-' * 72)
Write-Host "  STEP 4: memory dump from $p1"
Write-Host ('-' * 72)

& .\QSaharaServer.exe -p "\\.\$p1" -m -v 2 -w . 2>&1 |
    Tee-Object -FilePath "bump_dump_step4.txt"
Write-Host "  exit=$LASTEXITCODE"

$log4 = Get-Content 'bump_dump_step4.txt' -Raw -ErrorAction SilentlyContinue
if ($log4 -match 'DDR_DATA') {
    Write-Host '  DDR_DATA.BIN appeared in the table' -ForegroundColor Green
}
if (Test-Path 'DDR_DATA.BIN') {
    Write-Host "  DDR_DATA.BIN written: $((Get-Item 'DDR_DATA.BIN').Length) bytes" -ForegroundColor Green
} elseif (Test-Path '.DDR_DATA.BIN') {
    Write-Host "  DDR_DATA.BIN written: $((Get-Item '.DDR_DATA.BIN').Length) bytes" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Logs: bump_dump_step2.txt, bump_dump_step4.txt'
