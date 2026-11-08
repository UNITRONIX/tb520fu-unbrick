# FAQ

Short answers. No archaeology.

## Questions

---

### 1. My `TB520FU` is soft-bricked the same way. Can I fix it from my PC?

**No.** Not with QFIL, `fh_loader`, `edl`, LTBox, a custom libusb client, on
Windows or on Linux. All were tried, all fail at the same step. See
[`05-firehose-and-the-silence.md`](05-firehose-and-the-silence.md).

### 2. Why not? The upload succeeds.

Because the programmer is accepted and then never starts. The device leaves USB
about 8 s after `DONE` and returns in crashdump mode. Nothing on the host can change
that; the failure is below the host's reach.

### 3. Is it definitely the bootloader and not the hardware?

The bootloader partitions, yes. Specifically `abl_a` and `abl_b`. Everything below
(silicon, PBL, XBL, storage reads) works — proven by a full Sahara session. Everything
above (`boot`, `init_boot`, Android) was never reached.

### 4. Could the storage chip be dying?

Unlikely, and consistent with nothing observed. Reads work, identification works,
the programmer is accepted. Only new writes are unavailable, and that is because the
programmer never runs — not because the medium refuses writes.

### 5. Is it a driver problem?

No. The same failure occurs on native Linux, which uses a completely different USB
stack. On Windows, the WinUSB-versus-COM choice is real and worth understanding
(see [`07-dead-ends.md`](07-dead-ends.md) §A6), but it is not the cause.

### 6. Is it a cable problem?

No. Multiple cables, multiple ports, USB 2.0 and 3.0. An "EDL cable" produced a
genuine PBL-level session once — and that session failed identically.

### 7. Could I just sign the programmer myself?

No. This PBL rejects a plain ELF64 at 64 bytes (`0x29`) before any signature is
examined. The original Lenovo programmer already passes. And modifying inside the
container trips a whole-blob integrity check (`0x21`). See
[`06-signing.md`](06-signing.md).

### 8. So signing is irrelevant?

For *this* device and *this* symptom, yes. It is not irrelevant in general, and
understanding it is how the format/integrity/trust layers were separated.

### 9. What about `qtestsign`? Someone said it can sign anything.

It produces no real signature — a zero stub plus dummy certificates. Its own README
says it only works where firmware secure boot is disabled. It is MBN packaging, not
signing.

### 10. Can I get Qualcomm's keys?

No.

### 11. Can I find a leaked Lenovo programmer for SM8650?

That is the only zero-cost hope, and it is open-ended. It would also have to solve
the runtime problem, which the *original, correctly signed* programmer does not.

### 12. What actually fixes this?

Writing 1 MiB to each of two partitions, with write access. Either a Lenovo service
centre or a shop with test-point EDL capability. The payloads and offsets are in
[`09-service-report.md`](09-service-report.md).

### 13. What is a test point, and why is it different?

A pad on the mainboard that forces the SoC into EDL before XBL runs. It gives a
clean PBL state with no crashdump residue and no wedged sessions. It does not bypass
signing, but it removes every variable the host cannot control. Requires opening the
case.

### 14. Will a Lenovo service centre definitely fix it?

Very likely — it is two writes with official tooling. Whether it is covered by
warranty is a separate question: an unlocked bootloader usually voids it, and flashing
a non-Lenovo bootloader certainly does.

### 15. My tablet is healthy. How do I avoid this?

Four rules, from [`08-linux-port-notes.md`](08-linux-port-notes.md) §9:

1. Test with `fastboot boot` before flashing anything.
2. Have stock payloads with verified hashes on disk first.
3. Keep one ABL slot stock. Always.
4. Never flash a bootloader built for other hardware, however similar the SoC.

### 16. Why is there no firmware in this repository?

Two reasons. Legally: it is Lenovo's proprietary software. Practically: the package
is ~13 GB. What is published instead are the SHA-256 hashes of the two payloads that
matter, so you can verify your own copy.

### 17. Where do I get the firmware?

Lenovo's Rescue and Smart Assistant (RSA) / LMSA, using the model `TB520FU`. Two
packages are relevant: `ZUI 17.5.10.096` (ABL on slot `a` came from here) and
`ZUI 18.5.10.037` (slot `b`).

### 18. Do the two ABL payloads have to match the same firmware version?

No. Each is a complete, self-contained bootloader for its partition. Mixing versions
across slots is unusual but not dangerous — each slot is booted independently.

### 19. Why does `slot-retry-count` matter?

When ABL fails to boot, XBL decrements the counter and eventually marks the slot
unbootable, which is why the device settles into a stable crashdump loop. If both
slots are wrong there is nothing to fall back to. A service write may also need to
reset the counter.

### 20. Can I use this repository's scripts on a healthy device?

Yes — they are read-only by design. Nothing in `scripts/` writes to the device. They
inspect the melf container, upload a programmer, and listen. The upload itself does
not modify storage; the programmer is what would, and it never started.

### 21. The scripts reference paths like `<ROM_DIR>`. How do I set them?

Every script takes the programmer path on the command line. See
[`../scripts/README.md`](../scripts/README.md).

### 22. Why is this in English if the work was in Polish?

So it is useful to anyone who finds a `TB520FU` in this state. The original Polish
session notes are preserved in [`../session-notes/`](../session-notes/) alongside the
translations, so nothing was lost in the process.

### 23. Can I contribute a fix?

Yes — especially if you have a programmer that gets past `DONE` with a live Firehose
endpoint on this platform, a UART capture, or confirmation of which shutdown
hypothesis is correct. Open an issue.

### 24. Was any of this dangerous?

The investigation itself, no — it was read-only. The *history* was dangerous: flashing
a pivot initramfs to `init_boot`, then an ABL for different hardware to both ABL
slots. Everything in this repository is the consequence.

### 25. Do I have to use the web form and wait for the email to unlock?

No. The unlock file is served from a CDN path with the serial in the URL and no
authentication:

```
http://cdn.zui.lenovomm.com/developer/tabletboot/<SERIAL>/sn.img
```

```bash
python scripts/get_unlock_file.py --serial <SERIAL> --verify
```

Use plain HTTP — the CDN's HTTPS certificate does not match its hostname. The file
is signed per serial, so it will not work on a different device. Full details in
[`12-bootloader-unlock.md`](12-bootloader-unlock.md).

### 26. Is the unlock file generic? Can someone share theirs with me?

No. It contains your serial in plaintext at offset `0x800` plus an X.509 signature
over it. Another device's file, or an edited serial, will be refused. You have to
download your own.

### 27. I typed my serial and got a 404.

The server only answers for serials it knows, so a 404 almost always means a typo
rather than a server problem. Check: 8 characters, uppercase, no spaces, no `S/N:`
prefix. Confirm the value with `adb shell getprop ro.serialno` or
`fastboot getvar serialno` — and make sure you are using the serial, not the model
number (`TB520FU`) or the IMEI.
