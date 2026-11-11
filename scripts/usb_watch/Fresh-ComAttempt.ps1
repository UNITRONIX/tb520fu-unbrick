# Fresh-cycle attempt: power-cycle the device by command, then one shot.
#
# Every attempt consumes the single Sahara HELLO. Once consumed the port stays open
# but silent, and no tool can proceed until the device re-enumerates.
#
# This script therefore does the whole thing in ONE run:
#   - asks the user to power-cycle (there is no software way to reset 900E)
#   - waits for the COM port to appear
#   - runs QSaharaServer with the chosen programmer
#   - runs fh_loader immediately after, same port, nothing in between
#   - prints both exit codes and the trace
#
# It deliberately does NOT probe the device. Every probe costs the HELLO.

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('17', '18')]
    [string]$Version,

    [string]$WorkDir = "C:\Users\UNITRONIX\Downloads\tb520fu-unbrick\com_attempt"
)

$ErrorActionPreference = 'Continue'

function Get-QualcommPort {
    # Passive registry read. Does not open the device.
    $k = 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM'
    if (-not (Test-Path $k)) { return $null }
    $vals = (Get-ItemProperty $k).PSObject.Properties |
        Where-Object { $_.Name -match 'QCUSB_COM(\d+)' }
    if (-not $vals) { return $null }
    # Highest COM number is the newest enumeration
    $best = $null; $bestN = -1
    foreach ($v in $vals) {
        if ($v.Name -match 'QCUSB_COM(\d+)') {
            $n = [int]$Matches[1]
            if ($n -gt $bestN) { $bestN = $n; $best = $v.Value }
        }
    }
    return $best
}

$melfDir = if ($Version -eq '17') { 'image17' } else { 'image' }
$melf = ".\$melfDir\xbl_s_devprg_ns.melf"
$melfFull = Join-Path $WorkDir "$melfDir\xbl_s_devprg_ns.melf"

if (-not (Test-Path $melfFull)) {
    Write-Host "Missing programmer: $melfFull" -ForegroundColor Red
    exit 1
}
$h = (Get-FileHash $melfFull -Algorithm SHA256).Hash
Write-Host ("Programmer: {0}  sha256={1}" -f $melfDir, $h.Substring(0, 16))

Write-Host ''
Write-Host ('=' * 70)
Write-Host "  POWER CYCLE THE TABLET NOW"
Write-Host ('=' * 70)
Write-Host '  Hold Power ~15 s. Wait for the device to come back.'
Write-Host '  Do NOT plug anything else in, do not run any other tool.'
Write-Host ''
Write-Host '  Waiting for the Qualcomm COM port to appear...'

# Wait for the port to go AWAY and come back, so we know it is fresh.
$seenGone = $false
$deadline = (Get-Date).AddSeconds(180)
$port = $null

while ((Get-Date) -lt $deadline) {
    $p = Get-QualcommPort
    if (-not $p) {
        $seenGone = $true
    }
    elseif ($seenGone -or $p) {
        $port = $p
        break
    }
    Start-Sleep -Milliseconds 300
}

if (-not $port) {
    Write-Host '  No Qualcomm port appeared within 180 s.' -ForegroundColor Red
    Write-Host '  Check the cable and that the driver is still bound:'
    Write-Host '    Get-PnpDevice -PresentOnly | ? InstanceId -match "VID_05C6"'
    exit 1
}

Write-Host "  Port: $port" -ForegroundColor Green
Write-Host '  Starting immediately - no probes.'

Set-Location $WorkDir

# ---- STEP 1 ---------------------------------------------------------------
Write-Host ''
Write-Host ('-' * 70)
Write-Host "  STEP 1  QSaharaServer  ($melfDir)"
Write-Host ('-' * 70)

& .\QSaharaServer.exe -p "\\.\$port" -x -s "13:$melf" -v 2 2>&1 |
    Tee-Object -FilePath "qs_$Version.txt"
$qsExit = $LASTEXITCODE
Write-Host "  exit=$qsExit"

# ---- STEP 2 ---------------------------------------------------------------
Write-Host ''
Write-Host ('-' * 70)
Write-Host '  STEP 2  fh_loader  (immediately)'
Write-Host ('-' * 70)

# After a successful transfer the device may re-enumerate as a different COM port.
# Re-read the registry; this is passive and does not cost a HELLO.
$port2 = Get-QualcommPort
if (-not $port2) { $port2 = $port }
Write-Host "  using $port2"

& .\fh_loader.exe --port="\\.\$port2" --noprompt --showpercentagecomplete `
    --memoryname=UFS --zlpawarehost=1 --search_path="$WorkDir\$melfDir" `
    2>&1 | Tee-Object -FilePath "fh_$Version.txt"
$fhExit = $LASTEXITCODE
Write-Host "  exit=$fhExit"

# ---- RESULT ---------------------------------------------------------------
Write-Host ''
Write-Host ('=' * 70)
Write-Host '  RESULT'
Write-Host ('=' * 70)
Write-Host "  QSaharaServer exit : $qsExit"
Write-Host "  fh_loader exit     : $fhExit"

$qs = Get-Content "qs_$Version.txt" -Raw -ErrorAction SilentlyContinue
if ($qs -match 'Sahara protocol completed') {
    Write-Host '  Sahara             : COMPLETED' -ForegroundColor Green
} elseif ($qs -match 'bytes transferred') {
    Write-Host '  Sahara             : transferred, check tail'
} else {
    Write-Host '  Sahara             : did not complete' -ForegroundColor Yellow
}

$fh = Get-Content "fh_$Version.txt" -Raw -ErrorAction SilentlyContinue
if ($fh -match 'Failed to open com port') {
    Write-Host '  fh_loader          : could not open port' -ForegroundColor Yellow
} elseif ($fh -match 'All Finished Successfully|Finished') {
    Write-Host '  fh_loader          : appears to have completed' -ForegroundColor Green
}

Write-Host ''
Write-Host '  Full logs: qs_' $Version '.txt  fh_' $Version '.txt'
