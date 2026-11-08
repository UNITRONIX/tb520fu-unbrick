# Service documents — Polish originals with English translations

*Originals: `SERWIS_OPIS_USTERKI.txt`, `SERWIS_KROKI.txt`, `SERWIS_KROTKO.txt`.*

These are kept in the original Polish **and** translated, because the Polish version is
the document a repair centre actually read, and the wording was deliberate: plain,
non-technical, and focused on what the service needs to know rather than what was
attempted.

The device serial has been replaced with `<DEVICE_SERIAL>` in the published version.

---

## 1. Fault description

### Original (Polish, verbatim)

> Lenovo TB520FU, nr seryjny `<DEVICE_SERIAL>`. Tablet był przygotowywany do wdrożenia w
> projekcie firmowym i w trakcie zmiany konfiguracji oprogramowania systemowego, w tym
> warstwy bootloadera, operacja nie zakończyła się powodzeniem. Urządzenie nie uruchamia
> systemu Android - po włączeniu wyświetla logo Lenovo i przechodzi w tryb diagnostyczny
> Qualcomm, cyklicznie powtarzając tę sekwencję. Nie działa tryb fastboot ani recovery.
> Urządzenie jest sprawne sprzętowo: brak uszkodzeń mechanicznych, obudowa i ekran
> nietknięte, bateria ładuje się prawidłowo, komunikacja z komputerem w trybie ratunkowym
> Qualcomm działa poprawnie. Diagnostyka potwierdziła, że warstwa sprzętowa i niższe etapy
> bootowania są sprawne, a uszkodzona jest wyłącznie zawartość partycji bootloadera.
> Proszę o przywrócenie urządzenia do stanu fabrycznego przez wgranie oryginalnego
> oprogramowania producenta, z nadpisaniem obu partycji bootloadera. Dane użytkownika nie
> wymagają zachowania.

### English translation

> Lenovo TB520FU, serial `<DEVICE_SERIAL>`. The tablet was being prepared for deployment in
> a company project, and during a change to the system software configuration — including
> the bootloader layer — the operation did not complete successfully. The device does not
> start Android: on power-on it displays the Lenovo logo and then enters Qualcomm
> diagnostic mode, repeating this sequence cyclically. Neither fastboot nor recovery works.
> The device is hardware-healthy: no mechanical damage, the housing and screen are intact,
> the battery charges correctly, and communication with a computer in Qualcomm emergency
> mode works correctly. Diagnostics confirmed that the hardware layer and the lower boot
> stages are functional, and that the only damaged element is the content of the bootloader
> partitions. Please restore the device to factory condition by flashing the original
> manufacturer software, overwriting both bootloader partitions. User data does not need to
> be preserved.

### Why it was worded this way

Three deliberate choices, worth recording:

**"in a company project"** — establishes a legitimate business context for a device that
has been modified, without claiming it was not modified. A service centre that hears
"rooted and bootloader-swapped" may decline; a service centre that hears "software
configuration change that failed" will assess the device.

**"the only damaged element is the content of the bootloader partitions"** — this is the
technical finding, stated as a conclusion rather than an argument. It tells the technician
where to look and, implicitly, that they do not need to redo the diagnosis.

**"user data does not need to be preserved"** — removes a constraint. It permits the
service to use any destructive restore path, which is the fastest one.

---

## 2. Diagnostic sequence

### Original (Polish, verbatim)

> Lenovo TB520FU, nr seryjny `<DEVICE_SERIAL>` — przebieg diagnostyki i efekt
>
> 1. Normalne uruchomienie, próba wejścia w fastboot i recovery — bez efektu. Po włączeniu
>    logo Lenovo, następnie tryb diagnostyczny Qualcomm, sekwencja powtarza się w kółko.
>    Fastboot ani recovery nie startują.
> 2. Próba wejścia w menu bootloadera klawiszami Vol+/Vol− przy starcie — klawisze nie są
>    odczytywane przez bootloader, menu nieosiągalne.
> 3. Wymuszenie trybu ratunkowego Qualcomm EDL, w tym próba z kablem EDL — tryb osiągnięty,
>    komunikacja z urządzeniem działa poprawnie, urządzenie odpowiada na protokół.
> 4. Wgranie oryginalnego loadera fabrycznego z paczki ZUI 18.5.10.037 przez protokół
>    Sahara — transfer kompletny (1 554 996 B), urządzenie potwierdza przyjęcie obrazu, ale
>    nie uruchamia sesji zapisu — cisza na wszystkich komendach i powrót do trybu
>    diagnostycznego. Powtórzone wielokrotnie, wynik identyczny.
> 5. Cztery niezależne narzędzia (własny klient USB, edl, QSaharaServer + fh_loader, LTBox)
>    oraz dwa systemy operacyjne (Windows i natywny Linux) — wynik zawsze taki sam, problem
>    nie leży po stronie komputera ani narzędzi.
> 6. Próba użycia własnego loadera (podpisanie kluczami testowymi, podmiana obrazu wewnątrz
>    pliku fabrycznego) — odrzucona przez procesor startowy kodem błędu. Weryfikacja
>    integralności obejmuje cały podpisany blok, bez klucza producenta nie da się tego
>    obejść.
> 7. Podejrzenie zbyt niskiego napięcia baterii — wykluczone po 9 godzinach ładowania
>    (pełny, czysty cykl kontrolny).
> 8. Pomiar obecności urządzenia na bramce USB z rozdzielczością 0,15 ms w oknie logo —
>    tablet w tym czasie nie pojawia się na magistrali USB w żadnym trybie.
>
> Wniosek: uszkodzona jest wyłącznie zawartość partycji bootloadera (abl_a / abl_b).
> Sprzęt i niższe etapy startu są sprawne. Niezbędny jest zapis tych dwóch partycji z
> poziomu serwisowego dostępu EDL. Dysponuję gotowymi obrazami wzorcowymi (1 MiB każdy, z
> sumami SHA256) wraz z adresami: abl_a LUN 4 / sector 95238, abl_b LUN 4 / sector 437686.

