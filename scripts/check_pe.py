import struct, sys, hashlib

p = r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\mainline\out\Image"
b = open(p, 'rb').read(4096)

code0, code1 = struct.unpack_from("<II", b, 0)
print(f"code0 = 0x{code0:08x}   bytes: {b[0]:02x} {b[1]:02x} {b[2]:02x} {b[3]:02x}")
print(f"code1 = 0x{code1:08x}")
print(f"text_offset = 0x{struct.unpack_from('<Q', b, 8)[0]:x}")
print(f"image_size  = 0x{struct.unpack_from('<Q', b, 16)[0]:x}")
print(f"flags       = 0x{struct.unpack_from('<Q', b, 24)[0]:x}")
magic = b[56:60]
print(f"magic @0x38 = {magic!r}")

# PE header offset lives at 0x3C for a PE/COFF image
pe_off = struct.unpack_from("<I", b, 0x3C)[0]
print(f"\ne_lfanew (0x3C) = 0x{pe_off:x}")
ok = False
if 0 < pe_off < 0x1000:
    sig = b[pe_off:pe_off + 4]
    print(f"signature at that offset = {sig!r}")
    if sig == b"PE\x00\x00":
        machine = struct.unpack_from("<H", b, pe_off + 4)[0]
        nsec = struct.unpack_from("<H", b, pe_off + 6)[0]
        opt_magic = struct.unpack_from("<H", b, pe_off + 24)[0]
        print(f"  machine = 0x{machine:04x}  (0xaa64 = ARM64)")
        print(f"  sections = {nsec}")
        print(f"  optional header magic = 0x{opt_magic:04x}  (0x20b = PE32+)")
        ok = machine == 0xAA64 and opt_magic == 0x20B
        print()
        for i in range(nsec):
            o = pe_off + 24 + 240 + i * 40
            name = b[o:o + 8].rstrip(b"\x00").decode('ascii', 'replace')
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", b, o + 8)
            print(f"  section {name:10s} vaddr=0x{vaddr:08x} vsize=0x{vsize:x} raw=0x{rawptr:x}/{rawsize:x}")

print()
if ok:
    print(">>> To JEST poprawny PE/EFI ARM64 (CONFIG_EFI_STUB=y).")
    print(">>> Image mozna uzyc bezposrednio jako EFI/BOOT/BOOTAA64.EFI")
    print(">>> (wystarczy zmiana nazwy, bez objcopy).")
else:
    print(">>> Brak poprawnego naglowka PE -> sciezka EFI niedostepna z tego pliku.")

# also check whether a .reloc section exists (required by some firmware)
if ok:
    names = []
    for i in range(struct.unpack_from("<H", b, pe_off + 6)[0]):
        o = pe_off + 24 + 240 + i * 40
        names.append(b[o:o + 8].rstrip(b"\x00").decode('ascii', 'replace'))
    print(f"\nsekcje: {names}")
    print("reloc obecny:", any('reloc' in n.lower() for n in names))
