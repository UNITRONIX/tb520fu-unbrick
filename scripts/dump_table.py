import struct, os
p = r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\abl_rocknix_sm8650\crashdump_2026-11-08\memory_table.bin"
b = open(p, 'rb').read()
print("table size", len(b))
ENT = 64
off = 0
i = 0
while off + ENT <= len(b):
    pref, base, length = struct.unpack_from("<QQQ", b, off)
    desc = b[off+24:off+44].split(b"\x00")[0].decode('ascii', 'replace')
    fname = b[off+44:off+64].split(b"\x00")[0].decode('ascii', 'replace')
    if length == 0 or length > (1 << 34):
        break
    print(f"[{i:2d}] {base:#014x} {length:>10d}  {desc:<22s} {fname}")
    off += ENT
    i += 1

print()
print("=== sbl_pmic_dump header ===")
q = r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\edl-tools\memory\sbl_pmic_dump.bin"
d = open(q, 'rb').read()
print("size", len(d))
print("first 128:", d[:128].hex(' '))
