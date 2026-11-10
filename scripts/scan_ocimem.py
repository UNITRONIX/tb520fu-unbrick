import re, sys, os

paths = [
    r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\edl-tools\memory\OCIMEM.BIN",
    r"C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\abl_rocknix_sm8650\crashdump_2026-11-08\OCIMEM.BIN",
]
seen = set()
for p in paths:
    if not os.path.exists(p):
        continue
    b = open(p, 'rb').read()
    key = (len(b), hash(b))
    if key in seen:
        continue
    seen.add(key)
    print("=" * 70)
    print(p, len(b), "B")
    # ascii runs
    runs = []
    cur = bytearray()
    start = 0
    for i, c in enumerate(b):
        if 32 <= c < 127:
            if not cur:
                start = i
            cur.append(c)
        else:
            if len(cur) >= 5:
                runs.append((start, cur.decode('ascii', 'ignore')))
            cur = bytearray()
    if len(cur) >= 5:
        runs.append((start, cur.decode('ascii', 'ignore')))
    print(f"ascii runs >=5: {len(runs)}")
    kw = re.compile(r'(fastboot|FASTBOOT|Android|ANDROID|extlinux|EXTLINUX|Volume|volume|boot|Boot|abl|ABL|abl|rocknix|ROCKNIX|menu|Menu|Linux|LINUX|devinfo|misc|Charging|charging|USB|xhci)', re.I)
    hits = [(o, s) for o, s in runs if kw.search(s)]
    print(f"keyword-bearing runs: {len(hits)}")
    for o, s in hits[:200]:
        print(f"  0x{o:08x}  {s[:100]}")
