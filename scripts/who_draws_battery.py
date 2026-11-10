import os, re

# Who draws the offline-charging battery screen: XBL or ABL?
# If XBL does it, ABL never runs -> explains no menu, no fastboot, everything.

cands = {
    "xbl_s.melf (XBL + firehose)":
        r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s.melf",
    "abl.elf (stock ABL)":
        r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\abl.elf",
    "ROCKNIX ABL":
        r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\abl_rocknix_sm8650\abl_signed-SM8650.elf",
}

PATTERNS = [
    "charg", "Charg", "CHARGE", "battery", "Battery", "BATT",
    "offmode", "OffMode", "offline", "LowBattery", "low_batt",
    "charging", "PON", "shutdown", "Shutdown",
    "fastboot", "Fastboot", "FASTBOOT",
    "Booting", "boot_linux", "BootLinux", "LinuxLoader",
    "android", "Android", "ANDROID",
]

for label, p in cands.items():
    if not os.path.exists(p):
        print(f"--- {label}: BRAK {p}\n")
        continue
    b = open(p, 'rb').read()
    print("=" * 74)
    print(f"{label}   {len(b)} B")

    # ascii runs
    runs, cur, start = [], bytearray(), 0
    for i, c in enumerate(b):
        if 32 <= c < 127:
            if not cur:
                start = i
            cur.append(c)
        else:
            if len(cur) >= 4:
                runs.append((start, cur.decode('ascii', 'ignore')))
            cur = bytearray()
    if len(cur) >= 4:
        runs.append((start, cur.decode('ascii', 'ignore')))

    print(f"ascii runs >=4: {len(runs)}")
    found = {}
    for o, s in runs:
        for pat in PATTERNS:
            if pat in s:
                found.setdefault(pat, []).append((o, s))
    if not found:
        print("  *** ZERO trafien - plik prawdopodobnie zaszyfrowany/kompresowany ***")
    for pat in PATTERNS:
        if pat in found:
            ex = found[pat][:3]
            print(f"  {pat:14s} x{len(found[pat]):<4d}  " +
                  " | ".join(f"0x{o:x}:{s[:44]}" for o, s in ex))
    print()
