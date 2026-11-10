# XBL: mechanizmy, których wcześniej nie sprawdzono

Data: 2026-11-08 (późny wieczór). Punkt wyjścia: pytanie „czy da się uzyskać klucze
i podpisać własny kod".

**Odpowiedź na pytanie o klucze: nie.** Ale przy okazji sprawdzenia odkryto, że
**`xbl_s.melf` nie jest zaszyfrowany** — ma 2 307 czytelnych stringów — a w nich
logikę bootowania, której nikt wcześniej nie przeczytał. To jest nowy materiał.

Źródło: `image\xbl_s.melf` z pakietu ZUI 18.5.10.037, 1 117 008 B.
Skrypty: `scripts/explore_xbl.py`, `xbl_recovery.py`, `xbl_edl_triggers.py`,
`xbl_combos.py`, `who_draws_battery.py`.

---

## 1. Dlaczego klucze są nieosiągalne (odpowiedź na pytanie)

Porównanie łańcuchów certyfikatów — to rozstrzyga sprawę definitywnie:

| plik | łańcuch |
|---|---|
| `abl.elf` (stock ZUI 18.5, 270 136 B) | `Lapis Attestation CA1`, `Lenovo Root CA1`, `Lenovo Company1`, `Lapis Root CA1` |
| ROCKNIX ABL (qtestsign, 258 048 B) | `qtestsign Root CA - NOT SECURE`, `qtestsign Attestation CA - NOT SECURE` |

To **dwa różne światy zaufania**:

- `qtestsign` to nie podpis — z README: *„There is actually no signature generated!
  This works only for devices that have firmware secure boot disabled."*
  Klucze są publiczne, bo niczego nie chronią.
- Stock ABL jest podpisany przez **Lenovo/Lapis Root CA** — klucz prywatny Lenovo.

**Kluczy Lenovo nie da się „gdzieś uzyskać".** Nie ma wycieku, nie ma backdoora,
nie ma skrótu. XBL przyjął ROCKNIX ABL tylko dlatego, że bootloader był
**odblokowany** (`verifiedbootstate=orange`) — czyli kontrola była wyłączona, a nie
obejdzieta.

Podmiana fragmentów partycji też nie działa — i to jest **zmierzone, nie założone**:
podmiana obrazu wewnątrz melf daje `0x21` na bajcie 1 109 804, czyli **7 204 B
przed** podmienionym obrazem (1 117 008). Kontener jest weryfikowany jako całość.

---

## 2. ODKRYCIE: XBL ma własne wyjście do EDL

To najważniejsza nowa informacja. XBL nie jest tylko pośrednikiem — **sam potrafi
wejść w tryb download**, niezależnie od ABL.

```
0x00bb0eb  boot_fedl_check
0x00bb0fb  boot_dload_handle_forced_dload_timeout
0x00bb59e  boot_dload_entry
0x00bb5af  EDL: sbl1_dload_entry: dload_entry_count > 1
0x00bb6ca  EDL: boot_fedl_check
0x00bdd08  Enter PBL EDL PCIe
0x00bdd1b  Enter PBL EDL USB
0x00bddef  /sw/boot/fedl_timeout
0x00bdd97  EMERGENCY_DLOAD_TIMEOUT_COOKIE_SET: Powerdown
0x00bddc5  EMERGENCY_DLOAD_TIMEOUT_COOKIE_SET: Reset
0x00c23f2  enter forced EDL
0x00c3fe7  dpGnd LOW, enter FEDL
```

Co to znaczy: **XBL ma licznik wejść do dload** (`dload_entry_count`). Jeśli
urządzenie wpada w EDL wielokrotnie, XBL to wykrywa i obsługuje inaczej. Istnieje
też `fedl_timeout` z akcją (`Powerdown` / `Reset`) — czyli ścieżka awaryjna.

Notatki znały tylko `dpGnd LOW, enter FEDL` (kabel EDL) i uznały, że „daje ten sam
wynik 7,94 s". **Nie sprawdzono `dload_entry_count` ani `fedl_timeout`.**

---

## 3. ODKRYCIE: klawisze czyta XBL, nie ABL

```
0x00bbc0c  %s/s2-kpdpwr
0x00bbc1f  s2-ms
0x00bbc2f  %s/s2-kpdpwr-resin
0x00bbc52  %s/s2-resin
0x00bbc5e  s2_resin
0x00c34dd  VOL-
0x00c3627  Error getting VOL- button status
0x00c36d5  /soc/buttons/buttons-config
0x00c36f1  /soc/buttons/platform-key-maps
0x00bccf7  Boot up PwrKey press %d ms detected is less than expected %d ms duration. Shutting down device.
```

