# FORMAT the GoodRAM disk to a clean ROCKNIX-ready layout.
#
# DESTRUCTIVE: wipes the whole disk #6 (Ventoy + all files, 19.84 GB used).
# Explicitly authorised by the owner.
#
# Layout produced:
#   part 1: FAT32, label ROCKNIX  <- what the ABL looks for
#   part 2: rest, exFAT, label DATA
#
# Payload on ROCKNIX:
#   /Image, /tb520fu.dtb, /extlinux/extlinux.conf   (raw kernel path)
#   /EFI/BOOT/BOOTAA64.EFI                          (EFI stub path, if buildable)
#
# Run elevated.

$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'format_usb.log'
function Log($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -Path $log -Value $line
}

$DISK = 6
$SRC  = 'C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\mainline\out'
$IMAGE = Join-Path $SRC 'Image'
$DTB   = Join-Path $SRC 'tb520fu_custom_from_stock.dtb'
$EFI   = 'C:\Users\UNITRONIX\Downloads\tb520fu-unbrick\build\BOOTAA64.EFI'

Log '=== FORMAT + ROCKNIX prep (DESTRUCTIVE) ==='

# ---- safety: confirm identity before wiping ----
$d = Get-Disk -Number $DISK
Log ("dysk #{0}: {1} {2:N2} GB bus={3}" -f $d.Number, $d.FriendlyName, ($d.Size/1GB), $d.BusType)
if ($d.BusType -ne 'USB')            { Log 'ABORT: to nie jest dysk USB'; exit 1 }
if ($d.Size -lt 100GB -or $d.Size -gt 140GB) { Log 'ABORT: nieoczekiwany rozmiar'; exit 1 }
if ($d.IsBoot -or $d.IsSystem)       { Log 'ABORT: dysk systemowy!'; exit 1 }

# ---- offline any volume so nothing holds the disk ----
Get-Partition -DiskNumber $DISK -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.DriveLetter) {
        Log ("odmontowuje {0}:" -f $_.DriveLetter)
        try { Remove-PartitionAccessPath -DiskNumber $DISK -PartitionNumber $_.PartitionNumber -AccessPath "$($_.DriveLetter):\" -ErrorAction Stop } catch { Log ("  uwaga: " + $_.Exception.Message) }
    }
}

# ---- wipe ----
Log 'czyszcze dysk (Clear-Disk)'
Clear-Disk -Number $DISK -RemoveData -RemoveOEM -Confirm:$false
Log '  wyczyszczony'

Initialize-Disk -Number $DISK -PartitionStyle GPT
Log 'GPT zainicjowany'

# ---- partition 1: ROCKNIX FAT32, 8 GB ----
$p1 = New-Partition -DiskNumber $DISK -Size 8GB -AssignDriveLetter
Log ("partycja 1: {0}: 8 GB" -f $p1.DriveLetter)
Format-Volume -DriveLetter $p1.DriveLetter -FileSystem FAT32 -NewFileSystemLabel 'ROCKNIX' -Confirm:$false | Out-Null
Log '  FAT32 / ROCKNIX OK'
$R = "$($p1.DriveLetter):\"

# ---- partition 2: rest as DATA ----
$p2 = New-Partition -DiskNumber $DISK -UseMaximumSize -AssignDriveLetter
Log ("partycja 2: {0}: reszta" -f $p2.DriveLetter)
Format-Volume -DriveLetter $p2.DriveLetter -FileSystem exFAT -NewFileSystemLabel 'DATA' -Confirm:$false | Out-Null
Log '  exFAT / DATA OK'

Start-Sleep -Seconds 2

# ---- payload: raw kernel path ----
New-Item -ItemType Directory -Force -Path (Join-Path $R 'extlinux') | Out-Null
Log 'kopiuje Image'
Copy-Item $IMAGE (Join-Path $R 'Image') -Force
Log 'kopiuje DTB'
Copy-Item $DTB (Join-Path $R 'tb520fu.dtb') -Force

$conf = @'
DEFAULT linux
PROMPT 1
TIMEOUT 10

LABEL linux
    MENU LABEL TB520FU mainline 7.2.6
    LINUX /Image
    FDT /tb520fu.dtb
    APPEND console=ttyMSM0,115200n8 earlycon loglevel=8 ignore_loglevel
'@
Set-Content -Path (Join-Path $R 'extlinux\extlinux.conf') -Value $conf -Encoding ASCII
# some loaders also probe /boot/extlinux/extlinux.conf
New-Item -ItemType Directory -Force -Path (Join-Path $R 'boot\extlinux') | Out-Null
Copy-Item (Join-Path $R 'extlinux\extlinux.conf') (Join-Path $R 'boot\extlinux\extlinux.conf') -Force
Log 'extlinux.conf zapisany (2 lokalizacje)'

# ---- payload: EFI path, if the stub was built ----
if (Test-Path $EFI) {
    New-Item -ItemType Directory -Force -Path (Join-Path $R 'EFI\BOOT') | Out-Null
    Copy-Item $EFI (Join-Path $R 'EFI\BOOT\BOOTAA64.EFI') -Force
    Log 'skopiowano EFI/BOOT/BOOTAA64.EFI'
} else {
    Log 'brak BOOTAA64.EFI - sciezka EFI pominięta (zostanie zbudowana osobno)'
}

# ---- verify ----
Log ''
Log '=== WERYFIKACJA ==='
Get-Partition -DiskNumber $DISK | Select-Object PartitionNumber,DriveLetter,@{n='GB';e={[math]::Round($_.Size/1GB,2)}} | ForEach-Object {
    Log ("  part {0}  {1}:  {2} GB" -f $_.PartitionNumber, $_.DriveLetter, $_.GB)
}
Get-ChildItem $R -Recurse -File | ForEach-Object {
    Log ("  {0,-32} {1,12} B" -f $_.FullName.Substring($R.Length), $_.Length)
}
$v = Get-Volume -DriveLetter $p1.DriveLetter
Log ("ROCKNIX: label='{0}' fs={1} free={2:N2} GB" -f $v.FileSystemLabel, $v.FileSystem, ($v.SizeRemaining/1GB))
Log ''
Log '=== GOTOWE ==='
