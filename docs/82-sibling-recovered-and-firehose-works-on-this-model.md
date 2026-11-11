# Two external findings that change the picture: a sibling model recovered, and Firehose confirmed working on this model

Two search results matter more than anything else found outside the repository this
session.

---

## 1. A Lenovo sibling with the identical symptom was recovered by test points

XDA thread title: **[TB128FU] Test points for recovering from Qualcomm Crashdump Mode**.

The opening post describes this device's exact state:

> I got my TB128FU tablet stuck in Qualcomm Crashdump Mode. I couldn't boot into Android,
> fastboot or EDL. I couldn't power off the device. Windows Device Manager confirmed I was
> in Qualcomm 900E diagnostics mode. I had to open the tablet, disconnect the battery and
> find the testpoints.

and the procedure:

```
1. open up tablet. Be careful, there is a cable connecting the display and PCB
2. disconnect the battery
3. while shorting the testpoints (I used tweezers), insert a USB cable that's already
   connected to a PC
4. you should now be in EDL mode (Qualcomm 9008 mode), where you can use LMSA, Qfil etc.
```

**`TB128FU` is the same family, the same vendor, the same Qualcomm 900E dead-end, and the
same conclusion: test points on the board, battery disconnected, short held while
inserting the cable.**

That is the strongest available precedent that this state is recoverable, and it comes
from a device close enough to be a template rather than an analogy.

Note the extra detail that matters: **the battery is disconnected first.** That is
consistent with everything in this repository - `docs/07` §E2 recorded the device cannot
be powered off, and a disconnected battery is the only genuine off state.

## 2. Firehose has been observed working on a TB520FU

A Korean forum post documents an LTBox flashing session on a **TB520FU**, with this log:

```
[EDL] 기기 감지: USB:VID_05C6&PID_9008            device detected as 9008
[EDL] 프로그래머 로드 중: ...xbl_s_devprg_ns.melf  loading programmer
[EDL] 프로그래머 크기: 1569028 bytes                size matches ours exactly
[EDL] Sahara: 프로그래머 업로드 중...
[EDL] Sahara: 프로그래머 업로드 완료                upload complete
[EDL] Firehose: 설정 중...
[EDL] Firehose: 설정 완료                          FIREHOSE CONFIGURED
[ARB] boot: 1775347200 패치 false
[Flash] 단계 3/4 — 펌웨어 파티션 플래싱
[EDL] xbl_a 플래시 ← xbl_s.melf (LUN 1, 시작 6, 896 섹터)
[EDL] abl_a 플래시 ← abl.elf (LUN 4, 시작 95238, 256 섹터)
[Flash] 펌웨어 플래싱 완료                          FLASHING COMPLETED
```

**This is the single most important external datum of the session.**

It is a TB520FU, with the same 1 569 028-byte programmer this repository uses, and
**Firehose configures successfully and the flash completes - including `abl_a` at LUN 4,
start sector 95238**, which is exactly the partition and offset this project has been
trying to write since the beginning (`docs/09`).

Three conclusions follow, and they are not inferences:

1. **The programmer works on this hardware.** The "programmer dies in DDR init" hypothesis
   (`docs/16`), and the DDR-training line of reasoning that followed it, are **not
   properties of the platform**. Another unit of the same model ran the same melf to
   completion.
2. **The write gate does not block.** `docs/17` decoded the lock as a byte that fails open;
   this log shows `abl_a` actually written, so on a normal unit it is not set.
3. **The wall is entirely about entering 9008.** Everything after that works.

## 3. What that does to the analysis in this repository

The session arrived at "the programmer dies in `sbl1_ddr_init`" by elimination, because
that was the only stage between `DONE` and silence. The external log shows that on the
same model, that stage completes.

So the correct statement is not "`sbl1_ddr_init` is broken". It is:

> On this unit, the programmer is accepted but never speaks. On another unit of the same
> model, the identical programmer configures Firehose and flashes. **The difference is in
> this unit's state, not in the platform.**

And the candidates for that state difference, all of which this repository already
identified, become relevant again:

- the DDR recovery path (`docs\57`: `HAL_DDR_SDI_Recover`, warm-reset ladder) - this unit
  has failed DDR initialisation before;
- `CDT not found in any storage media, using defaults` (`docs\56`) - the boot log shows
  this unit falling back to default memory parameters, which is exactly the condition
  `docs\16` §4.2 said would produce a board-specific mismatch;
- the low battery (`VBAT 3588mV`, `UFS Gear 1`).

**The CDT fallback is now the leading candidate.** It was flagged as suspicious on
`docs\16`'s own terms, and a sibling unit that flashes successfully is unlikely to be
running on default DRAM parameters.

## 4. What this does to the goal

The goal is `HELLO ver=3 mode=0`. Two things are now established externally:

- **the sibling precedent says the state is recoverable by test points** - and gives the
  procedure, including the battery-disconnect step this repository never performed;
- **the flashing route works on this model** - so if 9008 is reached, everything after it
  is solved.

That is a materially better position than "one route open, needs a pin-out we do not have".

## 5. Honest limits

- Neither source is a verified guide for **this exact unit**. `TB128FU` is a sibling, not a
  twin; the Korean log is a different device of the same model.
- The Korean log does **not** show how 9008 was entered - it shows `기기를 수동으로 EDL(9008)
  모드로 재부팅하세요` ("manually reboot the device into EDL 9008"), meaning the operator did
  it outside the tool, and the method is not recorded.
- The `CDT not found` reading is a **candidate**, not a conclusion.
- A comment in the Korean thread mentions the same "The Current system is not compatible
  with hardware" loop this repository saw, and the resolution was flashing a region-matched
  firmware - consistent, but about a different failure.
