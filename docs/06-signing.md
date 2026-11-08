# Signing: what it does, and why it was not the problem

Signing consumed more time than any other line of investigation, and every hour
was misdirected. This document exists so the next person skips it.

**Short version:** the device was never rejecting our signature. It was rejecting
our file format, 64 bytes in, before any signature could be examined. Signing was
a plausible-looking answer to the wrong question.

---

## 1. What qtestsign actually does

`qtestsign` is GPL-2.0, small, and honest about itself. From its own README:

> There is actually **no signature generated!** This works only for devices that
> have firmware secure boot **disabled**.

What it produces is MBN packaging:

```
input ELF
  ├─ MBN header            (version, cert chain pointer and size)
  ├─ per-segment SHA-256   (the "hash segment")
  ├─ stub signature        (256 B, ZERO — not a real signature)
  └─ dummy certificate chain
        "qtestsign Root CA - NOT SECURE"
        "qtestsign Attestation CA - NOT SECURE"
```

The private keys are in the repository in plaintext, deliberately, for
reproducibility. There is nothing to break, because nothing is locked.

The practical consequence: qtestsign works **only where secure boot is off**. It
does not defeat secure boot; it produces a file that a permissive loader will
accept.

---

## 2. Why it looked like the answer

The device returned `0x23` — `SAHARA_NAK_HASH_TABLE_NOT_FOUND` — for a plain
`prog_firehose_ddr.elf`. qtestsign adds exactly that: a hash table. The reasoning
was clean:

1. Device says "no hash table".
2. qtestsign adds a hash table.
3. Therefore qtestsign should satisfy it.

There was also supporting evidence that this device tolerates test certificates:
**XBL had already accepted a ROCKNIX ABL signed with qtestsign.** So the chain of
trust above Sahara was known to accept those certificates.

Both observations are true. The inference was still wrong, for a reason that only
became visible later.

---

## 3. What was built and tested

Three variants of a qtestsign-signed Firehose:

| Variant | Size | Structure |
|---|---|---|
| `-v7 prog` | 303 104 B | MBN header v7, cert chain 1632 B, SW_ID 0x03 |
| `-v6 prog` | 303 104 B | MBN header v6, same chain |
| `-v7 abl` | 303 104 B | SW_ID 0x1C instead of 0x03 |

The v7/prog variant matched the structure of the ROCKNIX ABL that XBL had
accepted, on every parameter except `SW_ID` — where the difference is correct
(firehose is `prog`, ABL is `abl`).

Result:

```
signed-v7-prog   303 104 B   END status=0x29  after 64 bytes
signed-v6-prog   303 104 B   END status=0x29  after 64 bytes
signed-v7-abl    303 104 B   END status=0x29  after 64 bytes
unsigned         303 096 B   END status=0x29  after 64 bytes
```

**Identical to the unsigned file.** Signing changed nothing at all.

---

## 4. The 64 bytes that settle it

`0x29` is returned after **64 bytes**. That is the size of what Sahara reads to
classify a payload. The decision is made on the header, before the hash table —
which lives later in the file — could possibly be examined.

So the ordering is:

```
bytes 0..63      header read      → format decision here  → 0x29
bytes 64..       never reached
hash table       never examined
certificates     never examined
```

`0x29` is also **not in the published NAK table**, which ends at `0x28`. It is a
vendor extension. Its meaning has to be inferred from behaviour, and the behaviour
is unambiguous: this PBL accepts only a `melf` (ELF32 container), and rejects a
plain ELF64 regardless of what is appended to it.

The `0x23` that started the whole signing theory was a *different* situation: an
ELF that did reach the hash-check stage. Once the container problem was understood,
`0x23` became irrelevant — we were no longer sending bare ELFs.

---

## 5. Why the ROCKNIX ABL precedent misled

XBL accepting a qtestsign-signed ABL proves that XBL does not enforce a
Lenovo-only root of trust at the ABL stage. True and useful.

But it says nothing about **PBL**, which is a different component with a separate
policy, and nothing about the **format** requirement, which is a parsing rule, not
a trust rule.

Two separate mechanisms were conflated:

| Mechanism | Question it answers | Enforcement point |
|---|---|---|
| Format | is this a payload I can parse? | PBL, at 64 bytes |
| Integrity | is this blob unmodified? | PBL, at `END` |
| Trust | was this signed by someone I trust? | PBL / XBL, after the above |

The investigation treated a failure of the first as a failure of the third.

---

## 6. The signed melf attempt, and why it also failed

A melf was rebuilt with a qtestsign-signed Firehose substituted at `0x110B50`,
preserving every offset (the signed image was trimmed by 8 bytes of trailing zeros
so the total size matched the original exactly).

This was a genuinely good idea: it addressed the format problem (still a melf) and
the integrity problem (a signed inner image). Result:

```
END status=0x21   bytes=1109804/1569028
```

`0x21` = `HASH_TABLE_AUTH_FAILURE`, at byte 1 109 804 — **before** the substituted
image at 1 117 008.

The device rejected the container before reaching the modification. Which means it
is not verifying images individually: it is verifying the blob as a unit, and the
table it verifies against is not in the file.

That closed the signing path permanently. Details in
[`04-melf-format.md`](04-melf-format.md).

---

## 7. What signing *would* require

For completeness, since people ask:

1. The exact byte range PBL hashes over, and the algorithm.
2. The hash table structure and its required location.
3. A signature over that table using a key PBL trusts.

Items 1 and 2 are reverse-engineerable in principle from the factory melf, with
much more work. Item 3 is Qualcomm's private key. There is no path to it, and no
shortcut around it.

Note that even a successful forgery would still need to solve the *runtime*
problem — a valid programmer that never binds Firehose to USB is still useless.
Signing was never going to be sufficient, only necessary.

---

## 8. If you are tempted to try signing anyway

Reasons it can still be worth doing, honestly stated:

- If your device returns `0x23` **and** accepts melf-format payloads, a signed
  inner image might get past a per-image check. Ours does not work that way, but
  a different firmware revision might.
- Reproducing the `0x21` result yourself takes minutes with
  [`scripts/build_signed_melf.py`](../scripts/build_signed_melf.py) and settles the
  question for your unit.

Reasons to skip it:

- If you see `0x29` after 64 bytes, signing is definitively not your problem.
- If you see `0x21` at an offset earlier than your modification, the container is
  checked as a whole and per-image signing cannot work.

Both diagnostics are one command away and cost less than an hour. Do those before
building anything.

---

## 9. Summary

| Claim | Verdict |
|---|---|
| "qtestsign creates a real signature" | False — it creates a zero stub and dummy certs. |
| "The device rejected our signature" | False — it rejected the format, 64 bytes in. |
| "XBL accepts qtestsign, so PBL will too" | Conflates two components with separate policies. |
| "Signing the melf would work" | Refuted — `0x21` before the substitution point. |
| "Signing is therefore useless to know about" | No — it is how the format/integrity/trust layers were separated, which is the main result. |
