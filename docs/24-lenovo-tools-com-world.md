# The untried path: Lenovo's own tools in the COM driver world

This document answers a question that this whole investigation had never properly
asked: **why has nobody run Lenovo's own flashing tools against this tablet?**

---

## 1. The answer is a driver world, not a technical impossibility

`fh_loader.exe`, `QSaharaServer.exe` and `QFIL.exe` are all present in the ROM package
next to `xbl_s_devprg_ns.melf`. They are what Lenovo's own `Rescue.cmd` invokes.

They speak to the device over a **COM port**. They cannot open a WinUSB node at all -
that has been confirmed repeatedly and is documented in `07-dead-ends.md` §A2.

And the tablet has always been bound to **WinUSB**:

```
USB\VID_05C6&PID_900E\B6F2DE0A   service=WinUSB   (oem66.inf)
```

So the tools were never actually given a chance. Every session in this project used
the WinUSB world: `edl`, `pyusb`, LTBox, custom libusb code. All of them are correct
tools in the other world.

## 2. A serial driver for these exact PIDs exists on this machine

```
C:\Program Files\Qualcomm\Qualcomm USB Drivers\drivers\qcwdfser.inf
    PID_9008  present
    PID_900E  present
```

This was found by checking the INF files rather than assuming. It matters because the
earlier conclusion was that no Qualcomm COM driver was available - and that was wrong
for this machine. Five Qualcomm INF packages are visible via `oem*.inf`
(`oem39`, `oem56`, `oem58`, `oem59` provide `qcom`/`qcusb`), but none of them cover
`9008`/`900E`. The package in `Program Files\Qualcomm` does.

## 3. What Lenovo's own script does

`Rescue.cmd`, verbatim from the ROM package:

```
Qsaharaserver.exe -p \\.\portname -s 13:...\image\xbl_s_devprg_ns.melf
fh_loader.exe --port=\\.\portname --setactivepartition=1 --zlpawarehost=1
              --sendxml=rawprogram_save_persist_unsparse0.xml
              --sendxml=rawprogram1.xml ... --sendxml=patch5.xml
              --search_path=...\image --noprompt --showpercentagecomplete
              --memoryname=UFS --reset
```

Note `13:` in the QSaharaServer argument - that is image ID 13, the programmer class,
which is exactly what the device requests (`READ_DATA image=0x0d`). This script was
built for this device.

## 4. Why this is worth trying, honestly assessed

**In favour:**

- it is the vendor's own toolchain against the vendor's own package;
- it has never been run against this tablet in its correct driver world;
- `fh_loader` reports progress and errors over the COM link in a way the raw USB path
  did not, so a failure would be *informative* rather than silent;
- the driver for `9008` is present on this machine, so the switch is possible.

**Against, and this is important:**

- `07-dead-ends.md` §A2 records an attempt in this world that reached
  `Sahara protocol completed (rc=0)` and then failed at
  `Failed to open com port \\.\COM5`. That is a real prior failure.
- However that attempt was made with the device having already *left* `9008` by the
  time `fh_loader` tried to open the port - the note says "by which time the device had
  already gone to the logo and returned as `900E`". That is a **timing and state**
  failure, not proof that the toolchain cannot work.
- The current understanding of the device is better: it waits in `900E`, it can be
  bumped to `9008` reliably (~20 s), and it does **not** reset itself unless something
  resets it. That removes exactly the failure mode of the earlier attempt.

So the honest position is: **this path was abandoned on the strength of an attempt that
failed for a reason now understood.** It deserves one properly sequenced attempt.

## 5. The sequence, correctly ordered

```
1. confirm the tablet is at 900E and responsive
2. bump 900E -> 9008  (and verify 9008 is present)
3. rebind the driver for 05C6:9008 from WinUSB to qcwdfser  (needs admin)
   -> a COM port must appear; if none does, the attempt is over
4. note the port number
5. QSaharaServer.exe -p \\.\COMx -s 13:<rom>\image\xbl_s_devprg_ns.melf
6. if that completes, fh_loader.exe with the same port
```

Step 3 is the one that requires administrator rights and is the only irreversible-ish
step: it changes which driver owns the device. It is reversible by rebinding WinUSB,
and the existing `oem66.inf` package makes that straightforward.

## 6. What must not be done

- Do **not** run `fh_loader` against a WinUSB node. It will fail with a port error and
  the failure will say nothing about the device.
- Do **not** mix worlds in one session. Pick COM, stay in COM, and rebind back
  deliberately.
- Do **not** trust the earlier "Gate 1 fail" as evidence against this path. Read what it
  actually said: the Sahara stage completed with `rc=0`. The failure was at the port
  open, afterwards.

## 7. Why this matters more than further host-side reverse engineering

Everything in `docs/16` through `docs/23` is static analysis of the programmer and the
boot chain. It has produced real understanding - the write gate is a byte in
`lenovolock`, the battery gate is bounded and ruled out, the entry point returns and
stops - but it has not produced a single working write.

This path, by contrast, is the vendor's supported route, and it has never been executed
in its correct configuration. If it works, it writes `abl_a` and `abl_b` and the tablet
is recovered. If it fails, it fails with a message that means something.

That is a better use of the next hour than another round of disassembly.
