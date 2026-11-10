import os

p = r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s.melf"
b = open(p, 'rb').read()

# The XBL carries its own DT fragments. Find the keys/buttons block and the
# fedl_timeout block, and dump nearby text so the exact combo is visible.
for needle in [b"/soc/buttons/buttons-config", b"/soc/buttons/platform-key-maps",
               b"/sw/boot/fedl_timeout", b"s2-kpdpwr-resin", b"boot_fedl_check"]:
    i = b.find(needle)
    print("=" * 74)
    print(f"{needle.decode()}  @ 0x{i:x}" if i >= 0 else f"{needle.decode()}  NIE ZNALEZIONO")
    if i < 0:
        continue
    lo = max(0, i - 300)
    hi = min(len(b), i + 500)
    chunk = b[lo:hi]

    # print printable runs in the neighbourhood, with offsets
    cur, start = bytearray(), 0
    for j, c in enumerate(chunk):
        if 32 <= c < 127:
            if not cur:
                start = j
            cur.append(c)
        else:
            if len(cur) >= 3:
                print(f"  0x{lo+start:07x}  {cur.decode('ascii','ignore')[:110]}")
            cur = bytearray()
    if len(cur) >= 3:
        print(f"  0x{lo+start:07x}  {cur.decode('ascii','ignore')[:110]}")
print()
