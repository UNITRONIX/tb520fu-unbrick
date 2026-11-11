# Read DDR_DATA.BIN (DDR Training Data) in one clean session.
#
# Why this one region
# -------------------
# The 53-entry memory table declares, at 0x1000080000 length 0x40000:
#
#     0x1000080000  len 0x40000  'DDR_DATA.BIN'  'DDR Training Data'
#
# If DDR training completed for all eight windows, that data describes eight. If one
# rank failed, it describes seven. That distinguishes "the mapping is truncated" from
# "the hardware never trained", which is the remaining ambiguity in
# docs/26-ddr-wall-at-40mb.md.
#
# It is one 256 KiB read. QSaharaServer dumps every declared region, which is why the
# previous run wrote 14 GB; this script asks for the single region of interest and
# stops.
#
# It writes nothing to the device.

param(
    [string]$WorkDir = "C:\Users\UNITRONIX\Downloads\tb520fu-unbrick\com_attempt"
)

$ErrorActionPreference = 'Continue'

function Get-QualcommPort {
    $k = 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM'
    if (-not (Test-Path $k)) { return $null }
    $v = (Get-ItemProperty $k).PSObject.Properties |
        Where-Object { $_.Name -match 'QCUSB_COM(\d+)' }
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

Write-Host ('=' * 70)
Write-Host '  Read DDR_DATA.BIN (DDR Training Data) - single region'
Write-Host ('=' * 70)

$port = Get-QualcommPort
if (-not $port) {
    Write-Host 'No Qualcomm COM port. Power-cycle the tablet and re-run.' -ForegroundColor Yellow
    exit 1
}
Write-Host "Port: $port"

# Remove any previous copies so a stale file cannot be mistaken for a fresh read.
foreach ($n in 'DDR_DATA.BIN', 'sbl_pmic_dump.bin') {
    if (Test-Path $n) { Remove-Item $n -Force }
}

Write-Host ''
Write-Host 'Starting Sahara in memory-debug mode. This consumes the only HELLO.'
Write-Host ''

# -m forces memory debug. No -s, so no programmer is uploaded: this only reads.
& .\QSaharaServer.exe -p "\\.\$port" -m -v 2 2>&1 | Tee-Object -FilePath "ddrdata_log.txt"
$exit = $LASTEXITCODE
Write-Host "`nexit=$exit"

Write-Host ''
Write-Host ('=' * 70)
Write-Host '  RESULT'
Write-Host ('=' * 70)

$log = Get-Content 'ddrdata_log.txt' -Raw -ErrorAction SilentlyContinue

if ($log -match 'DDR_DATA\.BIN') {
    Write-Host 'DDR_DATA.BIN was offered by the device:' -ForegroundColor Green
    ($log -split "`n") | Where-Object { $_ -match 'DDR_DATA|DDR Training' } | ForEach-Object { Write-Host "  $($_.Trim())" }
} else {
    Write-Host 'DDR_DATA.BIN did not appear in the log.' -ForegroundColor Yellow
}

if (Test-Path 'DDR_DATA.BIN') {
    $sz = (Get-Item 'DDR_DATA.BIN').Length
    Write-Host "`nFile written: DDR_DATA.BIN  $sz bytes" -ForegroundColor Green
} else {
    Write-Host "`nNo DDR_DATA.BIN file was produced." -ForegroundColor Yellow
}

if ($log -match 'Received 0 bytes') {
    $zeros = ([regex]::Matches($log, 'Received 0 bytes')).Count
    Write-Host "`nZero-byte reads: $zeros" -ForegroundColor Yellow
}
