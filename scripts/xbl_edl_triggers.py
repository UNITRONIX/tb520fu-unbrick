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

# "abnormal reset status" is the Android A/B retry machinery: XBL counts failed
# boots and can fall back to another partition. Also look for QFIL/EDL triggers
# that XBL itself honours - those would give a write path without ABL.
groups = {
    "ABNORMAL RESET / retry counter": ["abnormal", "Abnormal", "reset_status", "bootfail",
                                       "boot_fail", "retry", "crash_count", "max_retry"],
    "EXPLICIT EDL / DLOAD triggers": ["dload", "DLOAD", "force_edl", "force_dl",
                                      "edl", "EDL", "emergency", "Emergency",
                                      "sahara", "Sahara"],
    "BUTTONS (XBL reads keys itself)": ["Button", "button", "Key", "key_map",
                                        "KeyMap", "pm_resin", "resin", "gpio_key"],
    "CHARGER / battery screen": ["charge_screen", "low_battery", "LowBatt",
                                 "battery_screen", "offmode", "OffMode"],
}
for title, keys in groups.items():
    print("=" * 76)
    print(title)
    print("-" * 76)
    n = 0
    for o, s in runs:
        if any(k in s for k in keys):
            print(f"  0x{o:07x}  {s[:100]}")
            n += 1
            if n >= 30:
                print("  ...")
                break
    if n == 0:
        print("  (brak)")
    print()
