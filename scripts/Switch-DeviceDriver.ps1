# Switch the Qualcomm 900E/9008 node between the COM driver and WinUSB.
#
# Why this is needed
# ------------------
# Sahara emits exactly one HELLO per boot and whoever opens the port consumes it.
# On this machine the Qualcomm serial driver (qcwdfserial) claims the node, so the
# first tool to open COM10 eats the packet and every later reader - including the
# vendor tool - gets silence. Measured repeatedly on 2026-11-11.
#
# libusb can only open the node when WinUSB owns it, and a fresh boot is the only
# way to get a new HELLO, so the sequence that works is:
#
#   1. switch to WinUSB
#   2. power cycle the tablet
#   3. catch the HELLO with the libusb client
#
# The switch is reversible: -To COM restores the Qualcomm driver, which is what
# QSaharaServer / fh_loader / QFIL need.
#
# Requires elevation (device driver changes).
#
# Usage
#   .\Switch-DeviceDriver.ps1 -Status
#   .\Switch-DeviceDriver.ps1 -To WinUSB
#   .\Switch-DeviceDriver.ps1 -To COM

param(
    [ValidateSet('WinUSB', 'COM')]
    [string]$To,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'driver_switch.log'

function Log($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -Path $log -Value $line
}

function Show-State {
    $nodes = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_05C6' }
    if (-not $nodes) {
        Log 'no VID_05C6 node present'
        return
    }
    foreach ($n in $nodes) {
        $key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$($n.InstanceId)"
        $svc = (Get-ItemProperty -Path $key -ErrorAction SilentlyContinue).Service
        $inf = (Get-ItemProperty -Path $key -ErrorAction SilentlyContinue).Driver
        Log ("{0}  service={1}  inf={2}  status={3}" -f $n.InstanceId, $svc, $inf, $n.Status)
    }
    Log ("COM ports: " + ((Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue |
        ForEach-Object { "$($_.DeviceID)=$($_.Name)" }) -join '; '))
}

Log '=== Switch-DeviceDriver ==='

# ---- elevation check ----
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Log 'ERROR: not elevated. Re-run this script from an Administrator PowerShell.'
    exit 1
}
Log "elevated as $($id.Name)"

if ($Status -or -not $To) {
    Show-State
    if (-not $To) { Log 'no -To given; nothing changed' }
    exit 0
}

# ---- locate the WinUSB driver package (libwdi / Zadig) ----
# pnputil is the supported way on this Windows build; /update-driver does not
# exist here (docs/07 F3), so we enumerate and then force on the live node.
$targetPids = @('PID_900E', 'PID_9008')

function Find-WinUsbInf {
    $cands = & pnputil /enum-drivers 2>&1
    $blocks = ($cands -join "`n") -split "`r?`n`r?`n"
    $found = @()
    foreach ($b in $blocks) {
        if ($b -match 'WinUSB' -and $b -match 'oem\d+\.inf') {
            $inf = [regex]::Match($b, '(oem\d+\.inf)').Groups[1].Value
            $found += $inf
        }
    }
    return $found | Select-Object -Unique
}

if ($To -eq 'WinUSB') {
    Log 'target: WinUSB (libusb)'

    $inf = Find-WinUsbInf
    if (-not $inf) {
        Log 'ERROR: no WinUSB driver package found in the driver store.'
        Log 'Install one first (Zadig, or libwdi) and re-run.'
        exit 1
    }
    Log ("WinUSB packages: " + ($inf -join ', '))

    foreach ($n in (Get-PnpDevice -PresentOnly | Where-Object {
                $_.InstanceId -match 'VID_05C6' })) {
        $key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$($n.InstanceId)"
        $cur = (Get-ItemProperty -Path $key -ErrorAction SilentlyContinue).Service
        Log "node $($n.InstanceId) currently service=$cur"
        if ($cur -eq 'WinUSB') { Log '  already WinUSB'; continue }

        # Preferred: ask PnP to rebind the node to the WinUSB package.
        foreach ($pkg in $inf) {
            Log "  trying $pkg"
            $out = & pnputil /add-driver "$env:SystemRoot\INF\$pkg" /install 2>&1
            Log ("  " + (($out -join ' ').Trim()))
        }
        # Force on the live instance; this is the route that worked before
        # (docs/07 F4: the COM packages outrank the libwdi ones, so a plain
        # rescan is not enough).
        $hwid = ($n.InstanceId -split '\\')[1]
        Log "  DiInstallDevice on $hwid"
        try {
            $out = & pnputil /force 2>&1
            Log ("  " + (($out -join ' ').Trim()))
        } catch { Log "  pnputil /force unavailable: $($_.Exception.Message)" }

        Log '  removing and rescanning the node'
        try {
            & pnputil /remove-device "$($n.InstanceId)" 2>&1 | ForEach-Object { Log "  $_" }
        } catch { Log "  remove-device failed: $($_.Exception.Message)" }
        Start-Sleep -Milliseconds 800
        & pnputil /scan-devices 2>&1 | ForEach-Object { Log "  $_" }
        Start-Sleep -Milliseconds 1200
    }

    Log ''
    Show-State
    Log 'If the service above is still qcwdfserial, the COM package still wins:'
    Log 'delete the competing oem*.inf and repeat, or bind WinUSB with Zadig once.'
    exit 0
}

if ($To -eq 'COM') {
    Log 'target: Qualcomm COM driver (qcwdfserial) - needed by QSaharaServer/fh_loader'

    # Find a Qualcomm serial INF in the driver store.
    $q = & pnputil /enum-drivers 2>&1
    $blocks = ($q -join "`n") -split "`r?`n`r?`n"
    $inf = @()
    foreach ($b in $blocks) {
        if ($b -match 'qc\w*ser' -and $b -match '(oem\d+\.inf)') {
            $inf += [regex]::Match($b, '(oem\d+\.inf)').Groups[1].Value
        }
    }
    $inf = $inf | Select-Object -Unique
    if (-not $inf) {
        Log 'ERROR: no Qualcomm serial package found. Install the Qualcomm USB drivers.'
        exit 1
    }
    Log ("Qualcomm packages: " + ($inf -join ', '))

    foreach ($n in (Get-PnpDevice -PresentOnly | Where-Object {
                $_.InstanceId -match 'VID_05C6' })) {
        Log "rebinding $($n.InstanceId)"
        try {
            & pnputil /remove-device "$($n.InstanceId)" 2>&1 | ForEach-Object { Log "  $_" }
        } catch { Log "  remove-device failed: $($_.Exception.Message)" }
        Start-Sleep -Milliseconds 800
        & pnputil /scan-devices 2>&1 | ForEach-Object { Log "  $_" }
        Start-Sleep -Milliseconds 1200
    }

    Log ''
    Show-State
    exit 0
}
