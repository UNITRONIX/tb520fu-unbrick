# One-shot attempt: QSaharaServer then fh_loader, nothing in between.
#
# The device allows ONE Sahara HELLO per power cycle. Any probe consumes it. So this
# script must not touch the device before it starts the real attempt, and must not
# touch it between QSaharaServer and fh_loader.
#
# Port numbers are read from the registry (passive - that does not open the device).

param(
    [string]$WorkDir = "C:\Users\UNITRONIX\Downloads\tb520fu-unbrick\com_attempt",
    [string]$Melf    = ".\image\xbl_s_devprg_ns.melf"
)

$ErrorActionPreference = "Continue"

function Get-QualcommPorts {
    $out = @{}
    $k = 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM'
    if (Test-Path $k) {
        (Get-ItemProperty $k).PSObject.Properties |
            Where-Object { $_.Name -notmatch '^PS' } |
            ForEach-Object {
                # \Device\QCUSB_COM10_1 = COM10
                if ($_.Name -match 'QCUSB_COM(\d+)') {
                    $out[[int]$Matches[1]] = $_.Value
                }
            }
    }
    return $out
}

Write-Host ("=" * 70)
Write-Host "  ONE-SHOT: QSaharaServer -> fh_loader, no probes in between"
Write-Host ("=" * 70)

# ---- passive port discovery ------------------------------------------------
$ports = Get-QualcommPorts
if ($ports.Count -eq 0) {
    Write-Host "No Qualcomm COM port present." -ForegroundColor Yellow
    Write-Host "The device may still be enumerating, or the driver is not bound."
    exit 1
}

Write-Host "`nQualcomm COM ports found (passive registry read):"
foreach ($n in ($ports.Keys | Sort-Object)) {
    Write-Host "  $($ports[$n])  (QCUSB_COM$n)"
}

$comPort = $ports[($ports.Keys | Sort-Object)[0]]
Write-Host "`nUsing $comPort" -ForegroundColor Cyan

# ---- find the melf ---------------------------------------------------------
if (-not (Test-Path (Join-Path $WorkDir $Melf))) {
    $alt = Join-Path $WorkDir "image\xbl_s_devprg_ns.melf"
    if (Test-Path $alt) { $Melf = "image\xbl_s_devprg_ns.melf" }
    else {
        Write-Host "melf not found under $WorkDir" -ForegroundColor Red
        exit 1
    }
}
Write-Host "Programmer: $Melf"

Set-Location $WorkDir

# ---- step 1: QSaharaServer ------------------------------------------------
Write-Host "`n$('-' * 70)"
Write-Host "  STEP 1: QSaharaServer  (this consumes the HELLO)"
Write-Host "$('-' * 70)"
$qs = Join-Path $WorkDir "QSaharaServer.exe"
& $qs -p "\\.\$comPort" -x -s "13:$Melf" -v 2
$qsExit = $LASTEXITCODE
Write-Host "`nQSaharaServer exit code: $qsExit"

# ---- step 2: immediately fh_loader ---------------------------------------
Write-Host "`n$('-' * 70)"
Write-Host "  STEP 2: fh_loader  (immediately, same port)"
Write-Host "$('-' * 70)"

# Re-read the port list WITHOUT opening the device: after a bump the port number
# changes, and the registry reflects that without us touching the USB node.
Start-Sleep -Seconds 3
$ports2 = Get-QualcommPorts
if ($ports2.Count -gt 0) {
    Write-Host "Ports now:"
    foreach ($n in ($ports2.Keys | Sort-Object)) { Write-Host "  $($ports2[$n])" }
    $comPort2 = $ports2[($ports2.Keys | Sort-Object)[0]]
} else {
    Write-Host "No Qualcomm port after step 1." -ForegroundColor Yellow
    $comPort2 = $comPort
}

Write-Host "`nUsing $comPort2 for fh_loader"
$fh = Join-Path $WorkDir "fh_loader.exe"
& $fh --port="\\.\$comPort2" --noprompt --showpercentagecomplete `
      --memoryname=UFS --zlpawarehost=1 --search_path="$WorkDir\image"
$fhExit = $LASTEXITCODE
Write-Host "`nfh_loader exit code: $fhExit"

# ---- results ---------------------------------------------------------------
Write-Host "`n$('=' * 70)"
Write-Host "  RESULT"
Write-Host "$('=' * 70)"
Write-Host "QSaharaServer: $qsExit"
Write-Host "fh_loader:     $fhExit"
Write-Host "`nport_trace.txt tail:"
$trace = Join-Path $WorkDir "port_trace.txt"
if (Test-Path $trace) {
    Get-Content $trace -Tail 25
} else {
    Write-Host "  (no trace file)"
}
