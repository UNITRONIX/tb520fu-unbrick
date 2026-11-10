import struct, sys

# GPT primary header + entries are in gpt_main0.bin
paths = [
    r"C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\gpt_main0.bin",
]
for p in paths:
    b = open(p, 'rb').read()
    print(f"=== {p.split(chr(92))[-1]}  {len(b)} B")
    # this kit's GPT binaries put the header at byte 0x1000 (LBA 8 of the file)
    hdr = b.find(b"EFI PART")
    if hdr < 0:
        print("brak GPT - pomijam")
        continue
    print(f"GPT header at file offset 0x{hdr:x}")
    sig = b[hdr:hdr + 8]
    hdr_size = struct.unpack_from("<I", b, hdr + 12)[0]
    entries_lba = struct.unpack_from("<Q", b, hdr + 72)[0]
    num_entries = struct.unpack_from("<I", b, hdr + 80)[0]
    ent_size = struct.unpack_from("<I", b, hdr + 84)[0]
    print(f"header_size={hdr_size} entries_lba={entries_lba} count={num_entries} ent_size={ent_size}")

    base = hdr + hdr_size
    print(f"\n{'#':>3} {'start_lba':>12} {'end_lba':>12} {'sectors':>10} {'size':>12}  name")
    for i in range(num_entries):
        o = base + i * ent_size
        if o + ent_size > len(b):
            break
        tguid = b[o:o + 16]
        if tguid == b"\x00" * 16:
            continue
        first = struct.unpack_from("<Q", b, o + 32)[0]
        last = struct.unpack_from("<Q", b, o + 40)[0]
        name = b[o + 56:o + 56 + 72].decode("utf-16-le", "replace").split("\x00")[0]
        secs = last - first + 1
        size = secs * 4096
        human = f"{size/1024/1024:.1f}MB" if size < 1024**3 else f"{size/1024**3:.2f}GB"
        print(f"{i:>3} {first:>12} {last:>12} {secs:>10} {human:>12}  {name}")
