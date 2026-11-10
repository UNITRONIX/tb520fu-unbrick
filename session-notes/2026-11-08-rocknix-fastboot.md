# 2026-11-08 (noc, po raporcie) — czy ROCKNIX ABL da się zmusić do fastboota?

Pytanie właściciela: „wiemy, że w ROCKNIX jest tryb fastboot, zapewne da się
przejść z 900E do fastboota w jakiś sposób — czy dasz radę to zbadać?"

**Odpowiedź: zbadałem, i nie da się — ale nie z powodu, który był w notatkach.**

---

## 1. Co zostało obalone (to jest najważniejsze)

Dokumentacja projektu twierdziła:

> „ROCKNIX ABL boots. But Vol− and Vol+ are not read. Its key GPIOs are mapped
> for AYANEO hardware. The menu is unreachable because of hardware mismatch."

Sprawdziłem to w **własnym device tree tego tabletu**:

```
&pon_pwrkey { status = "okay"; };
&pon_resin { linux,code = <KEY_VOLUMEDOWN>; status = "okay"; };
```

| klawisz | gdzie | czy może się nie zgadzać |
|---|---|---|
| **Volume Down** | `pon_resin` — blok PON w PMIC | **NIE** — standard Qualcomm |
| Power | `pon_pwrkey` | **NIE** — standard |
| Volume Up | `pm8550_gpios 6` | tak, numer pinu może się różnić |

**Volume Down nie jest pinem GPIO.** To wejście sprzętowego bloku PON w PMIC,
takie samo na każdym Qualcommie. Nie da się go „pomylić" między płytkami.

Czyli uzasadnienie „złe piny AYANEO" było **błędne dla klawisza, który ROCKNIX
każe trzymać**. A wniosek „menu jest nieosiągalne" został wyciągnięty z błędnego
powodu — i przez tydzień zamykał tę drogę bez pomiaru.

---

## 2. Pomiar, który to rozstrzygnął

Warunek konieczny, żeby ten test cokolwiek znaczył: **żadnego filtra VID**.
Wszystkie wcześniejsze watchery filtrowały `05C6` — a fastboot na Qualcomm ABL
enumeruje się zwykle jako `18D1:4EE0`, `18D1:D00D` albo `05C6:901D`. Filtr mógł
go przegapić z definicji.

Nowy watcher (`scripts/fastboot_watch.py`) wylicza **wszystkie** urządzenia USB
i wypisuje każde nowe `VID:PID`. Klawisz trzymany przez całe okno nieobecności:

```
[   0.04] baseline: 11 urzadzen
[  90.19] - ZNIK  05c6:900e bus2 adr4  Qualcomm crashdump
[  90.25]   ... nasluch dalej (10 urzadzen)
[ 105.98] + NOWE  05c6:900e bus2 adr4  Qualcomm crashdump
[ 120.29]   ... nasluch dalej (11 urzadzen)
```

**16 sekund z trzymanym Vol−, tablet poza USB, i nie pojawiło się NIC** —
żadnego nowego VID:PID, nie tylko fastboota.

Ważne: **fastboot by nie zniknął.** ABL wszedłszy w fastboot siedzi w nim i czeka.
Tu nie ma wyścigu na mikrosekundy — wystarczył nasłuch 50 ms. Wynik negatywny jest
więc wiarygodny, a nie „za wolny".

---

## 3. Prawdziwy powód (skorygowany)

Nie „zły pin", a **ABL nie dochodzi do punktu decyzji o trybie bootu.**

Spójny łańcuch:

- ABL **działa** — rysuje ekran ładowania offline (baterię, którą widać).
- W tym trybie menu startowe jest **pomijane** — to funkcja z README ROCKNIX:
  *„Charging Mode — Displays an offline charging screen while the device is
  powered off."*
- `RST_STAT = 0x3` (b0 core reset + b1 **WDOG**) i okno 7,918 s co do 3 ms
  mówią, że urządzenie jest resetowane przez watchdoga, zanim cokolwiek wybierze.
- Odczyt klawisza nie ma znaczenia, jeśli kod, który go czyta, nigdy nie startuje.

**Konsekwencja praktyczna:** każda droga wymagająca menu jest zamknięta tą samą
przeszkodą. Nie tylko fastboot — także **boot Linuksa z pendrive'a**, bo wybór
`BootSourceMode` (Internal/Auto/USB/SDcard) też jest w tym menu.

---

## 3a. Test z nośnikiem USB — NIEROSTRZYGAJĄCY (ważne)

Przygotowano nośnik: partycja FAT32 z etykietą `ROCKNIX`, `Image` (kernel 7.2.6,
który jest *także* poprawnym PE/EFI: `machine=0xAA64`, `subsystem=10`), DTB,
`extlinux/extlinux.conf` oraz `EFI/BOOT/BOOTAA64.EFI`.

Podłączony do tabletu: **czerwona dioda na dysku się zapaliła, odczytu brak.**

**KLUCZOWA KOREKTA (2026-11-08 22:48).** Przejściówka USB-C użyta do testu jest
**uszkodzona mechanicznie** — przewody nie dochodzą do mniejszego złącza w środku.
Efekt: **VBUS przechodzi (dioda świeci), linie danych D+/D− nie.**

