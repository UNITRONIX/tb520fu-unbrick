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

print("=== BUTTON COMBOS supported by XBL ===")
for o, s in runs:
    if ("s2-" in s) or ("kpdpwr" in s) or ("resin" in s) or ("vol" in s.lower() and "-" in s):
        print(f"  0x{o:07x}  {s[:90]}")

print("\n=== PWR-KEY HOLD behaviour ===")
for o, s in runs:
    if "PwrKey" in s or "hold" in s.lower() or "duration" in s.lower():
        print(f"  0x{o:07x}  {s[:110]}")

print("\n=== dload_entry_count / forced dload ===")
for o, s in runs:
    if "dload" in s.lower() or "fedl" in s.lower():
        print(f"  0x{o:07x}  {s[:110]}")
