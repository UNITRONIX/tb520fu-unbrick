#!/usr/bin/env python3
"""Exhaustive search: is any TLV block a hash of a well-defined region of the melf?"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\image\xbl_s_devprg_ns.melf")

TLV_START, TLV_END = 0x1074, 0x1300
ALGS = ("sha256", "sha384", "sha512", "sha3_256", "sha3_384", "sha3_512",
        "blake2b", "blake2s", "md5")

d = MELF.read_bytes()

# ---------------------------------------------------------------- ELF images
def elf_images(data: bytes):
    """Yield (name, offset, phdrs) for every ELF header found."""
    off = 0
    idx = 0
    while True:
        i = data.find(b"\x7fELF", off)
        if i < 0:
            break
        cls = data[i + 4]
        if cls == 1:
            e_type, e_machine = struct.unpack_from("<HH", data, i + 16)
            entry = struct.unpack_from("<I", data, i + 24)[0]
            phoff = struct.unpack_from("<I", data, i + 28)[0]
            phentsize = struct.unpack_from("<H", data, i + 42)[0]
            phnum = struct.unpack_from("<H", data, i + 44)[0]
        else:
            e_type, e_machine = struct.unpack_from("<HH", data, i + 16)
            entry = struct.unpack_from("<Q", data, i + 24)[0]
            phoff = struct.unpack_from("<Q", data, i + 32)[0]
            phentsize = struct.unpack_from("<H", data, i + 54)[0]
            phnum = struct.unpack_from("<H", data, i + 56)[0]

        phdrs = []
        for k in range(phnum):
            base = i + phoff + k * phentsize
            if base + phentsize > len(data):
                break
            if cls == 1:
                p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, \
                    p_flags, p_align = struct.unpack_from("<IIIIIIII", data, base)
            else:
                p_type, p_flags = struct.unpack_from("<II", data, base)
                p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = \
                    struct.unpack_from("<QQQQQQ", data, base + 8)
            phdrs.append(dict(type=p_type, off=p_offset, filesz=p_filesz,
                              vaddr=p_vaddr, idx=k))
        yield f"img{idx}@{i:#x}", i, cls, e_type, e_machine, entry, phdrs
        idx += 1
        off = i + 4


images = list(elf_images(d))
print("ELF images found:")
for name, base, cls, etype, mach, entry, phdrs in images:
    print(f"  {name:14s} ELF{32 if cls == 1 else 64} "
          f"type={etype} mach={mach:#x} entry={entry:#x} ph={len(phdrs)}")

# ---------------------------------------------------------------- candidates
cands: dict[str, bytes] = {}


def add(name: str, blob: bytes) -> None:
    if 0 < len(blob) <= 64 * 1024 * 1024:
        cands[name] = blob


for name, base, cls, etype, mach, entry, phdrs in images:
    end = min(p["off"] + p["filesz"] for p in phdrs if p["filesz"] > 0) if phdrs else 0
    for p in phdrs:
        if p["filesz"] == 0:
            continue
        start = base + p["off"]
        blob = d[start:start + p["filesz"]]
        tag = "LOAD" if p["type"] == 1 else f"t{p['type']:#x}"
        add(f"{name} ph[{p['idx']}] {tag} filesz={p['filesz']}", blob)
        add(f"{name} ph[{p['idx']}] strippedFF", blob.rstrip(b"\xff"))
        add(f"{name} ph[{p['idx']}] stripped00", blob.rstrip(b"\x00"))

add("whole file", d)
add("TLV region", d[TLV_START:TLV_END])
add("wrapper header only", d[0:0x94])
add("wrapper 0x0..0x1074", d[0:0x1074])
add("melf minus TLV", d[:TLV_START] + d[TLV_END:])
add("0x1300..end", d[0x1300:])
add("TLV value of 0x0182", d[0x1078:0x1078 + 648])

# concatenations of TLV children
add("TLV children concat",
    d[0x1078:0x1080] + d[0x1080:0x10f8] + d[0x10f8:0x1184] + d[0x1184:0x1300])

print(f"\nCandidates: {len(cands)}")

# ---------------------------------------------------------------- targets
def tlv_blocks(blob: bytes, base: int) -> list[tuple[int, int, bytes]]:
    out = []

    def walk(buf: bytes, off: int) -> None:
        pos = 0
        while pos + 4 <= len(buf):
            tag, ln = struct.unpack_from("<HH", buf, pos)
            vs, ve = pos + 4, pos + 4 + ln
            if ve > len(buf):
                return
            out.append((off + pos, tag, buf[vs:ve]))
            if ln >= 8:
                t2, l2 = struct.unpack_from("<HH", buf, vs)
                if 0 < l2 <= ln - 4:
                    walk(buf[vs:ve], off + pos + 4)
            pos = vs + ((ln + 3) // 4) * 4

    walk(blob, base)
    return out


targets = [(o, t, v) for o, t, v in tlv_blocks(d[TLV_START:TLV_END], TLV_START)
           if len(v) in (32, 48, 64, 128, 136)]

print(f"Hash-sized TLV values: {len(targets)}")

# ---------------------------------------------------------------- search
hits = 0
print()
for off, tag, value in targets:
    printable = value.hex()
    # split 136-byte blocks into their two 64-byte halves
    parts = [("whole", value)]
    if len(value) == 136:
        parts = [("p1", value[4:68]), ("p2", value[68:132])]
    elif len(value) == 128:
        parts = [("p1", value[0:64]), ("p2", value[64:128])]

    for pname, part in parts:
        for cname, cdata in cands.items():
            for alg in ALGS:
                h = hashlib.new(alg, cdata).digest()
                if h == part:
                    print(f"  MATCH tag={tag:#06x}@{off:#06x} {pname} "
                          f"== {alg}({cname})")
                    hits += 1
                # truncated-to-32 / prefix comparisons for 64-byte slots
                if len(part) == 64 and len(h) < 64 and part[:len(h)] == h:
                    print(f"  MATCH(prefix) tag={tag:#06x}@{off:#06x} {pname} "
                          f"== {alg}({cname}) padded")
                    hits += 1
    if not any(len(v) for v in (value,)):
        pass

print(f"\nTotal matches: {hits}")

# ---------------------------------------------------------------- what is it
print("\n--- structural reading of the two 136-byte blocks ---")
for off, tag, value in targets:
    if tag == 0x81ff and len(value) == 136:
        idx = struct.unpack_from("<I", value, 0)[0]
        tail = struct.unpack_from("<I", value, 132)[0]
        print(f"  @{off:#06x}  index=0x{idx:08x} ({idx})  tail=0x{tail:08x}")
        print(f"            p1={value[4:12].hex()}...  p2={value[68:76].hex()}...")
