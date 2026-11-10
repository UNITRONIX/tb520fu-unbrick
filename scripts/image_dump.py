#!/usr/bin/env python3
"""image_dump.py - disassemble arbitrary offsets in any melf inner image.

The write gate lives in image [3] (Firehose):
    "device is locked, cannot write"   referenced from image+0x008eac
    "device is locked, cannot erase"   referenced from image+0x009acc

Reading those sites needs the same decoder used for image [2], but with image
[3]'s own program headers, which have a different base. This wraps a64.decode with
the right segment map for any of the four images.

Use as a library:
    from image_dump import MelfImages
    mi = MelfImages(path)
    for line in mi.disasm(3, 0x8e80, 40):
        print(line)

CLI:
    python image_dump.py --image 3 --offset 0x8e80 --count 40
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from a64 import decode

DEFAULT_MELF = Path(
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929"
    r"\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf"
)

#: file offset, size, for the melf's inner images (docs/04-melf-format.md)
LAYOUT = {
    1: (0x001300, 203888),
    2: (0x032F70, 908256),
    3: (0x110B50, 303096),
    4: (0x15AB48, 148924),
}


class MelfImages:
    def __init__(self, path: str | Path = DEFAULT_MELF) -> None:
        self.blob = Path(path).read_bytes()
        self.cache: dict[int, bytes] = {}

    def image(self, n: int) -> bytes:
        if n not in self.cache:
            off, size = LAYOUT[n]
            self.cache[n] = self.blob[off:off + size]
        return self.cache[n]

    def segments(self, n: int) -> list[tuple[int, int, int]]:
        """Return [(file_off, vaddr, filesz)] for loadable PT_LOAD segments."""
        img = self.image(n)
        if img[:4] != b"\x7fELF" or img[4] != 2:
            return []
        e_phoff = struct.unpack_from("<Q", img, 32)[0]
        e_phnum = struct.unpack_from("<H", img, 56)[0]
        out = []
        for i in range(e_phnum):
            o = e_phoff + i * 56
            if o + 56 > len(img):
                break
            p_type = struct.unpack_from("<I", img, o)[0]
            p_off, p_vaddr, _pa, p_filesz, _m = struct.unpack_from("<QQQQQ", img, o + 8)
            if p_type == 1 and p_filesz:
                out.append((p_off, p_vaddr, p_filesz))
        return out

    def off_to_va(self, n: int, off: int):
        for p_off, p_vaddr, filesz in self.segments(n):
            if p_off <= off < p_off + filesz:
                return p_vaddr + (off - p_off)
        return None

    def va_to_off(self, n: int, va: int):
        for p_off, p_vaddr, filesz in self.segments(n):
            if p_vaddr <= va < p_vaddr + filesz:
                return p_off + (va - p_vaddr)
        return None

    def cstr(self, n: int, va: int, maxlen: int = 200):
        off = self.va_to_off(n, va)
        if off is None:
            return None
        img = self.image(n)
        end = img.find(b"\x00", off, off + maxlen)
        if end < 0:
            return None
        raw = img[off:end]
        if not raw:
            return ""
        if sum(1 for c in raw if 32 <= c < 127) / len(raw) < 0.90:
            return None
        return raw.decode("ascii", "replace")

    def disasm(self, n: int, offset: int, count: int):
        """Yield (file_off, va, insn, text) for `count` instructions."""
        img = self.image(n)
        for i in range(count):
            off = offset + i * 4
            if off + 4 > len(img):
                break
            insn = struct.unpack_from("<I", img, off)[0]
            va = self.off_to_va(n, off)
            yield off, va, insn, decode(insn, va if va is not None else off)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--melf", default=str(DEFAULT_MELF))
    ap.add_argument("--image", type=int, default=3)
    ap.add_argument("--offset", type=lambda x: int(x, 0), default=None,
                    help="file offset within the image")
    ap.add_argument("--va", type=lambda x: int(x, 0), default=None,
                    help="virtual address (converted to a file offset)")
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--annotate", action="store_true",
                    help="resolve ADRP+ADD string operands inline")
    args = ap.parse_args()

    mi = MelfImages(args.melf)

    if args.offset is None and args.va is None:
        print("give --offset or --va")
        return 2

    if args.va is not None:
        off = mi.va_to_off(args.image, args.va)
        if off is None:
            print(f"va {args.va:#x} is not inside any segment of image {args.image}")
            for p_off, p_vaddr, filesz in mi.segments(args.image):
                print(f"  segment {p_vaddr:#x}..{p_vaddr + filesz:#x}")
            return 2
        print(f"  (va {args.va:#x} -> image+{off:#x})")
    else:
        off = args.offset

    rows = list(mi.disasm(args.image, off, args.count))

    print("=" * 78)
    print(f"#  image [{args.image}]  from image+{off:#x}"
          + (f"  (va {args.va:#x})" if args.va is not None else ""))
    print("=" * 78)

    # Pre-compute adrp+add pairs so annotations show the FINAL address, not the
    # page. Annotating only the adrp resolves to a page base and silently points
    # at the wrong string - a mistake that produced a misleading label once.
    resolved: dict[int, int] = {}
    if args.annotate:
        for idx, (off, va, insn, text) in enumerate(rows):
            if not text.startswith("adrp"):
                continue
            try:
                page = int(text.split(", ")[1].rstrip(">"), 16)
            except Exception:  # noqa: BLE001
                continue
            rd = text.split(",")[0].split()[1]
            # look ahead for add <same reg>, <same reg>, #imm
            for j in range(idx + 1, min(idx + 5, len(rows))):
                t2 = rows[j][3]
                if not t2.startswith("add "):
                    continue
                parts = t2[4:].split(", ")
                if len(parts) != 3:
                    continue
                if parts[0] == rd and parts[1] == rd:
                    try:
                        imm = int(parts[2].lstrip("#"), 16)
                    except Exception:  # noqa: BLE001
                        continue
                    resolved[off] = page + imm
                break

    for off, va, insn, text in rows:
        extra = ""
        if args.annotate and off in resolved:
            s = mi.cstr(args.image, resolved[off])
            if s:
                extra = f'   ; {resolved[off]:#x} "{s[:58]}"'
        va_s = f"{va:#012x}" if va is not None else "------------"
        print(f"  {off:#08x}  {va_s}  {insn:08x}  {text}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