XBL ma **własny** podsystem przycisków: `boot_buttons.c`, konfigurację z DT
(`/soc/buttons/buttons-config`), mapy klawiszy i **trzy obsługiwane kombinacje S2**:

| kombinacja | nazwa DT |
|---|---|
| Power | `s2-kpdpwr` |
| Power + Vol− | `s2-kpdpwr-resin` |
| Vol− | `s2-resin` |

To obala wcześniejsze ustalenie „klawisze nie są czytane". Są czytane — **przez XBL,
na poziomie PMIC PON**, zanim ABL w ogóle wystartuje. Wcześniejsze testy mierzyły
skutek w ABL, nie w XBL.

String `Boot up PwrKey press %d ms ... Shutting down device` pokazuje, że XBL mierzy
**czas trzymania** i potrafi wyłączyć urządzenie, jeśli jest za krótki. To wyjaśnia
część nieudanych prób.

---

## 4. ODKRYCIE: XBL ma mechanizm recovery partitions

```
0x00bb1da  boot_recovery_partitions_info_smem_init
0x00bb2c3  boot_check_recoveryinfo_partition
0x00bb310  boot_recovery_select_boot_partitions
0x00bb335  boot_recovery_partitions_info_imem_init
0x00bb35d  boot_save_sbl_recovery_partition_info
0x00bb3b1  boot_update_abnormal_reset_status
```

To standardowa maszyneria Qualcomma: partycja `recoveryinfo` + licznik
`abnormal_reset_status`. XBL może **wybrać inne partycje startowe po serii nieudanych
bootów**. Nie sprawdzono, czy na tym urządzeniu licznik się zapełnia i czy prowadzi
gdziekolwiek użytecznym.

---

## 5. Kto rysuje ekran baterii — nadal nieustalone

| plik | trafienia „battery"/“charg" |
|---|---|
| `xbl_s.melf` | **16** (`boot_usb_handle_charger`, `Charger:%s V%s`, `battery-low-threshold-mv`, `Battery recovered`, `charger is not charging and device will shut down`) |
| `abl.elf` | **0** — plik zaszyfrowany/kompresowany |
| ROCKNIX ABL | **0** — potwierdzone: entropia 7.97 bit/B |

ABL stock jest zaszyfrowany, więc brak stringów **nie dowodzi**, że nie rysuje
ekranu. Ale fakt, że XBL ma pełną obsługę chargera i logikę
`Boot up PwrKey press ... Shutting down device`, sugeruje, że **ekran może pochodzić
z XBL**.

Gdyby tak było, wyjaśniałoby to wszystko naraz: ABL nigdy nie startuje (XBL kończy na
swoim ekranie ładowania), dlatego brak menu, brak fastboota, brak reakcji na klawisze
w ABL — a jednocześnie XBL spokojnie czyta klawisze.

**To pozostaje hipotezą** — wymaga potwierdzenia, np. przez UART.

---

## 6. Co to otwiera (kandydaci do testu, w kolejności)

| # | Test | Koszt | Co rozstrzyga |
|---|---|---|---|
| 1 | **Power + Vol− trzymane ~2 s, przed podłączeniem kabla**, potem kabel — i nasłuch 0.15 ms na dowolne VID:PID | minuty, zero ryzyka | czy `s2-kpdpwr-resin` daje EDL z XBL |
| 2 | To samo, ale z **kablem EDL** (D+ do masy) — sekwencja zgodna z `wait unplug(dpGnd LOW)` | minuty | czy `boot_fedl_check` przechodzi |
| 3 | **Trzy kolejne nieudane booty** → sprawdzić, czy `dload_entry_count > 1` coś zmienia | ~5 min, obserwacja | czy licznik dload daje inne zachowanie |
| 4 | Powtórzyć z **naładowaną baterią** (próg UFS `BatteryThresholdMv = 3600`) | wymaga ładowania | wykluczyć DBC |

Każdy z tych testów był **niemożliwy wcześniej**, bo nie wiedzieliśmy, że XBL ma
te mechanizmy. Teraz wiadomo, czego szukać.

**Nie testować:** podpisywania (klucze Lenovo — ślepa ulica), podmiany obrazów w melf
(`0x21` przed punktem podmiany).
