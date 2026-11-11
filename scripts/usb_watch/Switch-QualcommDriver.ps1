# Switch the tablet to the Qualcomm COM driver world
#
# Why: fh_loader / QSaharaServer / QFIL speak to the device over a COM port. They
# cannot open a WinUSB node. The tablet has always been on WinUSB, so Lenovo's own
# toolchain has never actually been given a chance on this unit.
# See docs/24-lenovo-tools-com-world.md.
#
# Requires: Administrator (driver binding needs elevation).
#
# Reversible: -RestoreWinUSB rebinds the WinUSB driver that was there before.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File Switch-QualcommDriver.ps1
#   powershell -ExecutionPolicy Bypass -File Switch-QualcommDriver.ps1 -RestoreWinUSB

[CmdletBinding()]
param(
    [switch]$RestoreWinUSB,
    [string]$SerialInf = "C:\Program Files\Qualcomm\Qualcomm USB Drivers\drivers\qcwdfser.inf",
    [string]$TargetPid = "9008"
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "ERROR: this script needs Administrator rights." -ForegroundColor Red
        Write-Host "       Right-click PowerShell -> Run as administrator, then re-run."
        exit 1
    }
}

function Show-Node {
    param([string]$Pid)
    $dev = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match "VID_05C6&PID_$Pid" }
    if (-not $dev) {
        Write-Host "  not present" -ForegroundColor DarkGray
        return $null
    }
    foreach ($d in $dev) {
        $svc = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data
        $inf = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_DriverInfPath' -ErrorAction SilentlyContinue).Data
        Write-Host ("  {0}  service={1}  inf={2}" -f $d.InstanceId, $svc, $inf)
    }
    return $dev
}

Assert-Admin

Write-Host "=" * 72
if ($RestoreWinUSB) {
    Write-Host "  RESTORE: rebind the node to WinUSB"
} else {
    Write-Host "  SWITCH: bind 05C6:$TargetPid to the Qualcomm serial driver"
}
Write-Host "=" * 72

# ---- current state ---------------------------------------------------------
Write-Host "`nCurrent node:"
$dev = Show-Node -Pid $TargetPid
if (-not $dev) {
    Write-Host "`nThe device is not at $TargetPid." -ForegroundColor Yellow
    if (-not $RestoreWinUSB) {
        Write-Host "Bump the tablet to 9008 first, then re-run. Suggested sequence:"
        Write-Host "  python scripts\single_session.py upload --melf <rom>\image\xbl_s_devprg_ns.melf"
        Write-Host "  (or use the bump portion of any script that reaches 9008)"
    }
    exit 1
}

# ---- restore path ----------------------------------------------------------
if ($RestoreWinUSB) {
    Write-Host "`nRebinding to WinUSB..."

    # Find a WinUSB package that matches this hardware id. The oem66.inf package was
    # what owned the node originally; rather than hard-coding it, ask Windows which
    # compatible driver packages exist.
    $hwid = "USB\VID_05C6&PID_$TargetPid"

    $candidate = $null
    Get-ChildItem "C:\Windows\INF\oem*.inf" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($script:candidate) { return }
        $t = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
        if ($t -match [regex]::Escape($hwid) -and $t -match 'winusb') {
            $script:candidate = $_.FullName
        }
    }

    if (-not $candidate) {
        Write-Host "  No WinUSB INF found for $hwid." -ForegroundColor Yellow
        Write-Host "  Use Zadig to rebind WinUSB manually, or reinstall the Lenovo driver set."
        exit 1
    }

    Write-Host "  using $candidate"
    pnputil /add-driver $candidate /install
    foreach ($d in $dev) {
        $inst = Get-PnpDevice -InstanceId $d.InstanceId
        Write-Host "  rescanning $($d.InstanceId)"
        pnputil /scan-devices | Out-Null
    }

    Write-Host "`nAfter rebinding:" -ForegroundColor Green
    Show-Node -Pid $TargetPid | Out-Null
    Write-Host "`nA WinUSB node should show service=WinUSB again."
    exit 0
}

# ---- switch path -----------------------------------------------------------
if (-not (Test-Path $SerialInf)) {
    Write-Host "`nSerial INF not found: $SerialInf" -ForegroundColor Red
    Write-Host "Look for it under 'C:\Program Files\Qualcomm\Qualcomm USB Drivers\drivers'."
    exit 1
}

$infText = Get-Content $SerialInf -Raw
if ($infText -notmatch "PID_$TargetPid") {
    Write-Host "`nThat INF does not list PID_$TargetPid - it would not match." -ForegroundColor Red
    exit 1
}
Write-Host "`nINF lists PID_$TargetPid  - good."

Write-Host "`nStaging and installing the driver package..."
pnputil /add-driver $SerialInf /install
if ($LASTEXITCODE -ne 0) {
    Write-Host "pnputil returned $LASTEXITCODE" -ForegroundColor Yellow
}

Write-Host "`nForcing the driver onto the live node..."
foreach ($d in $dev) {
    Write-Host "  $($d.InstanceId)"
    # devcon is not present by default; pnputil can update a device with /add-driver
    # once the package is staged and the hardware id matches.
    pnputil /scan-devices | Out-Null
    Start-Sleep -Seconds 2
}

Write-Host "`nAfter switching:" -ForegroundColor Green
Show-Node -Pid $TargetPid | Out-Null

Write-Host "`nLooking for a new COM port..."
$ports = Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue |
    Select-Object DeviceID, Name, Description
if ($ports) {
    $ports | Format-Table -AutoSize
} else {
    Write-Host "  none"
}

Write-Host @"

Next steps, in order:
  1. A Qualcomm COM port must now exist (e.g. COM5). If none appeared, stop:
     without a port neither QSaharaServer nor fh_loader can work.
  2. QSaharaServer.exe -p \\.\COMx -s 13:<rom>\image\xbl_s_devprg_ns.melf
  3. fh_loader.exe --port=\\.\COMx --search_path=<rom>\image --memoryname=UFS ...

To undo: re-run this script with -RestoreWinUSB
"@
