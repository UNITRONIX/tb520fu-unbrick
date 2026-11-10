import struct, sys, os

def strs(b, minlen=6):
    out, cur, start = [], bytearray(), 0
    for i, c in enumerate(b):
        if 32 <= c < 127:
            if not cur:
                start = i
            cur.append(c)
        else:
            if len(cur) >= minlen:
                out.append((start, cur.decode('ascii', 'ignore')))
            cur = bytearray()
    if len(cur) >= minlen:
        out.append((start, cur.decode('ascii', 'ignore')))
    return out

files = {
    "stock abl.elf (ROM ZUI 18.5)": r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\abl.elf",
    "ROCKNIX ABL (qtestsign)": r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\abl_rocknix_sm8650\abl_signed-SM8650.elf",
}

for label, p in files.items():
    if not os.path.exists(p):
        print(f"--- {label}: BRAK PLIKU {p}")
        continue
    b = open(p, 'rb').read()
    print("=" * 72)
    print(f"{label}")
    print(f"  size = {len(b)} B")

    # ELF program headers -> find hash segment (type 0, the second one usually)
    if b[:4] == b"\x7fELF":
        cls = b[4]
        if cls == 1:  # ELF32
            e_phoff = struct.unpack_from("<I", b, 28)[0]
            e_phentsize = struct.unpack_from("<H", b, 42)[0]
            e_phnum = struct.unpack_from("<H", b, 44)[0]
            fmt = "<IIIIIIII"
        else:
            e_phoff = struct.unpack_from("<Q", b, 32)[0]
            e_phentsize = struct.unpack_from("<H", b, 54)[0]
            e_phnum = struct.unpack_from("<H", b, 56)[0]
            fmt = "<IIQQQQQQ"
        print(f"  ELF{'32' if cls==1 else '64'}  phnum={e_phnum} phentsize={e_phentsize}")
        for i in range(e_phnum):
            o = e_phoff + i * e_phentsize
            if cls == 1:
                p_type, p_off, p_va, p_pa, p_fsz, p_msz, p_fl, p_al = struct.unpack_from(fmt, b, o)
            else:
                p_type, p_fl, p_off, p_va, p_pa, p_fsz, p_msz, p_al = struct.unpack_from(fmt, b, o)
            print(f"    ph[{i}] type={p_type} off=0x{p_off:x} filesz={p_fsz}")

    print("  --- interesujace stringi w certyfikatach ---")
    hits = [(o, s) for o, s in strs(b, 6)
            if any(k in s for k in ("CA", "Qualcomm", "qti", "QTI", "Attestation",
                                    "Root", "NOT SECURE", "qtestsign", "PKI", "Lenovo"))]
    for o, s in hits[:25]:
        print(f"    0x{o:06x}  {s[:70]}")
    if not hits:
        print("    (brak)")
