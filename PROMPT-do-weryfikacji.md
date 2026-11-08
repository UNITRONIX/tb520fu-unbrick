Muszę zweryfikować trzy konkretne błędy w analizie, którą wcześniej przygotowałem, i chcę, żebyś podszedł do tego sceptycznie — zakładaj, że mogę się mylić, i sprawdzaj to na plikach, nie na moim opisie.

## Kontekst

Repo: `C:\Users\UNITRONIX\Downloads\tb520fu-unbrick` (Lenovo TB520FU / SM8650, soft brick, śledztwo wokół EDL/Sahara/Firehose).

Plik źródłowy, na którym wszystko bazuje:
`C:\ProgramData\RSA\Download\RomFiles\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\TB520FU_ROW_OPEN_USER_Q29300.0_A17_ZUI_18.5.10.037_ST_260929\image\xbl_s_devprg_ns.melf`

Są też dwie inne kopie tego samego programisty z innych paczek — **to jest kluczowy materiał porównawczy**:
- `C:\Users\UNITRONIX\Downloads\TB520FU_FW\096\TB520FU_ROW_OPEN_USER_Q00002.0_W_ZUI_17.5.10.096_ST_251127\image\xbl_s_devprg_ns.melf`
- `C:\Users\UNITRONIX\Downloads\TB520FU_FW\backup_pre_096_20261025_205920\stock_18.5_ref\xbl_s_devprg_ns.melf`

Skrypty w repo: `scripts/` (`melf_tool.py`, `find_hashes.py`, `analyze_melf_map.py`, `sahara_bump.py`).

## Błąd 1 (mój, najważniejszy) — pakiet switcha w `sahara_bump.py` ma inną długość niż w wersji, która zadziałała

W repo, `scripts/sahara_bump.py` linia ~311, wysyłam:

```python
struct.pack("<III", CMD_SWITCH_MODE, 12, MODE_IMAGE_TX_PENDING)   # 12 bajtów na drucie
```

Ale wersja, która **faktycznie zadziałała** i zostawiła ślad w logu (`catch2.log`, kod `bump: switch -> 1`), robiła:

```python
struct.pack("<IIII", SWITCH_MODE, 12, MODE_IMAGE_TX, 0)          # 16 bajtów na drucie, len=12
```
źródło: `C:\Users\UNITRONIX\Downloads\TB520FU_Linux_Port\offline-preflight\abl_rocknix_sm8650\oneshot_2026-11-08.py` linia 224

Czyli: deklarowany `len=12`, ale na drucie 16 bajtów — dodatkowe dwa zera. Napisałem w docs/14, że mój wariant jest „zgodny co do bajtu" z tym, co zadziałało. **To prawdopodobnie nieprawda.** Sprawdź:

- czy `edlclient` (`offline-preflight\edl-tools\edlclient\Library\sahara.py`, `cmd_modeswitch`) wysyła 12 czy 16,
- czy device czyta `len`, czy faktycznie konsumuje 16 (ślad w logach, zachowanie w innych skryptach),
- który wariant jest poprawny i czy mój wymaga poprawki.

Jeśli mam rację, popraw `sahara_bump.py` i zdanie w `docs/14-edl-mode-switch.md` §2.

## Błąd 2 — twierdziłem, że w pliku „nie ma tablicy hash", a potem to złagodziłem; ustal, jak jest naprawdę

W `docs/04-melf-format.md` i `README.md` napisałem, że nie znaleziono digestów obrazów wewnętrznych żadnym standardowym algorytmem. Ale w międzyczasie **rozłożyłem TLV** w obszarze `0x1074..0x1300` (payload `ph[1]`, 652 B) i wyszło:

- to TLV **little-endian z wyrównaniem wartości do 4 bajtów** (naiwny parser się rozjeżdżał, bo nie robił `align4`),
- parsuje się **dokładnie** do 652 bajtów,
- pod tagiem `0x8441` jest 64-bajtowa wartość o wysokiej entropii (`bb429dcd...`), wygląda jak SHA-512,
- pod tagiem `0x8511` jest `0x12345678` — wartość-sentinel,
- dwie 136-bajtowe wartości pod `0x81FF` wyglądają jak kolejne skróty.

Sprawdź, czy któryś z tych bloków to skrót czegoś realnego: pojedynczych obrazów wewnętrznych, ich konkatenacji, wrappera, obszarów TLV, czy konkretnych struktur ELF. Testuj też **przycięte** wersje (bez końcowego `0xFF`), wyrównane i nie. Jeśli znajdziesz dopasowanie — to zmienia dokumentację w istotny sposób.

## Błąd 3 — mocny dowód, którego wcześniej nie miałem: TLV jest identyczny w dwóch różnych buildach

Porównałem trzy kopie melfa:

| paczka | sha256 pliku | sha256 TLV (0x1074..0x1300) |
|---|---|---|
| ZUI 17.5.10.096 | `ba72961c...` | `d862fb49...` |
| stock_18.5_ref | `3f6184f9...` | `d862fb49...` |
| ZUI 18.5.10.037 | `3f6184f9...` | `d862fb49...` |

Czyli: **cały plik różni się (33 779 bajtów różnic), a TLV jest bit w bit identyczny.** Żadna różnica nie dotyka obszaru `0x1074..0x1300`.

To wygląda na **definitywne wykluczenie** hipotezy, że ten TLV jest tabelą integralności obrazów wewnętrznych — bo skoro obrazy się różnią, a tabela nie, to nie opisuje ich hashy.

**Ale sprawdź to sceptycznie:**
- czy diff na pewno nie dotyka TLV (powtórz niezależnie),
- czy obrazy wewnętrzne rzeczywiście się różnią między buildami i które,
- jeśli TLV jest stały, to **czym on jest?** Hipotezy do przetestowania: konfiguracja/feature-flags, wersja formatu kontenera, parametry DDR, coś niezależnego od zawartości obrazów.

## Czego oczekuję

1. **Konkretne wyniki**, nie streszczenie: offsety, wartości, polecenia którymi to sprawdziłeś.
2. **Wyraźne rozdzielenie**: co jest zmierzone, co jest hipotezą.
3. Jeśli któryś z moich trzech punktów jest błędny — powiedz to wprost i popraw pliki w repo.
4. Jeśli błąd 3 się potwierdzi, zaproponuj poprawkę `docs/04-melf-format.md` §5 i `docs/00-glossary.md`, bo tam twierdzę, że TLV jest „niezidentyfikowany" — a teraz wiemy o nim znacznie więcej.

Nie zmieniaj niczego poza tym, co wynika z ustaleń. Nie pisz nowych dokumentów, jeśli wystarczy poprawić istniejące.
