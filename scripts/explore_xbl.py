import os, re

p = r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s.melf"
b = open(p, 'rb').read()
print(f"xbl_s.melf  {len(b)} B")

runs, cur, start = [], bytearray(), 0
for i, c in enumerate(b):
    if 32 <= c < 127:
        if not cur:
            start = i
        cur.append(c)
    else:
        if len(cur) >= 5:
            runs.append((start, cur.decode('ascii', 'ignore')))
        cur = bytearray()

print(f"ascii runs >=5: {len(runs)}\n")

def show(title, pats, limit=18):
    print("=" * 74)
    print(title)
    print("-" * 74)
    seen = 0
    for o, s in runs:
        low = s.lower()
        if any(pt.lower() in low for pt in pats):
            print(f"  0x{o:07x}  {s[:96]}")
            seen += 1
            if seen >= limit:
                print(f"  ... (ucieto na {limit})")
                break
    if seen == 0:
        print("  (brak)")
    print()

# who loads what / boot decision
show("1. BOOT FLOW / wybor obrazu", [
    "boot_", "Boot", "select", "Select", "devinfo", "slot",
    "aboot", "abl", "ABL", "load_image", "LoadImage",
    "boot_mode", "BootMode", "fastboot", "Fastboot",
], 30)

show("2. PARTYCJE / storage", [
    "partition", "Partition", "lun", "LUN", "ufs", "UFS",
    "gpt", "GPT", "LoadImageAndAuth", "ImageAuth",
], 20)

show("3. CRASHDUMP / PIL / reset", [
    "crash", "Crash", "dump", "Dump", "PIL", "pil",
    "DEAD", "dead end", "subsys", "SSR", "fatal", "Fatal",
], 25)

show("4. DISPLAY / splash (kto rysuje ekran)", [
    "splash", "Splash", "logo", "Logo", "display", "Display",
    "framebuffer", "FB", "panel", "dsi", "DSI", "charge_screen",
], 25)
