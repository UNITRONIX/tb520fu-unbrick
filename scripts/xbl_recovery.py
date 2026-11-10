import os

p = r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s.melf"
b = open(p, 'rb').read()

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

# The recovery-partition strings hint XBL can boot a recovery image on repeated
# boot failures. If so, the target may be recoverable WITHOUT ABL at all.
print("=== XBL: recovery / boot-failure logic ===")
keys = ["recovery", "Recovery", "abnormal", "force_panic", "boot_count",
        "bootable", "retry", "slot", "fail", "Fail", "panic", "Panic"]
seen = 0
for o, s in runs:
    if any(k in s for k in keys):
        print(f"  0x{o:07x}  {s[:100]}")
        seen += 1
        if seen > 60:
            break
print(f"\n-- lacznie trafien w oknie: {seen}")

# specifically the recovery partition machinery
print("\n=== dokladnie mechanika partycji recovery ===")
for o, s in runs:
    low = s.lower()
    if "recovery" in low or "panic" in low:
        print(f"  0x{o:07x}  {s[:110]}")
