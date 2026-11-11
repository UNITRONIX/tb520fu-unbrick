# Remove the wedged devnode and rescan, with elevation.
#
# Why this is the last host-side option worth trying
# --------------------------------------------------
# docs/103 closed the IOCTL routes: RESET_HUB is accepted and does nothing, CYCLE_PORT
# is not implemented on this platform (err 50 on a free USB 3.0 root port). Those act on
# the HUB. This script acts on the DEVNODE instead:
#
#     pnputil /remove-device <instance>   drop the failed node entirely
#     pnputil /scan-devices               make the stack re-enumerate the bus
#
# A rescan asks the hub driver to re-report what is on each port, which makes the USB
# stack spend its descriptor-retry budget again on a device it had given up on. The
# registry shows that budget exhausted:
#
#     EnumerationRetryCount  4
#     EnumerationFailureCode 0x40010000
#
# If the device answers this time, it comes back as 900E or 9008 and the wedge is gone
# without anyone touching the cable. If it comes back as VID_0000 again, the wedge is in
# the device and not in the host - a definitive answer either way.
#
# Safety
# ------
# Removing a FAILED node is safe: it has no driver, no storage and no state to lose. The
# rescan re-creates it. Nothing on the tablet is written. The one risk is losing the node
# record if the device is genuinely dead - which would only mean re-plugging the cable,
# i.e. the action that was required anyway.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File Remove-WedgedNode.ps1
#   powershell -ExecutionPolicy Bypass -File Remove-WedgedNode.ps1 -DryRun

param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$here = $PSScriptRoot
$log = Join-Path $here 'remove_node.log'
Remove-Item $log -ErrorAction SilentlyContinue

# Find the instance id rather than hardcoding it: the tablet can appear on more than one
# port over time and each port has its own instance id.
$targets = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -match 'VID_0000&PID_0002' } |
    Select-Object -ExpandProperty InstanceId)

if (-not $targets -or $targets.Count -eq 0) {
    Write-Host 'no VID_0000&PID_0002 node present - nothing to remove'
    exit 0
}

foreach ($t in $targets) { Write-Host "target: $t" }

if ($DryRun) {
    Write-Host 'dry run: would run'
    foreach ($t in $targets) { Write-Host "  pnputil /remove-device `"$t`"" }
    Write-Host '  pnputil /scan-devices'
    exit 0
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("=== Remove-WedgedNode $(Get-Date -Format 'HH:mm:ss') ===Elevated: $(([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))")

foreach ($t in $targets) {
    $out = & pnputil /remove-device "$t" 2>&1
    $lines.Add("--- remove $t (exit $LASTEXITCODE) ---")
    $lines.Add(($out | Out-String).Trim())
}

Start-Sleep -Milliseconds 800
$out = & pnputil /scan-devices 2>&1
$lines.Add("--- scan-devices (exit $LASTEXITCODE) ---")
$lines.Add(($out | Out-String).Trim())

# Give the stack time to spend the retries before we look.
Start-Sleep -Seconds 8

$after = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -match 'VID_0000|VID_05C6' } |
    ForEach-Object { "$($_.Status)`t$($_.InstanceId)" })
$lines.Add('--- after 8 s ---')
if ($after.Count -eq 0) { $lines.Add('(no tablet node)') } else { $lines.Add(($after -join "`n")) }

$coms = @([System.IO.Ports.SerialPort]::GetPortNames())
$lines.Add("--- COM ports: $($coms -join ', ') ---")

$lines -join "`n" | Set-Content -Path $log -Encoding UTF8
Write-Host ''
$lines -join "`n"
