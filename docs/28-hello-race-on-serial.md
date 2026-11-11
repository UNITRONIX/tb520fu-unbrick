# Why HELLO keeps disappearing: a serial-port timing problem

This document records why every attempt to read `DDR_DATA.BIN` failed, and what is and is
not established about the cause.

---

## 1. The symptom, consistently observed

Across many attempts on a freshly power-cycled device:

```
port COM10 appears at  +5..10 s after reset
port opens successfully
HELLO never arrives (0 bytes within 15 s)
```

and crucially, verified with the **vendor tool** as well as with custom code:

```
QSaharaServer.exe -p \\.\COM10 -m -v 3
11:10:41: STATE <-- SAHARA_WAIT_HELLO
11:10:51: Received 0 bytes
11:10:51: ERROR: Unable to read packet header. Only read 0 bytes.
```

**The same tool, on the same port, in the same mode, had earlier succeeded** and dumped
14 GB of memory (`25-com-world-works.md`, `26-ddr-wall-at-40mb.md`). So this is not a tool
defect and not a driver defect.

## 2. The explanation that fits

Sahara's `HELLO` is a **single pending packet**, issued once per boot of the bootloader.
Evidence for this, accumulated:

| observation | meaning |
|---|---|
| first attempt after a power cycle: HELLO received | the packet exists once |
| every subsequent attempt on the same boot: 0 bytes | it was consumed |
| the vendor tool and custom code fail identically | device property, not tooling |
| re-running after a real power cycle works again | a new boot issues a new HELLO |

So the device is not mute. **Its one greeting has already been taken.**

## 3. What this means for the serial port specifically

On a USB *bulk* endpoint, a pending packet waits in a kernel buffer and can be read
whenever the device is opened. On a **serial port** it does not: bytes arriving before the
port is open are discarded by the driver.

This creates a narrow race that the tooling has been losing:

- wait for the port to appear, then open it → the HELLO may already have been sent and lost;
- open before it appears → impossible, the port does not exist yet.

`com_wait_read.py` polls every 50 ms and opens immediately, but in the runs so far it
either opened after the HELLO had been sent, or something else had already consumed it.

**This race is the real obstacle**, and it is why two full attempts were spent and
`DDR_DATA.BIN` has still not been read.

## 4. What is not established

- Whether the HELLO is sent **at enumeration** (before the port exists, hence always lost)
  or **shortly after**, in a window that can be caught.
- Whether the driver buffers anything at all. The vendor tool succeeding once suggests the
  window is catchable, but not how wide it is.

If the HELLO is issued at enumeration, then **no host-side tool can reliably read the
crash dump over this serial port**, and the vendor tool only ever succeeded by winning the
race once.

## 5. The practical workaround

The vendor tool's own sequence is `QSaharaServer` then `fh_loader`, both opening the port
fresh. That works because `QSaharaServer` is the first thing to open the port after the
boot — it wins the race by being the only contender.

**Therefore: the only reliable way to read memory over COM is to let `QSaharaServer` do
it**, accepting that it dumps all regions in reverse order and reaches `DDR_DATA.BIN` only
after ~13 GB.

Two options, both honest about the cost:

**a)** Let a full dump run to completion (~15-20 minutes) and keep the region we want.
The dump order is deterministic, so `DDR_DATA.BIN` will be reached. Previous attempts were
stopped early; none was allowed to finish.

**b)** Use `--dump-partitions` style filtering if the tool supports it. Its help shows
`-r <image ID>` for ramdump and `-w <path>` for output location, but no per-region filter
was found in the usage text.

**Option (a) is the one to take.** It costs time and disk, needs no new code, and is
guaranteed to reach the region.

## 6. Correction to this session's work

`com_wait_read.py` and `com_region_read.py` were written to avoid the 14 GB dump. They are
correct in design but cannot win the race in practice. They are kept because they document
the attempt and because they would work on a device whose HELLO is issued after the port
opens — which may be the case on other Qualcomm platforms.

The honest summary: **the selective-read approach failed for a reason that was not
anticipated, and the reliable path is the slow one.**
