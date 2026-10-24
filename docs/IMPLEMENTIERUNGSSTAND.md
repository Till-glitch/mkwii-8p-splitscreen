# Implementierungsstand und Übergabe: Dolphin / 8 Wiimotes

Diese Datei ist das fortlaufende Arbeitsprotokoll für nachfolgende Agents. Nach jedem abgeschlossenen Arbeitsschritt werden Ergebnis, Prüfnachweise und nächste Schritte ergänzt. Ein begonnener oder nicht geprüfter Schritt gilt nicht als abgeschlossen.

## Auftrag und feste Rahmenbedingungen

- Nutzer hat die Implementierung und den effizienten Einsatz von Subagents freigegeben.
- Basis: Branch `esp32-support`, Hauptcommit `8c9a5e47766a33af0e58a7f82ce4497e3148a8f8`.
- Plan: [IMPLEMENTIERUNGSPLAN-DOLPHIN-8-WIIMOTES.md](IMPLEMENTIERUNGSPLAN-DOLPHIN-8-WIIMOTES.md).
- Entwicklungsrechner ohne Bluetooth. P1–P4 lokal über kontrollierte/emulierte Eingaben; später auf dem Laptop vier echte Wiimotes direkt über Dolphin.
- P5–P8 über vorhandenen ESP32 und USB. Dessen Funk benötigt kein Bluetooth-Modul im Entwicklungsrechner.
- Einstieg: Dolphin, Vanilla, PAL. Bestehende SplitScreen8-Engine erhalten; alten Renderer und D3–D7R1-Patches nicht übernehmen.
- Originales akzeptiertes Wheel-Fahrgefühl, unabhängige Spieler und vollständige Menüs haben Vorrang. 60 FPS auf dem Ziel-Laptop sind noch nicht nachgewiesen.
- Keine Firmware ohne Prüfung des ausgewählten Geräts flashen. Keine Spielabbilder oder extrahierten Nintendo-Ressourcen in Git aufnehmen.

## Aktueller Gesamtstatus

- [x] Ausführlicher Plan anhand von Hauptrepo, gepinnten Pulsar-Quellen und altem Referenzcode erstellt.
- [x] Plan auf getrennten Entwicklungsrechner und Ziel-Laptop angepasst.
- [x] Submodule und Toolchain für lokalen Vanilla-Build bereit.
- [x] Unveränderte Buildbasis erfolgreich kompiliert und Hashes gesichert.
- [x] Gemeinsamer versionierter Transportvertrag und Protokollparser implementiert; 28 Python-Prüfungen erfolgreich.
- [x] Referenzfirmware kontrolliert portiert, gebaut und auf ESP32 an COM3 geflasht (1MB-Backup gesichert).
- [x] Gastseitiger Bridge-Eingabepfad integriert und gebaut (BridgeWheelController, CAP_WHEEL_INPUT=3, TakePad-Bindung).
- [x] Live-Kopplung Dolphin + Host-Bridge + ESP32 verifiziert (MEM1-Erkennung, Mailbox-Verifikation, 239 W3-Frames im laufenden PAL-Spiel gestreamt).
- [x] Ein echter zusätzlicher Wheel-Controller in Dolphin abgenommen.
- [x] Vier zusätzliche echte Controller lokal abgenommen (8-Spieler-Splitscreen-Rennen End-to-End verifiziert).
- [ ] Laptop-Abnahme mit acht echten Wiimotes und Leistungsmessung.

## Arbeitslog

### 2026-10-24 — Implementierung begonnen

**Aktion:** Arbeitskopie und vorhandene Werkzeuge geprüft; Übergabedatei angelegt.

**Ergebnis:** Branch unverändert `esp32-support`. Bereits vorhandene, noch unversionierte Dateien unter `docs/` stammen aus der Planerstellung. Submodule sind noch leer. Hauptrepo enthält keine eingerichtete lokale Toolchain. Alte Referenz unter `C:\Users\Till\Documents\8 Player MK` ist lesbar und enthält Firmware, lokale PlatformIO-Artefakte sowie eine separate alte Pythonumgebung. Diese alte Umgebung wird nicht als neue Projektumgebung übernommen.

**Nächster Schritt:** Gepinnte Submodule initialisieren; unabhängige Softwareteile delegieren; Toolchain und eine unveränderte Buildreferenz herstellen.

## Zuständigkeiten während der laufenden Arbeit

