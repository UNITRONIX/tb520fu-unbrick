# Verified: the Korean log is the same partition layout as ours

`docs\82` cited a Korean LTBox session on a TB520FU and noted that the `abl_a` write at
"LUN 4, start sector 95238" matched this project's target. That match is now checked
against this repository's own source for the number.

---

## 1. Where 95238 comes from on our side

It is read from the device's GPT, not assumed:

```
docs\02-device-and-partitions.md
  | abl_a | 4 | 95238 | 256 | 390 094 848 | 1 048 576 |
                  ^LUN ^start ^sectors          ^bytes

docs\09-service-report.md
  abl_a        4        95238        256     1 048 576 B
  abl_b        4        437686       256     1 048 576 B
```

## 2. What the Korean log reports

```
[EDL] abl_a 플래시 ← abl.elf (LUN 4, 시작 95238, 256 섹터)
                          LUN 4      start 95238  256 sectors
```

**Four values agree: LUN 4, sector 95238, 256 sectors, and the programmer size
1 569 028 bytes.** The other four values in that log - `xbl_a` at LUN 1 sector 6, 896
sectors - would be a further check but this repository does not record them in the same
form, so they are left unverified rather than asserted.

## 3. What the agreement establishes

It is not a coincidence that two independent sources produce `LUN 4 / 95238 / 256`:

- ours from reading the tablet's GPT via the crash-dump path;
- theirs from a flashing tool that resolved the same partition table on the same model.

So the log in `docs\82` is about **the same hardware layout as this unit**, not a similar
one. That makes its central claim - Firehose configures and the flash completes - a
statement about a TB520FU with this partition table.

## 4. What it does not establish

- **It is not this unit.** Different serial, different history, different state.
- **The entry method is unrecorded.** The log says `기기를 수동으로 EDL(9008) 모드로
  재부팅하세요` - "manually reboot the device into EDL 9008" - and then
  `[EDL] EDL 모드 감지됨` ("EDL mode detected"). The operator produced that state outside
  the tool, and how is not written down.
- **It does not show the programmer's runtime.** It shows `Firehose: configured`, which is
  the outcome, not the internal path. But the outcome is the thing this project never got.

## 5. Why this is worth a separate document

Because it is the difference between "our analysis might be wrong about the platform" and
"our analysis of the platform is right and this unit is in a bad state".

`docs\16` and everything after it concluded that the programmer dies during DDR
initialisation. That conclusion was reached by elimination, on one unit. The Korean log is
a second data point on the same model, with the same programmer, reaching the opposite
outcome.

**That does not make the DDR hypothesis wrong for this unit.** It makes it a statement
about *this unit's state*, which is a weaker and more actionable claim: a state can be
changed, a broken platform cannot.

Which points the whole investigation at the same place `docs\56` already pointed:
`CDT not found in any storage media, using defaults`.
