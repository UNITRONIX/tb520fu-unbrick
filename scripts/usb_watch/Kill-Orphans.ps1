// Kill-Orphans.ps1 - stop leftover EDL processes that hold the USB handle.
//
// Why this exists
// ---------------
// Leftover python processes from an earlier EDL session block all access to the
// device. The symptom looks like a driver fault:
//
//   usb_class(...).connect()  ->  Permission denied accessing 05c6:9008
//
// while raw libusb works fine once the orphans are gone. Hours were lost to this
// on TB520FU. Run this before every session.
//
// What it does
// ------------
// Lists python processes whose command line looks like an EDL client, prints them,
// and stops them. Does not touch unrelated python (MCP servers, language servers).
//
// Usage
// -----
//   powershell -ExecutionPolicy Bypass -File Kill-Orphans.ps1            # dry run
//   powershell -ExecutionPolicy Bypass -File Kill-Orphans.ps1 -Kill      # actually stop
//
// Must run elevated to stop processes started elevated.

[CmdletBinding()]
param(
    [switch]$Kill,
    [string]$LogPath = "$PSScriptRoot\kill_orphans.log"
)

$ErrorActionPreference = 'Continue'

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format o)  $Message"
    Write-Host $line
    if ($LogPath) { Add-Content -Path $LogPath -Value $line -Encoding utf8 }
}

# Patterns that identify an EDL client rather than an unrelated python process.
# Deliberately specific: the cost of killing the wrong process is a broken editor.
$edlPatterns = @(
    'sahara', 'firehose', 'edl', 'winusb', 'qfil', 'fh_loader',
    'abl_flash', 'flash9008', 'bump', 'catch_usb', 'raw_usb'
)

# Never touch these, regardless of command line.
$keepPatterns = @('mcp', 'ms-python', 'pylance', 'jupyter', 'ipykernel', 'cursor')

Write-Log "=== EDL orphan scan $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

$candidates = @()
$procs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    if ($keepPatterns | Where-Object { $cmd -match $_ }) { continue }
    if ($edlPatterns | Where-Object { $cmd -match $_ }) {
        $candidates += $p
    }
}

if (-not $candidates) {
    Write-Log "No EDL-looking python processes found."
} else {
    Write-Log "Found $($candidates.Count) candidate(s):"
    foreach ($p in $candidates) {
        $started = try { $p.CreationDate } catch { 'unknown' }
        Write-Log ("  PID {0,-6} started {1}  {2}" -f $p.ProcessId, $started, $p.CommandLine)
    }

    if ($Kill) {
        foreach ($p in $candidates) {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                Write-Log ("  PID {0} : stopped" -f $p.ProcessId)
            } catch {
                Write-Log ("  PID {0} : FAILED - {1}" -f $p.ProcessId, $_.Exception.Message)
            }
        }
        Start-Sleep -Seconds 2
    } else {
        Write-Log "Dry run. Re-run with -Kill to stop these."
    }
}

Write-Log "--- Qualcomm devices currently present ---"
$qc = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
      Where-Object { $_.InstanceId -match 'VID_05C6' }
if ($qc) {
    foreach ($d in $qc) {
        Write-Log ("  {0,-12} {1}  {2}" -f $d.Status, $d.FriendlyName, $d.InstanceId)
    }
} else {
    Write-Log "  none"
}

Write-Log "--- driver bound to the 9008/900e nodes ---"
foreach ($d in $qc) {
    if ($d.InstanceId -match 'PID_900[8E]') {
        try {
            $svc = (Get-PnpDeviceProperty -InstanceId $d.InstanceId `
                    -KeyName 'DEVPKEY_Device_Service' -ErrorAction Stop).Data
            Write-Log ("  {0} -> service '{1}'" -f $d.InstanceId, $svc)
            if ($svc -eq 'WinUSB') {
                Write-Log "     (WinUSB: use pyusb / edl.exe / raw libusb - NOT fh_loader/QFIL)"
            } elseif ($svc -match 'qcser|qcusbser') {
                Write-Log "     (Qualcomm serial: use QFIL / fh_loader / QSaharaServer - NOT pyusb)"
            }
        } catch {
            Write-Log ("  {0} -> service unknown" -f $d.InstanceId)
        }
    }
}

Write-Log "=== done ==="