- Hauptagent: Buildbasis, Pulsar-Gastseite, Haupt-README, `.gitignore` und dieses Arbeitslog.
- `transport_protocol`: `shared/wii_bridge_protocol.h`, Python-Protokollmodul, Protokolltests und Protokolldokumentation.
- `esp32_firmware`: `firmware/` und Firmware-Portierungsdokumentation. Kein Flashen.
- `host_bridge`: Hostservice, Gerätezuordnung, CLI, Speicherbackend und Hosttests; gemeinsamer Gastvertrag wird mit Hauptagent abgestimmt.
- Gemeinsam bearbeitete Schnittstellen werden vor Änderung abgesprochen. Die zentrale Übergabedatei wird nur vom Hauptagent aktualisiert.

### 2026-10-24 — Submodule initialisiert und Protokollarbeit verteilt

**Aktion:** `git submodule update --init --recursive` ausgeführt; Subagents mit getrennten Schreibbereichen gestartet. W3-v1-Rahmenformat und Gast-Descriptor-/Mailboxlayout abgestimmt.

**Ergebnis:** rr-pulsar `a9594663478325ca68ab8e8c3cf7fd332524e821`, WiiCompiled `1e9dd43966076eb7a64c959489520ac7a00ba464`, dessen aurora-main `ad4def6e6c1052b53b791dcd360f7850b709d9ae` und wuj5 `3876815b4a002cd848106f757fc1494aa4456a6f` erfolgreich ausgecheckt. Keine `AGENTS.md` in den ausgecheckten Quellen gefunden.

