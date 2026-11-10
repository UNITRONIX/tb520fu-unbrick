import struct, math, collections, sys, zlib, lzma, bz2, gzip, io, os

f = r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\abl_rocknix_sm8650\abl_signed-SM8650.elf"
b = open(f, 'rb').read()
print("size", len(b))

ident = b[:16]
print("ident", ident.hex())
(e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags,
 e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", b, 16)
print(f"type={e_type} machine={e_machine} entry=0x{e_entry:x} phoff=0x{e_phoff:x} "
      f"shoff=0x{e_shoff:x} ehsize={e_ehsize} phentsize={e_phentsize} phnum={e_phnum}")

for i in range(e_phnum):
    o = e_phoff + i * e_phentsize
    p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from("<IIIIIIII", b, o)
    print(f"ph[{i}] type=0x{p_type:x} off=0x{p_offset:x} vaddr=0x{p_vaddr:x} paddr=0x{p_paddr:x} "
          f"filesz={p_filesz} memsz={p_memsz} flags=0x{p_flags:x} align=0x{p_align:x}")

def ent(d):
    if not d:
        return 0.0
    c = collections.Counter(d)
    n = len(d)
    return -sum(v / n * math.log2(v / n) for v in c.values())

# find code segment
code_off, code_sz = None, None
for i in range(e_phnum):
    o = e_phoff + i * e_phentsize
    p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from("<IIIIIIII", b, o)
    if p_type == 1 and p_filesz > 10000:
        code_off, code_sz = p_offset, p_filesz
print(f"\ncode segment: off=0x{code_off:x} size={code_sz}")

print("\nentropy per 8K block in code segment:")
for off in range(code_off, code_off + code_sz, 8192):
    blk = b[off:off + 8192]
    print(f"  0x{off:06x}  {ent(blk):.3f}  ({len(blk)} B)")

code = b[code_off:code_off + code_sz]

print("\nmagic scan in code segment:")
magics = {
    b"\x1f\x8b\x08": "gzip",
    b"\xfd7zXZ": "xz",
    b"BZh": "bzip2",
    b"\x28\xb5\x2f\xfd": "zstd",
    b"\x04\x22\x4d\x18": "lz4",
    b"\x5d\x00\x00": "lzma-alone-ish",
    b"\x89LZO": "lzo",
    b"LZMA": "LZMA-name",
    b"\x02\x21\x4c\x18": "lz4-legacy",
    b"_FVH": "UEFI FV",
    b"LinuxLoader": "LinuxLoader",
}
for m, name in magics.items():
    idx = 0
    hits = []
    while True:
        idx = code.find(m, idx)
        if idx < 0:
            break
        hits.append(idx)
        idx += 1
        if len(hits) > 20:
            break
    print(f"  {name:16s} {len(hits)} hits {[hex(x) for x in hits[:10]]}")

# try raw LZMA / deflate at every 4-byte aligned offset in first 64K of code
print("\ntrying raw decompressors at 4-byte aligned offsets (first 16K):")
found = False
for off in range(0, min(16384, len(code)), 4):
    for wbits in (None,):
        pass
    # raw lzma1 with common lc/lp/pb
    pass

def try_lzma_raw(data):
    for lc in range(4):
        for lp in range(3):
            for pb in range(3):
                try:
                    d = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                                              filters=[{"id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb}])
                    out = d.decompress(data[:200000], max_length=4096)
                    if len(out) > 256:
                        return (lc, lp, pb, out)
                except Exception:
                    continue
    return None

cands = [0] + [code.find(m) for m in (b"\x5d\x00\x00", b"\x00\x00\x80\x00")]
for start in cands:
    if start is None or start < 0:
        continue
    r = try_lzma_raw(code[start:])
    if r:
        print(f"  LZMA RAW hit at code+0x{start:x}: lc={r[0]} lp={r[1]} pb={r[2]} first bytes={r[3][:64]!r}")
        found = True

if not found:
    print("  no raw-LZMA candidate decompressed")

# deflate raw attempts
print("\ntrying raw deflate at aligned offsets (first 4K):")
hit = False
for off in range(0, min(4096, len(code))):
    try:
        d = zlib.decompressobj(-15)
        out = d.decompress(code[off:off + 200000], 4096)
        if len(out) > 512:
            print(f"  deflate hit at code+0x{off:x}: {out[:64]!r}")
            hit = True
            break
    except Exception:
        continue
if not hit:
    print("  no raw deflate candidate")
