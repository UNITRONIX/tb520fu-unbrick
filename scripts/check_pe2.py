import struct

p = r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\mainline\out\Image"
b = open(p, 'rb').read(8192)

pe = struct.unpack_from("<I", b, 0x3C)[0]
print(f"PE offset = 0x{pe:x}")
assert b[pe:pe+4] == b"PE\0\0"

machine, nsec, tstamp, symptr, nsym, optsize, chars = struct.unpack_from("<HHIIIHH", b, pe+4)
print(f"machine=0x{machine:04x}  sections={nsec}  opt_hdr_size={optsize}  characteristics=0x{chars:04x}")

opt = pe + 24
magic = struct.unpack_from("<H", b, opt)[0]
print(f"optional magic = 0x{magic:04x}")

# PE32+ layout
subsystem = struct.unpack_from("<H", b, opt + 68)[0]
print(f"subsystem = {subsystem}   (10 = EFI application, 11 = EfiBootServiceDriver, 12 = EfiRuntime)")

# section table starts right after the optional header
sec = opt + optsize
print(f"\nsection table at 0x{sec:x}")
for i in range(nsec):
    o = sec + i * 40
    name = b[o:o+8].rstrip(b"\x00").decode('ascii', 'replace')
    vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", b, o+8)
    print(f"  [{i}] name={name!r:14s} vaddr=0x{vaddr:08x} vsize=0x{vsize:08x} rawptr=0x{rawptr:08x} rawsize=0x{rawsize:08x}")

names = []
for i in range(nsec):
    o = sec + i*40
    names.append(b[o:o+8].rstrip(b"\x00").decode('ascii','replace'))
print(f"\nnazwy sekcji: {names}")
print("ma .reloc:", any('reloc' in n.lower() for n in names))

# EFI needs image to be loaded at its preferred base; check ImageBase
imagebase = struct.unpack_from("<Q", b, opt + 24)[0]
print(f"ImageBase = 0x{imagebase:x}")