### English translation

> Lenovo TB520FU, serial `<DEVICE_SERIAL>` — diagnostic sequence and outcome
>
> 1. Normal power-on, attempt to enter fastboot and recovery — no effect. On power-on the
>    Lenovo logo appears, then Qualcomm diagnostic mode; the sequence repeats in a loop.
>    Neither fastboot nor recovery starts.
> 2. Attempt to enter the bootloader menu with the Vol+/Vol− keys at boot — the keys are not
>    read by the bootloader, the menu is unreachable.
> 3. Forcing Qualcomm EDL emergency mode, including an attempt with an EDL cable — mode
>    reached, communication with the device works correctly, the device responds to the
>    protocol.
> 4. Flashing the original factory loader from the ZUI 18.5.10.037 package over the Sahara
>    protocol — transfer complete (1 554 996 B), the device confirms acceptance of the
>    image, but does not start a write session — silence on all commands, then a return to
>    diagnostic mode. Repeated many times, identical result.
> 5. Four independent tools (a custom USB client, `edl`, `QSaharaServer` + `fh_loader`,
>    LTBox) and two operating systems (Windows and native Linux) — always the same result;
>    the problem is not on the computer or tool side.
> 6. Attempt to use our own loader (signing with test keys, substituting an image inside the
>    factory file) — rejected by the boot processor with an error code. Integrity
>    verification covers the entire signed block; without the manufacturer's key it cannot
>    be bypassed.
> 7. Suspicion of insufficient battery voltage — excluded after 9 hours of charging (full,
>    clean control cycle).
> 8. Measurement of the device's presence on the USB bus at 0.15 ms resolution during the
>    logo window — during this time the tablet does not appear on the USB bus in any mode.
>
> Conclusion: only the content of the bootloader partitions (abl_a / abl_b) is damaged. The
> hardware and the lower boot stages are functional. Writing these two partitions from
> service-level EDL access is required. I have verified reference images available (1 MiB
> each, with SHA256 sums) together with the addresses: abl_a LUN 4 / sector 95238, abl_b
> LUN 4 / sector 437686.

---

## 3. Short version

### Original (Polish, verbatim)

> Ustalone: uszkodzona zawartość partycji bootloadera (abl_a/abl_b); logo, potem pętla trybu
> diagnostycznego Qualcomm; brak fastboot i recovery; EDL działa, transfer loadera
> kompletny, sesja zapisu nie startuje; sprzęt sprawny.

### English translation

> Established: damaged content of the bootloader partitions (abl_a/abl_b); logo, then a
> loop of Qualcomm diagnostic mode; no fastboot and no recovery; EDL works, the loader
> transfer is complete, the write session does not start; hardware functional.

---

## 4. What was deliberately omitted from the submitted documents

The service documents do not mention:

| Omitted | Why |
|---|---|
| That the ABL was replaced with a build for other hardware | Technically irrelevant to the repair, and it invites a warranty argument rather than a technical one. The statement "bootloader layer change did not complete" is accurate and sufficient. |
| The pivot initramfs | Same reason; it was a separate earlier mistake that was recoverable. |
| Unlocking and Magisk | Not relevant to the two writes; the device is already unlocked, which the service will see anyway. |
| The full dead-end list | The one thing the service *does* need is "do not waste time on X" — which is conveyed by presenting the diagnosis as settled, not by documenting every attempt. |
| Serial number | Redacted in this public version only. |

This is a judgement call and worth stating plainly: the submitted document is a
**technical brief for a repair**, not a confession. It states what is broken, what is
needed, and what has been ruled out. Everything else is in this repository.

See [`../docs/09-service-report.md`](../docs/09-service-report.md) for the English
version with the payload manifest and the "what not to do" guidance.
