# 2026-11-07 19:47 — native Linux gate

*Original: `STATUS_TERAZ_LINUX_SYNC.txt`. Translated.*

```
TB520FU soft brick — STATUS 2026-11-07 19:47 (Ubuntu native)

Goal: stock abl_a + abl_b. Nothing flashed.
RESULT abl_a=False abl_b=False
```

## Windows (earlier)

Gates 0–2 plus USB2: Sahara OK, Firehose FAIL (logo → 900E).

## Linux gate — kit melf (18:55)

- bump `900E`→`9008`: OK
- loader: `images/xbl_s_devprg_ns.melf`
  sha256 `3f6184f972eb413e7688fb5fae7fe88f2f4ee0ab09b6b58b551f7cad22e89e69`
- Sahara upload OK (ver3, HWID `0x2280e1`, SN `<REDACTED>`)
- Firehose: `USBError(19)` immediately after `DONE` — `printgpt` FAIL
- Log: `notes/GO_ABL_LINUX.log`

## Linux — two loaders (19:28)

- bump `900E`→`9008`: OK (Bus 001)
- METHOD A, FW096 melf
  sha256 `ba72961ce341d4edc6c413a23fc01abb0102d18bd3d69284a45a370543446cf5`
  → Sahara upload OK, FH `USBError(19)` FAIL (same pattern)
- METHOD B, `prog_firehose_ddr_from_fw096.elf`: **NOT RUN**
  (after A, no QC device on USB for ≥90 s — stop, no spam)

## Environment (ready)

- Workspace: `~/TB520FU_ubuntu_kit` (copy of the removable-media kit)
- `sudo` NOPASSWD: `/etc/sudoers.d/tb520fu-edl` → `scripts/tb520_root.sh`
- Commands: `sudo -n ~/TB520FU_ubuntu_kit/scripts/tb520_root.sh {setup|bump|edl|go-abl|status}`

## Conclusion

Native Linux = the same FAIL as Windows. The kit melf and the FW096 melf (different
hashes) — both Sahara OK, FH does not stay.
The problem is not the host / the WinUSB race.

NEXT (deliberately, without spam): METHOD B when 9008 returns; or LTBox plus the
309-resigned package if available; or service/test point.
Do not force-disassemble as the only option — METHOD B first when USB returns.

Notes: `NOTES_ODKRYCIA_2026-11-07_linux_gate.md`
USB now: no `05c6` (state after the drop).

---

## Why this file matters more than it looks

This is the point at which the entire "it is our software, our race, our driver"
family of explanations died. Two firmware revisions with different hashes, two
operating systems, two driver stacks, four tools: one result.

Everything after this date was, properly speaking, forensics on the device rather
than debugging of the host.