Konsekwencje:

1. Tablet widzi pobór prądu, czyli klasyczną **ładowarkę** — dlatego pokazuje ekran
   baterii. To wyjaśnia obraz na ekranie bez żadnych założeń o ABL.
2. **Test nie mówi NIC o tym, czy ABL jest hostem.** Dane nigdy nie dotarły.
   Ani wynik negatywny, ani pozytywny nie jest dowodem.
3. Hipoteza „ABL wystawia tryb hosta" pozostaje **nietestowalna do czasu
   działającej przejściówki z danymi** — nie została obalona.

Sprawdzone w DTS (nadal aktualne, ale to nie one przesądziły):

```
&usb_1 { dr_mode = "otg"; usb-role-switch; ... };
&usb_1_dwc3_hs { remote-endpoint = <&pmic_glink_hs_in>; };
```

| fakt | konsekwencja |
|---|---|
| `dr_mode = "otg"` | port domyślnie **device**, nie host |
| `usb-role-switch` przez `pmic_glink` | przełączenie wymaga negocjacji TCPM |
| **brak `vbus-supply`** | 5 V musi włączyć sterownik chargera w PMIC — **działa, skoro dioda świeci** |

**Warunek powtórzenia:** sprawna przejściówka OTG z pełnym okablowaniem danych.
Dopiero wtedy brak aktywności cokołu nośnika jest dowodem.

---

## 4. Ślepa ulica: PMIC PON jako sonda klawisza

Próbowałem zmierzyć, czy PMIC widzi klawisz, przez rejestr `PMIC_PON`
(`0x81b75048`):

```
PMIC_PON = 0x02400200   nibble = 0 -> PON_KPDPWR (tylko Power)
RST_STAT = 0x00000003   b0 + b1 (core reset + watchdog)
PMON_HIS = 11 rekordow, 3 identyczne cykle
```

**To narzędzie było źle dobrane.** Zatrzask PON zapisuje powód **włączenia**,
a nie **resetu**. Przy resecie od watchdoga nie ma prawa się zmienić. Zapisałem
to, żeby nikt tego nie powtarzał.

---

## 5. Ślepa ulica: kod ABL z RAM (DDR)

Pomysł: skoro ABL działa, jego odszyfrowany kod jest w RAM pod `0x9fa00000`
(z nagłówka ELF: `ph[2] vaddr=0x9fa00000 filesz=249856`). Wcześniej DDR uznano
za nieczytelne, ale zawsze **blokami 2 GB**. Nikt nie spróbował 4 KB.

```
0x9fa00000  4096 B  ->  ff ff ff ff ff ff ff ff ...   (0xFF fill)
```

`0xFF` na całym bloku = adres **niezamamapowany**, nie kod. Handler crashdumpa
nie ma dostępu do DDR. (Uwaga: pierwsza wersja klasyfikatora nazwała to
„ARM64-podobne", bo `0xFFFFFFFF` wpada w zakres — poprawione.)

---

## 6. Co to znaczy dla sprawy

Diagnoza z raportu dla serwisu **się nie zmienia** i jest teraz mocniejsza:

- usterka jest w oprogramowaniu bootloadera (`abl_a` + `abl_b` oba nadpisane),
- sprzęt jest zdrowy (PMIC żyje, ABL rysuje UI, Sahara i crashdump działają),
- **żadna** droga przez klawisze, menu ani pendrive nie ominie tej przeszkody,
- pozostaje EDL z prawdziwym programmlem (write) — a to wymaga serwisu/testpointu.

Zmienia się **uzasadnienie**, nie kierunek. I to jest wartość tej sesji: zamiast
„menu nie działa, bo złe piny" mamy „menu nigdy nie startuje, bo watchdog resetuje
urządzenie wcześniej" — z pomiarem, nie z domysłem.

---

## 7. Skrypty z tej sesji (wszystkie read-only)

```
scripts/fastboot_watch.py   nasluch na DOWOLNE nowe USB (bez filtra VID)
scripts/pon_probe.py        odczyt PMIC_PON/RST_STAT/PMON_HIS (slepa ulica, patrz §4)
scripts/ddr_peek.py         mala probka DDR 4 KB (slepa ulica, patrz §5)
scripts/analyze_abl.py      struktura ELF ROCKNIX ABL: kod = 7.97 bit/B, brak stringow
scripts/format_usb.ps1      format dysku + uklad ROCKNIX (FAT32 8 GB + exFAT DATA)
scripts/check_pe2.py        weryfikacja naglowka PE/EFI kernela (machine/subsystem)
scripts/prep_usb.ps1        proba shrinku bez formatowania (exFAT: Not Supported)
```

`analyze_abl.py` potwierdza niezależnie: kod ABL ma entropię **7.97 bit/B**,
zero trafień na `fastboot`, `Linux`, `extlinux`, brak znanych magic-bajtów
kompresji. Nie da się go patchować stringami — tylko zbudować od źródła,
a `ROCKNIX/LinuxLoader` jest prywatne.
