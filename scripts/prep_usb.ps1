# Prepare a ROCKNIX-labelled FAT32 partition on the GoodRAM disk.
#
# NON-DESTRUCTIVE to Ventoy: it only SHRINKS the exFAT data partition by 2 GB
# and adds a new partition in the freed space. Existing files are not touched.
#
# Run elevated. Writes a log next to itself.

$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'prep_usb.log'
function Log($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Host $line
    Add-Content -Path $log -Value $line
}

$KIT = 'C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\mainline\out'
$IMAGE = Join-Path $KIT 'Image'
$DTB_SRC = Join-Path $KIT 'tb520fu_custom_from_stock.dtb'

Log '=== ROCKNIX USB prep ==='

# ---- 1. find the target disk: USB, ~119 GB, has a Ventoy exFAT partition ----
$cands = Get-Disk | Where-Object { $_.BusType -eq 'USB' -and $_.Size -gt 100GB -and $_.Size -lt 140GB }
if (-not $cands) { Log 'BLAD: nie znaleziono dysku USB ~119 GB'; exit 1 }
if ($cands.Count -gt 1) { Log 'BLAD: wiecej niz jeden kandydat - przerwan'; exit 1 }
$disk = $cands[0]
Log ("dysk: #{0} {1} {2:N2} GB" -f $disk.Number, $disk.FriendlyName, ($disk.Size/1GB))

$parts = Get-Partition -DiskNumber $disk.Number
$ventoy = $parts | Where-Object { $_.DriveLetter } | ForEach-Object {
    $v = Get-Volume -DriveLetter $_.DriveLetter -ErrorAction SilentlyContinue
    if ($v -and $v.FileSystemLabel -eq 'Ventoy') { [pscustomobject]@{ Part = $_; Vol = $v } }
}
if (-not $ventoy) { Log 'BLAD: nie znaleziono partycji z etykieta "Ventoy" - przerwan'; exit 1 }
$vp = $ventoy.Part
Log ("partycja Ventoy: {0}: {1} fs={2} size={3:N2} GB free={4:N2} GB" -f `
     $vp.DriveLetter, $ventoy.Vol.FileSystemLabel, $ventoy.Vol.FileSystem,
     ($ventoy.Vol.Size/1GB), ($ventoy.Vol.SizeRemaining/1GB))

# ---- 2. already done? ----
$existing = $parts | ForEach-Object {
    $v = Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.PartitionNumber -eq $_.PartitionNumber }
}
$already = Get-Volume | Where-Object { $_.FileSystemLabel -eq 'ROCKNIX' }
if ($already) {
    Log ("partycja ROCKNIX juz istnieje: {0}: {1} fs={2}" -f $already.DriveLetter, $already.FileSystemLabel, $already.FileSystem)
    $target = $already
} else {
    # ---- 3. shrink exFAT by 2 GB ----
    $shrink = 2048MB
    $newSize = $vp.Size - $shrink
    Log ("zmniejszam {0}: z {1:N2} GB do {2:N2} GB" -f $vp.DriveLetter, ($vp.Size/1GB), ($newSize/1GB))
    try {
        Resize-Partition -DiskNumber $disk.Number -PartitionNumber $vp.PartitionNumber -Size $newSize
        Log '  shrink OK'
    } catch {
        Log ("  BLAD shrink: " + $_.Exception.Message)
        Log '  przerywam - nic nie zostalo zmienione poza ewentualnym shrinkiem'
        exit 1
    }

    # ---- 4. new FAT32 partition labelled ROCKNIX ----
    Log 'tworze partycje FAT32 z etykieta ROCKNIX'
    $np = New-Partition -DiskNumber $disk.Number -UseMaximumSize -AssignDriveLetter
    Log ("  nowa partycja: {0}:" -f $np.DriveLetter)
    Format-Volume -DriveLetter $np.DriveLetter -FileSystem FAT32 -NewFileSystemLabel 'ROCKNIX' -Confirm:$false | Out-Null
    Log '  format OK'
    Start-Sleep -Seconds 2
    $target = Get-Volume -DriveLetter $np.DriveLetter
}

$dst = "$($target.DriveLetter):\"
Log ("cel: {0}  fs={1}  label={2}" -f $dst, $target.FileSystem, $target.FileSystemLabel)

# ---- 5. copy payload ----
if (-not (Test-Path $IMAGE)) { Log "BLAD: brak $IMAGE"; exit 1 }
if (-not (Test-Path $DTB_SRC)) { Log "BLAD: brak $DTB_SRC"; exit 1 }

New-Item -ItemType Directory -Force -Path (Join-Path $dst 'extlinux') | Out-Null

Log 'kopiuje Image (kernel 7.2.6)'
Copy-Item $IMAGE (Join-Path $dst 'Image') -Force
Log 'kopiuje DTB'
Copy-Item $DTB_SRC (Join-Path $dst 'tb520fu.dtb') -Force

$conf = @'
DEFAULT linux
PROMPT 1
TIMEOUT 10

LABEL linux
    MENU LABEL TB520FU mainline 7.2.6 (diagnostyka)
    LINUX /Image
    FDT /tb520fu.dtb
    APPEND console=ttyMSM0,115200n8 earlycon loglevel=8 ignore_loglevel
'@
Set-Content -Path (Join-Path $dst 'extlinux\extlinux.conf') -Value $conf -Encoding ASCII
Log 'extlinux.conf zapisany'

# secondary location some loaders look at
New-Item -ItemType Directory -Force -Path (Join-Path $dst 'boot\extlinux') | Out-Null
Copy-Item (Join-Path $dst 'extlinux\extlinux.conf') (Join-Path $dst 'boot\extlinux\extlinux.conf') -Force

# ---- 6. verify ----
Log ''
Log '=== WERYFIKACJA ==='
Get-ChildItem $dst -Recurse -File | ForEach-Object {
    Log ("  {0,-28} {1,12} B" -f $_.FullName.Substring($dst.Length), $_.Length)
}
$v = Get-Volume -DriveLetter $target.DriveLetter
Log ("etykieta={0} fs={1} free={2:N2} GB" -f $v.FileSystemLabel, $v.FileSystem, ($v.SizeRemaining/1GB))
Log ''
Log '=== GOTOWE ==='
Log 'Test: wloz dysk do tabletu, wlacz tablet, PATRZ NA DIODE DYSKU.'
Log 'Miganie diody = ABL wszedl w tryb hosta i czytal nosnik.'
Log 'Brak migania przez 60 s = ABL nigdy nie doszedl do obslugi USB host.'
