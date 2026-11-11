# The 40 MiB boundary is the start of qdss_region, not a DRAM limit

For most of this project the crash dump's refusal to answer above `0x82800000`
was treated as a property of the memory itself - "CS0 serves exactly 40 MiB" -
and that reading fed the hypothesis that DRAM was partially trained or partly
absent.

The live device tree names the region that begins at exactly that address.

---

    10|## 1. The address

```
reserved-memory/qdss_region@82800000      base 0x82800000   32.0 MiB
```

`qdss` is Qualcomm's on-chip trace and debug subsystem. Its reserved region
**starts at `0x82800000`** - the precise address at which reads stop answering
(`docs/27` §1, reproduced in two independent dumps).

## 2. What is below the boundary

```
global_sync_region@82600000    1 MiB    ends 0x82700000
tz_stat_region@82700000        1 MiB    ends 0x82800000
```

`tz_stat_region` ends **exactly** at `0x82800000`. So the exposed area is the
block of reserved regions that happen to be contiguous up to that point, and the
next one in the map is qdss.

## 3. The corrected reading

The old statement was:

> CS0 answers from 0x80000000 to 0x827FFFFF inclusive, and nothing beyond.

That is what was observed and it remains true. What changes is the explanation:

| reading | status |
|---|---|
| CS0 is only trained to 40 MiB | **not supported** - the training record covers 8 × 2 GiB (`docs/36`) |
| the crash handler exposes a bounded slice of CS0 | **supported** - and now with a name |
| the boundary is where qdss_region begins | **measured** - exact address match |

So the 40 MiB is a **layout boundary**, not a capacity boundary: the crash-dump
handler serves the regions it declares, and qdss is a traced region it does not
expose through that path. That is consistent with everything else measured:

- `SHRM_MEM` (0x24020000), the PMIC block (0x81B75000), `DDR_DATA`
  (0x1000080000) and `sbl_pmic_dump` (0x1000000000) all answer, and all are
  declared regions - not contiguous with CS0;
- the eight 2 GiB windows above `0x880000000` answer with `0xFF` rather than
  refusing (`docs/33`), so they are served-but-empty rather than cut off;
- `ramoops@0xa2000000` (4 MiB) sits in that `0xFF` area, which is worth knowing
  for later: a pstore region exists, and it is in a window the handler does serve.

## 4. Why this matters for the recovery goal

The whole "DDR is damaged" line of reasoning - which at one point pointed at a
board swap - rested on the 40 MiB figure meaning something about the DRAM. It
does not. Combined with `docs/36` (training covers the full capacity), there is
now no measurement anywhere in this project that indicates the DRAM is
malfunctioning.

That redirects the failure to the one place `docs/16` §7 already identified: the
programmer's DDR initialisation inside `sbl1_ddr_set_params` / `sbl1_ddr_init`,
which is software, not silicon.

## 5. Reproduce

```
python scripts/tablet.py read --region DDR_DATA     # needs a fresh HELLO
```

Offline, the region map is in `stock_live.dtb`, `/reserved-memory`, 40 entries
with `reg` properties.
