# Switch the Qualcomm 900E/9008 node between the Qualcomm COM driver and WinUSB.
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
# Method
# ------
# pnputil /update-driver does not exist on this Windows build, and remove-device
# plus rescan does not rebind: the Qualcomm COM package simply wins the ranking
# again. docs/07 F3/F4 recorded the same thing. The route that works here is
# UpdateDriverForPlugAndPlayDevicesW with INSTALLFLAG_FORCE, called on the live
# device instance with the full path to the WinUSB INF from the driver store.
#
# Requires elevation. Reversible: -To COM deletes the libwdi packages and rescans,
# which lets the Qualcomm driver take the node back for QSaharaServer / fh_loader.
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

# ---- P/Invoke: the documented way to force a driver on a live instance --------
if (-not ('NewDevApi' -as [type])) {
    Add-Type -Namespace '' -Name 'NewDevApi' -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("newdev.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern bool UpdateDriverForPlugAndPlayDevicesW(
    System.IntPtr hwndParent,
    string HardWareId,
    string FullInfPath,
    uint InstallFlags,
    out bool bRebootRequired);

[System.Runtime.InteropServices.DllImport("setupapi.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern bool SetupDiGetINFClassW(
    string InfName, ref System.Guid ClassGuid, System.Text.StringBuilder ClassName,
    uint ClassNameSize, out uint RequiredSize);
'@
}

$INSTALLFLAG_FORCE = 0x00000001
$INSTALLFLAG_NONINTERACTIVE = 0x00000004

function Get-QualcommNodes {
    Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_05C6' }
}

function Get-NodeService($instanceId) {
    $key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$instanceId"
    (Get-ItemProperty -Path $key -ErrorAction SilentlyContinue).Service
}

function Show-State {
    $nodes = Get-QualcommNodes
    if (-not $nodes) { Log 'no VID_05C6 node present'; return }
    foreach ($n in $nodes) {
        $svc = Get-NodeService $n.InstanceId
        Log ("{0}  service={1}  status={2}" -f $n.InstanceId, $svc, $n.Status)
    }
    $ports = Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue |
        ForEach-Object { "$($_.DeviceID) ($($_.Name))" }
    Log ("COM ports: " + ($ports -join '; '))
}

# Find an INF package in the driver store by provider + the PID it covers.
function Find-DriverInf {
    param([string]$ProviderPattern, [string]$PidPattern)
    $raw = & pnputil /enum-drivers 2>&1
    $blocks = ($raw -join "`n") -split "`r?`n`r?`n"
    $hits = @()
    foreach ($b in $blocks) {
        $pub = [regex]::Match($b, 'Published Name:\s+(\S+\.inf)')
        if (-not $pub.Success) { continue }
        $prov = [regex]::Match($b, 'Provider Name:\s+(.+)')
        $sign = [regex]::Match($b, 'Signer Name:\s+(.+)')
        $text = $b
        if ($text -match $ProviderPattern -and $text -match $PidPattern) {
            $hits += [pscustomobject]@{
                Published = $pub.Groups[1].Value.Trim()
                Provider  = if ($prov.Success) { $prov.Groups[1].Value.Trim() } else { '' }
                Signer    = if ($sign.Success) { $sign.Groups[1].Value.Trim() } else { '' }
            }
        }
    }
    $hits | Sort-Object Published -Unique
}

Log '=== Switch-DeviceDriver ==='

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Log 'ERROR: not elevated.'
    Log 'Open PowerShell with "Run as administrator", cd to this folder, and re-run.'
    exit 1
}
Log "elevated as $($id.Name)"

if ($Status -or -not $To) {
    Show-State
    Log '--- available packages ---'
    foreach ($h in (Find-DriverInf -ProviderPattern 'libwdi' -PidPattern '900E|9008')) {
        Log ("  WinUSB-ish: {0}  provider={1}" -f $h.Published, $h.Provider)
    }
    foreach ($h in (Find-DriverInf -ProviderPattern 'Qualcomm' -PidPattern '9008|900E')) {
        Log ("  Qualcomm  : {0}  provider={1}" -f $h.Published, $h.Provider)
    }
    if (-not $To) { Log 'no -To given; nothing changed' }
    exit 0
}

if ($To -eq 'WinUSB') {
    Log 'target: WinUSB (for libusb / pyusb)'

    $infNames = Find-DriverInf -ProviderPattern 'libwdi' -PidPattern '900E'
    if (-not $infNames) { $infNames = Find-DriverInf -ProviderPattern 'libwdi' -PidPattern '9008' }
    if (-not $infNames) {
        Log 'ERROR: no libwdi WinUSB package covering 900E/9008 in the driver store.'
        exit 1
    }

    foreach ($n in (Get-QualcommNodes)) {
        $svc = Get-NodeService $n.InstanceId
        Log "node $($n.InstanceId) service=$svc"
        if ($svc -eq 'WinUSB') { Log '  already WinUSB'; continue }

        $hwid = ($n.InstanceId -split '\\')[1]   # e.g. USB\VID_05C6&PID_900E
        $ok = $false
        foreach ($pkg in $infNames) {
            $infPath = Join-Path $env:SystemRoot "INF\$($pkg.Published)"
            if (-not (Test-Path $infPath)) { Log "  $infPath missing"; continue }
            Log "  forcing $($pkg.Published) on $hwid"
            $reboot = $false
            $res = [NewDevApi]::UpdateDriverForPlugAndPlayDevicesW(
                [IntPtr]::Zero, $hwid, $infPath,
                ($INSTALLFLAG_FORCE -bor $INSTALLFLAG_NONINTERACTIVE), [ref]$reboot)
            $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            Log ("  result={0} reboot={1} win32err={2}" -f $res, $reboot, $err)
            if ($res) { $ok = $true; break }
        }
        if (-not $ok) {
            Log '  forcing failed - deleting the competing Qualcomm package and retrying'
            foreach ($q in (Find-DriverInf -ProviderPattern 'Qualcomm' -PidPattern '900E')) {
                Log "  pnputil /delete-driver $($q.Published) /uninstall /force"
                & pnputil /delete-driver $q.Published /uninstall /force 2>&1 |
                    ForEach-Object { Log "    $_" }
            }
            & pnputil /scan-devices 2>&1 | ForEach-Object { Log "    $_" }
            Start-Sleep -Milliseconds 1500
        }
    }

    Log ''
    Show-State
    $svc = (Get-QualcommNodes | ForEach-Object { Get-NodeService $_.InstanceId }) -join ','
    if ($svc -eq 'WinUSB') {
        Log 'SUCCESS: node is on WinUSB. Power cycle the tablet, then run the libusb catcher.'
    } else {
        Log 'STILL on a non-WinUSB service. Bind it once with Zadig (Options > List All Devices,'
        Log 'select 05C6:900E, choose WinUSB) - that is a one-time click and fully reversible.'
    }
    exit 0
}

if ($To -eq 'COM') {
    Log 'target: Qualcomm COM driver (for QSaharaServer / fh_loader / QFIL)'
    $removed = 0
    foreach ($h in (Find-DriverInf -ProviderPattern 'libwdi' -PidPattern '900E|9008')) {
        Log "deleting $($h.Published)"
        & pnputil /delete-driver $h.Published /uninstall /force 2>&1 |
            ForEach-Object { Log "  $_" }
        $removed++
    }
    if ($removed -eq 0) { Log 'no libwdi packages to remove' }
    & pnputil /scan-devices 2>&1 | ForEach-Object { Log "  $_" }
    Start-Sleep -Milliseconds 2000
    Log ''
    Show-State
    exit 0
}
