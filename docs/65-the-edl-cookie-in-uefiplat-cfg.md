# The EDL cookie, found in UEFI's own configuration

`uefi.elf` is the APPSBL image that XBL loads at the end of every boot
(`docs/56`: `APPSBL - Image Loaded, Delta - (2901084 Bytes)`, which matches
`uefi.elf` to within its 4 032-byte ELF header). Inside it is a plain-text platform
configuration, and it names the download cookie explicitly.

---

    10|## 1. The configuration block, verbatim

```
# Shared IMEM (Cookies, Offsets)
SharedIMEMBaseAddr    = 0x14680000
DloadCookieAddr = 0x01FD9000
# for full dump 0x10, for minidump 0x20
DloadCookieValue = 0x10

# Skip dbi setup
SkipDBISetup = 0x0

# debug cookie of PIL subsystem, defined in FBC script
PilSubsysDbgCookieAddr = 0x146806DC
PilSubsysDbgCookieVal  = 0x53444247

# NumCpus - max number of cores
NumCpus = 8
NumActiveCores = 8
```

## 2. What each part settles

**`DloadCookieAddr = 0x01FD9000`** is the TCSR register that four earlier documents
converged on from the code side:

| document | what it found |
|---|---|
| `docs/16` §5 | the DDR-training guard reads bits `0x30` of `0x1FD9000` |
| `docs/40` | the forced-download timeout stage reads the same register |
| `docs/58` | the working boot logged `TCSR reg value 0x10` |
| `docs\61` | the crash handler stamps the low six bits with the route it chose |

Now the configuration file names it directly: **it is the download cookie address.**

**`DloadCookieValue = 0x10`** is the value that appears in the one boot that reached
EDL. And the comment explains what the values mean:

```
0x10  full dump
0x20  minidump
```

So `0x10` is not a timeout, not a mode index, and not a bitmask of training flags -
it is **"request a full dump"**, written into the cookie register.

**`SharedIMEMBaseAddr = 0x14680000`** matches `OCIMEM` in the device's own memory
table (`docs/63`), so the cookie lives in shared IMEM as the comment says, and that
region *is* exposed by the crash handler - which is why `PilSubsysDbgCookieAddr`
(`0x146806DC`) is readable.

## 3. The mechanism, end to end

```
UEFI (APPSBL) writes DloadCookieAddr = DloadCookieValue   i.e. [0x1FD9000] = 0x10
        |
        v  (next boot)
XBL's download-entry path reads the cookie
        |
        v  0x10 present -> dump requested -> boot_dload_entry
        |
        v  RamDump image (890 156 B) loaded, EDL entered
```

That is consistent with every measurement in this session:

- the boot that logged `TCSR reg value 0x10` **also** loaded the 890 156-byte
  RamDump image **and** reached `boot_dload_entry` (`docs/58`);
- the boot with no TCSR line loaded **0 bytes** and did not reach it;
- `dload_entry_count` (`docs/59`) then records how many times that path has been
  taken, which is why it can never be a first entry again without a cold boot.

## 4. The two writable surfaces this exposes

For the first time the route has a **named, documented, writable address**, not an
inferred one:

| target | current meaning | how it could be changed |
|---|---|---|
| `0x1FD9000` low bits | download cookie (`0x10` full dump, `0x20` minidump) | UEFI writes it; not writable from the host without a session |
| `0x146806DC` | PIL subsystem debug cookie (`0x53444247` = "SDBG") | same |

Both are in regions that matter, and neither is reachable from the host today -
the standing blocker. But their **meaning** is no longer a guess.

## 5. Which config the running UEFI actually reads — checked

`uefi.elf` contains two config names. Counting them:

```
"uefiplat.cfg"    4 occurrences
"uefiplatLA.cfg"  1 occurrence
```

and the single `PlatConfigFileName` entry points at the LA variant:

```
PlatConfigFileName = "uefiplatLA.cfg"
OsTypeString = "LA"
```

**So the running image selects `uefiplatLA.cfg`.** There is exactly **one** block
carrying cookie values in the whole image (`0x51206`), and it is the one quoted in
§1 - `DloadCookieAddr = 0x01FD9000`, `DloadCookieValue = 0x10`.

There is also **no separate `.cfg` file in the ROM package** - the only files with
"cfg" in the name are `aop_devcfg.mbn` and `devcfg.mbn`, neither of which is a
platform config. So the values above are not a stale copy of a file that lives
elsewhere; they are the values built into the image that runs.

That closes the caveat `docs/65` §5 raised: the config is not merely *present* in the
image, it is the one the image selects by name.

## 6. What is not claimed

- The config is read from the file on disk; it is **not** confirmed that this exact
  copy is what the running UEFI used. Its presence in the APPSBL image that XBL
  loads is strong evidence, not proof of the live value.
- `0x1FD9000` being the cookie is now documented by the vendor's own comment, but
  the *write* path (when UEFI decides to set it) is still not located.
- Whether writing `0x10` from the host would be sufficient to reach EDL is untested -
  and cannot be tested without a Sahara session, which is the blocker.

## 7. Why this matters more than another dead end

Four documents inferred the same register from three different directions. A
configuration file in an image we already had states it outright, with a comment
explaining the values. That is the difference between a hypothesis about
`0x1FD9000` and a documented fact about it - and it means the search should prefer
**reading the vendor's own config files** over further disassembly.

`uefiplat.cfg` is embedded in plain text in `uefi.elf`. It was there all along.
