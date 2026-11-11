# Cycle the port the tablet is on, with elevation.
#
# Why a separate script: IOCTL_USB_CYCLE_PORT returns ERROR_INVALID_PARAMETER (87) for a
# non-administrator, which is easy to misread as "this hub does not support it". The call
# needs admin rights, so this wrapper re-launches the Python tool with RunAs.
#
# Why cmd /c with a redirect instead of -RedirectStandardOutput: PowerShell 5.1 refuses
# `-Verb RunAs` together with redirection ("Parameter set cannot be resolved"), because
# elevating and capturing a handle belong to different parameter sets. Routing through
# cmd keeps both: the elevated process gets the redirect, and the log survives the window
# closing.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File Cycle-TabletPort.ps1
#   powershell -ExecutionPolicy Bypass -File Cycle-TabletPort.ps1 -Port 4 -Hub "8&1b878445"
#   powershell -ExecutionPolicy Bypass -File Cycle-TabletPort.ps1 -ResetHub

param(
    [int]$Port = 4,
    [string]$Hub = "8&1b878445",
    [switch]$ResetHub
)

$ErrorActionPreference = 'Continue'
$here = $PSScriptRoot
$log = Join-Path $here 'cycle_out.log'
Remove-Item $log -ErrorAction SilentlyContinue

$mode = if ($ResetHub) { '--reset-hub' } else { '--cycle' }
$py = Join-Path $here 'reset_port.py'

# Quote the hub: it contains '&', which cmd would otherwise read as a command separator.
$inner = "python `"$py`" $mode --port $Port --hub `"$Hub`" > `"$log`" 2>&1"
Write-Host "elevating: $inner"

$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $inner -Verb RunAs -Wait -PassThru
Write-Host "elevated exit code: $($p.ExitCode)"
Write-Host ''

if (Test-Path $log) {
    Get-Content $log
} else {
    Write-Host 'no log produced - the elevated process did not run (UAC declined?)'
}