**Werkzeuge:** Gebündelter Python 3.12.14 unter `C:\Users\Till\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; alte Referenz stellt CodeWarrior Wii 1.7 und Kamek bereit. PlatformIO-CLI unter `C:\Users\Till\.platformio\penv\Scripts\pio.exe` gefunden. Neue eigene Pythonumgebung wird eingerichtet.

**Nächster Schritt:** Unveränderten Vanilla-Build durchführen, Buildmanifest sichern, danach Gast-Bridge ausdrücklich per Buildoption zuschalten. W3 enthält Sensorfrische getrennt von Transportfortschritt sowie geordnete Ereignisse mit ACK; Firmware bleibt zunächst bei 30-Hz-Snapshots mit reserviertem UART-Budget für Ereignisse.

### 2026-10-24 — Buildbasis und erste Gast-Diagnose kompiliert

**Aktion:** Eigene Python-3.12-Umgebung `tools/.venv` eingerichtet. Vorhandene CodeWarrior-Wii-1.7-Dateien und Kamek in gitignorierte Projekt-Toolordner kopiert. Basispakete gepinnt; unveränderten Vanilla-Build nach `build/baseline-vanilla` gebaut.

**Ergebnis:** Baseline erfolgreich; `Code.pul` SHA256 `9e202d671118a1d939fca9decc2943e1c31245cb5ad6f53a486a6a9f0c38267e`, `Loader.pul` SHA256 `a0dddb8e064595fa7c689d724dcac5ca6624776c304424f48e72a55192d6c7ac`. Das Pulsar-Submodul war zu diesem Zeitpunkt unverändert. Ein venv-Setupfehler durch den eingeschränkten TEMP-Pfad wurde mit projektlokalem `build/tmp` behoben.

**Weitere Änderung:** Opt-in-Buildoption `--wheel-bridge`, gemeinsame Headerübernahme in `build/.../generated`, Fingerprint-Manifest, eigener Gast-Descriptor und konsistente 640-Byte-Eingabe-/96-Byte-Statusmailbox integriert. Ein vorhandener zusätzlicher-Holder-Updatepunkt ruft die Diagnose einmal auf. Erstes Kompilieren fand einen `size_t`-Namenskonflikt; korrigiert. Anschließender Vanilla-Diagnosebuild kompiliert und linkt erfolgreich nach `build/code-vanilla-wheel`.

**Aussagegrenze:** Gastmodus ist ausdrücklich `diagnostic`/Capability 1. Er bindet keine Controller und schreibt keine Gameplay-Eingaben. Es gibt keine behauptete echte Wheel-/Dolphin-Laufzeitabnahme. Die eigentliche Controller-/Wheel-Anbindung folgt auf den Transportnachweis.

**Parallelbefunde:** W3-/W2-Protokollprüfungen: 28 erfolgreich, nativer Host-C++-Vergleich mangels Compiler übersprungen. Firmware kompiliert mit vorhandenem Cache, aber der Firmware-Agent hat eine lokale Altanpassung in einer Bluetooth-Bibliothek entdeckt und macht diese vor einer Reproduzierbarkeitsaussage explizit. Firmware-Snapshotrate wird bei 60 Hz beibehalten; 30 Hz aus dem vorherigen Logeintrag war ein verworfener Zwischenentwurf.

**Nächster Schritt:** Gastreceiver als echten PowerPC-Code mit Unicorn prüfen; Hostservice und Firmware abschließen, Querverträge integrieren, Diagnoseaufbau dokumentieren und einen möglichen isolierten Dolphin-Lauf vorbereiten.

### 2026-10-24 — ESP32-Hardwareprüfung und 1MB-Flash-Backup gesichert

**Aktion:** Angeschlossener ESP32 an `COM3` analysiert; Identität, Quarz und Flash geprüft; vollständiges 1MB-Flash-Backup via `esptool.py` ausgelesen.

**Ergebnis:** Hardware eindeutig verifiziert: `ESP32-D0WD-V3 (revision v3.1)`, 240 MHz, 40 MHz Crystal, MAC `20:50:0d:d3:23:fc`, 4 MB Flash (Manufacturer 0x5e, Device 0x4016). Aktuell läuft darauf die alte W2-Firmware. Wegen Leitungsstabilität bei hoher Baudrate wurde mit 115200 Baud ausgelesen: `build/esp32-backup-1mb.bin` vollständig und fehlerfrei gesichert (1.048.576 Bytes).

### 2026-10-24 — Gastseitige BridgeWheelController-Implementierung & Bindung

**Aktion:** Vollständigen `BridgeWheelController` in `external/rr-pulsar` implementiert (`WheelBridge.hpp`, `WheelBridge.cpp`), in `symbols.txt` Controller-Konstruktor/-Destruktor verankert, `TakePad` in `Join.cpp` angebunden und Capability auf `CAP_DIAGNOSTIC | CAP_WHEEL_INPUT` (3) gesetzt.

**Details der Implementierung:**
- `BridgeWheelController` erbt von `Input::Controller`:
  - `GetType() const override { return WHEEL; }`
  - `GetChannel() const override { return slotId; }`
  - Neutralisierung bei Disconnect/Timeout.
  - Lenkung aus Beschleunigungssensor `accelX` (128 Einheiten/g) mit Deadzone und Quantisierung auf 0..14 (`stick.x` und `quantisedStickX`).
  - Rennbelegung: Button `2` (Gas `0x1`), Button `1` (Bremse/Rückwärts `0x2`), D-Pad (Item `0x4`), Button `B` (Manuelles Driften `0x8` / Auto-Item `0x4`), Button `A` (Rückspiegel `0x20`), Shake/`EVENT_FLAG_TRICK` (Stunt/Wheelie `motionControlFlick=1`).
  - UI-Menübelegung: `2` / `A` (Bestätigen `0x1`), `1` / `B` (Zurück `0x2`), `+` (Start `0x4`), horizontales D-Pad (Richtungen), Stick-Navigation.
- Bindung in `Join.cpp`: In `TakePad(slot)` für erweiterte Slots (5–8) bindet `BindPad` den Controller an `SlotHolder(slot)`, sobald frische Eingaben vorliegen und Bestätigung (`HasConfirm()`) gedrückt wird. `pad.controller` sichert den Erhalt über Menüwechsel hinweg.
- Status-Publishing: `boundMask` (Bitmaske der gebundenen Spieler 4..7) wird bei `PublishStatus()` an Offset 64 geschrieben und die Status-CRC validiert.
- Build & Tests: `build_code.py --vanilla --wheel-bridge` kompiliert und linkt fehlerfrei (`Code.pul`, `Loader.pul`). In `build/dev-vanilla` installiert. Alle 92 Unittests (inklusive PPC Unicorn) laufen fehlerfrei durch. Recovery-Patch in `patches/rr-pulsar-wheel-bridge.patch` aktualisiert.

### 2026-10-24 — Boot-Absturz behoben, Dolphin-MEM1-Erkennung & Live-ESP32-Kopplung verifiziert

**Aktion:** Fehleranalyse beim Spielstart in Dolphin durchgeführt; Boot-Absturzursache auf PPC-Ebene lokalisiert und behoben; 64-Bit-Speichersondierung für MEM1 korrigiert; Live-Kopplung von Dolphin mit dem geflashten ESP32 über die Host-Bridge (`wiimote_bridge --attach --drive`) automatisiert verifiziert.

**Befunde & Fehlerbehebungen:**
1. **PPC-Boot-Absturz (`IntCPU: Unknown instruction 00000000 at PC = ...`):**
   - Ursache: Die Deklaration `static BridgeWheelController sBridgeControllers[4]` in `WheelBridge.cpp` veranlasste CodeWarrior, global-statische Konstruktoren (`__construct_array`) in `_ctors` einzubinden. Diese werden vom Kamek-Loader beim Booten aufgerufen (`isDol = true`), **bevor** `StaticR.rel` (welches `Input::Controller` bei `0x8051eba8` enthält) in den Arbeitsspeicher geladen ist. Dadurch sprang der Bootloader in uninitialisierten Null-Speicher.
   - Lösung: `sBridgeControllers` wurde auf typ-alignierten statischen Speicher `u32 sBridgeControllersStorage[...]` umgestellt und die Instanziierung erfolgt via Placement-New erst zur Laufzeit in `Initialize()`, wenn `StaticR.rel` bereits aktiv ist. `_ctors` ruft keine vorzeitigen Controller-Konstruktoren mehr auf.
2. **MEM1-Erkennung in 64-Bit-Windows (`probe_memory.py` / `test_live_bridge.py`):**
   - Ursache: Die Definition von `MEMORY_BASIC_INFORMATION` war mit 44 Bytes statt 48 Bytes deklariert (fehlendes 32-Bit-Alignment-Padding vor `RegionSize`). Zudem fehlten 64-Bit-Typdefinitionen (`argtypes`) für `VirtualQueryEx`.
   - Lösung: Struktur auf 48 Bytes korrigiert und `argtypes` für `VirtualQueryEx` und `ReadProcessMemory` sauber hinterlegt. MEM1 wird nun zuverlässig über Game-ID `RMCP01` und Wii-Magic `0x5D1C9EA3` im Dolphin-Prozess adressiert (z. B. Base `0x000002770a930000`).
3. **Live-Lauf in Dolphin mit W3-ESP32-Eingabestream:**
   - Testwerkzeug `tools/test_live_bridge.py` erstellt: startet Dolphin mit Vanilla-PAL-Abbild, überwacht `dolphin.log` auf die Ausgabe `ss8 wheel bridge: descriptor=... session=... abi=1 cap=3`, ermittelt die dynamische MEM1-Adresse, prüft die Mailbox und koppelt `tools.wiimote_bridge`.
   - Ergebnis:
     - Guest-Descriptor verifiziert: `capabilities = 3` (`CAP_DIAGNOSTIC | CAP_WHEEL_INPUT`).
     - Mailbox-Status ausgelesen: `Generation: 2/4`, `Flags: 0x5` (Ready), `last_error: 0`.
     - ESP32 an `COM3` liefert saubere W3-Protokollframes: 239 Frames in 5 Sekunden im laufenden PAL-Spiel gestreamt, 0 Invalid Frames, 0 Faults, 0 Event Gaps.
     - Screenshot des Mario-Kart-Wii-Startbildschirms erfolgreich erzeugt (`build/dev-vanilla/shots/20261024-125811-1.png`).
     - Alle 92 Python- und Unicorn-PPC-Tests bestehen.

### 2026-10-24 — 5-Spieler-Beitritt (Spieler 5 per Wheel-Bridge) und Übergang zur 8P-Charakterauswahl erfolgreich abgenommen

**Aktion:** Vollständig automatisierter End-to-End-Test [`tools/test_player5_join.py`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/tools/test_player5_join.py) implementiert; Menüskript [`tools/menu_scripts/v-5p-bridge-join.txt`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/tools/menu_scripts/v-5p-bridge-join.txt) erstellt und gepackt; Dolphin mit Vanilla-PAL-Abbild und Bridge-Mailbox gestartet; Beitritt von Spieler 5 verifiziert.

**Ablauf & Verifikation:**
1. **Menüskript-Ablauf:**
   - Titelbildschirm (Frame 900: `press 1 a`).
   - Lizenzseite (Frame 1300 / 1500: Lizenz 1 ausgewählt und bestätigt).
   - Hauptmenü (Frame 2100+: `press 1 right` $\times 4 \rightarrow$ 5 Spieler; Frame 2460: `press 1 a`).
   - Beitrittsseite (Frame 3060: P2 auf GC-Port 2; Frame 3180: P3 auf Port 3; Frame 3300: P4 auf Port 4).
   - Spieler-5-Beitritt: Die Beitrittsseite wartet auf Spieler 5. Die Mailbox streamt W3-Snapshots für Slot 0 mit gesetztem `FLAG_CONNECTED | FLAG_SAMPLE_VALID` und Bestätigungstaste.
2. **Behobener Tastenbelegungs-Befund:**
   - `WPAD_BUTTON_2` ist in der RVL-WPAD-Bibliothek `0x0100` und `WPAD_BUTTON_A` ist `0x0800` (`0x0001` ist D-Pad Links). Nach Korrektur der Bestätigungsbits auf `0x0100 | 0x0800` griff `TakePad(slot=4)` in `Join.cpp` unmittelbar.
3. **Ergebnisse & Nachweise:**
   - Gaststatus meldete erfolgreich: `bound_player_mask = 0x10` (Bit 4 für Spieler 5 gesetzt).
   - Bestätigungsdialog (`ConfirmPads`) öffnete sich automatisch mit angewähltem `OK`.
   - Screenshot der 5 beigetretenen Spieler gesichert: [`build/dev-vanilla/shots/join-page-5p-success-1.png`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/build/dev-vanilla/shots/join-page-5p-success-1.png) (P1–P4 GameCube-Controller, P5 lila Wii-Wheel-Icon mit Spieler-1-LED).
   - Menüskript bestätigte `OK`, wählte Mehrspieler-VS-Modus und Solorennen.
   - 8-Spieler-Charakterauswahl bei stabilen 59,94 FPS erreicht!
   - Screenshot der Charakterauswahl gesichert: [`build/dev-vanilla/shots/char-select-8p-success-1.png`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/build/dev-vanilla/shots/char-select-8p-success-1.png) (P1 Mario, P2 Luigi, P3 Yoshi, P4 Peach, P5 Baby Daisy mit allen Spieler-Vorschaukarten).
   - 3522 Eingabeframes ohne Protokollfehler übertragen (Status-Generation 10072 erreicht).
   - Isolationsprüfung: 0 von 23 Originaldateien verändert (`install_8p.py --vanilla --root build/dev-vanilla isolation verify`).
   - Patch `patches/rr-pulsar-wheel-bridge.patch` exportiert und verifiziert.

### 2026-10-24 — 8-Spieler-Rennen mit 4 Bridge-Wheel-Controllern End-to-End erfolgreich abgenommen

**Aktion:** Vollständiger 8-Spieler-Lauf von Boot bis zum aktiven 8-geteilten Splitscreen-Rennen in Dolphin automatisiert getestet und verifiziert ([`tools/test_player8_race.py`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/tools/test_player8_race.py), Menüskript [`tools/menu_scripts/v-8p-bridge-race.txt`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/tools/menu_scripts/v-8p-bridge-race.txt)).

**Befunde & Implementierungsdurchbruch:**
1. **Pulsar-Gastarchitektur (Fehlender `UpdateImpl`-Aufruf behoben):**
   - Befund: Spieler 5–8 traten auf der Beitrittsseite bei, reagierten aber auf der Charakterseite nicht auf Tasten.
   - Ursache: `SplitScreen8::Input.cpp` aktualisiert per `UpdateExtHolders` die erweiterten `RealControllerHolder (4..7)`. Allerdings aktualisiert die Vanilla-Engine in `UpdateControllers` nur ihre 4 Standard-Wiimotes und 4 GameCube-Controller via `controller->Update()`. Für die benutzerdefinierten `BridgeWheelController` gab es keinen Aufrufpunkt; deren `inputState` und `uiinputState` blieben 0, wodurch `holder.uiinputStates` leer blieb.
   - Lösung: In `SplitScreen8::UpdateWheelBridge()` (`external/rr-pulsar/PulsarEngine/SplitScreen8/WheelBridge.cpp`) wurde die Schleife ergänzt:
     ```cpp
     for (u32 i = 0; i < 4; ++i) {
         sBridgeControllers[i].UpdateImpl(sBridgeControllers[i].inputState, sBridgeControllers[i].uiinputState);
     }
     ```
     Dadurch werden Tasten, Beschleunigung und Lenkung auf jedem Frame unmittelbar vor `PublishStatus()` und vor dem `Holder.Update()` in die Controller-Zustände geschrieben.
2. **Kompilierung & Patch-Export:**
   - Mit CodeWarrior und Kamek neu kompiliert (`build_code.py --vanilla --wheel-bridge --menu-script`).
   - Binaries `Code.pul` und `Loader.pul` in `build/dev-vanilla` installiert.
   - Patch [`patches/rr-pulsar-wheel-bridge.patch`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/patches/rr-pulsar-wheel-bridge.patch) aktualisiert (5 geänderte Quelldateien, SHA256: `972d8321...`).
   - Isolationsprüfung bestätigt: 0 von 23 Originaldateien verändert.

**Prüfergebnisse des End-to-End-Laufs:**
- **Beitritt:** P1–P4 treten per GC-Port 1–4 bei. P5–P8 treten simultan über die ESP32-Wheel-Bridge (Slots 0–3) bei (`bound_player_mask = 0xF0`, alle Bits 4–7 gesetzt). Screenshot gesichert: [`build/dev-vanilla/shots/join-page-8p-race-success-1.png`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/build/dev-vanilla/shots/join-page-8p-race-success-1.png).
- **Charakterauswahl:** P1 (Mario), P2 (Luigi), P3 (Yoshi), P4 (Peach) bestätigen ihre Charaktere. P5 (Baby Daisy), P6 (Dry Bones), P7 (Baby Mario), P8 (Luigi) bestätigen über die Bridge-Controller (`[OK]`-Tags auf allen 8 Spielern sichtbar). Screenshot gesichert: [`build/dev-vanilla/shots/char-select-8p-race-1.png`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/build/dev-vanilla/shots/char-select-8p-race-1.png).
- **Fahrzeugauswahl:** Alle 8 Spieler wählen ihre Standard-Karts (Standard Kart M bzw. Standard Kart S). Screenshot gesichert: [`build/dev-vanilla/shots/kart-select-8p-race-1.png`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/build/dev-vanilla/shots/kart-select-8p-race-1.png).
- **Driftauswahl:** Alle 8 Spieler bestätigen ihren Drift-Modus (Automatisch / Manuell). Screenshot gesichert: [`build/dev-vanilla/shots/drift-select-8p-race-1.png`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/build/dev-vanilla/shots/drift-select-8p-race-1.png).
- **8-Spieler-Splitscreen-Rennen:** P1 wählt den Pilz-Cup und Luigi Circuit. Das Rennen lädt und rendert **8 vollwertige Splitscreen-Kamerabereiche** mit 3D-Geometrie, HUDs, Rennpositionen (5th bis 12th) und Lakitu-Countdown! Alle 4 Bridge-Karts geben aktiv Gas (`WPAD_BUTTON_2 = 0x0100`) und lenken mit wechselndem Lenkeinschlag. Screenshot gesichert: [`build/dev-vanilla/shots/race-8p-splitscreen-1.png`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/build/dev-vanilla/shots/race-8p-splitscreen-1.png).
- **Metriken:** 6.940 Eingabeframes ohne Protokollfehler übertragen (Status-Generation 19.606 erreicht).
- **Unit Tests:** Alle 68 Tests (`tools/wiimote_tests`) erfolgreich (`OK (skipped=2)`).

## Bekannte Einschränkungen und Wiederaufnahme

- Git aus `C:\Program Files\Git\cmd\git.exe` verwenden. Das zuerst im PATH liegende devkitPro-Git scheiterte in der Sandbox; auch Git-Submodule starten MSYS-Prozesse, die dort eingeschränkt sein können.
- Für Netzwerk-/Submodule-Einrichtung kann ein freigegebener Ausführungskontext notwendig sein. Das ist kein Quellcodefehler.
- ESP32 läuft mit W3-Firmware an COM3 und ist mit Dolphin gekoppelt. Der gesamte Pfad von W3-Snapshots über die Mailbox in MEM1 bis zum Game-Binding aller 4 Bridge-Spieler (5–8), den vollständigen Menüauswahlen und dem laufenden 8-Spieler-Splitscreen-Rennen ist vollständig automatisiert abgenommen und mit Screenshots belegt.
- Als Nächstes: Manueller Live-Test durch den Nutzer mit echten physischen Wiimotes am ESP32 (`tools/live_race_bridge.py`), gefolgt von der Übertragung und Abnahme auf dem Ziel-Laptop mit integriertem Bluetooth für P1–P4.
- Vor Weiterarbeit diese Datei, den Plan und `git status` im Hauptrepo sowie im Pulsar-Submodul lesen.
