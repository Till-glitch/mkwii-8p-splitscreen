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
- [x] Geordnete Gameplay-Ereignisse im Gastreceiver implementiert; 41 tatsächliche PPC-Prüfungen inklusive Diagnosemodus erfolgreich.
- [x] Akzeptierte native PAL-Wheel-/Item-Funktionen portiert und unabhängig geprüft; echte Geräteabnahme bleibt offen.
- [x] Referenzfirmware kontrolliert portiert, gebaut und auf ESP32 an COM3 geflasht (1MB-Backup gesichert).
- [x] Gastseitiger Bridge-Eingabepfad integriert und gebaut (BridgeWheelController, CAP_WHEEL_INPUT=3, TakePad-Bindung).
- [x] Live-Kopplung Dolphin + Host-Bridge + ESP32 verifiziert (MEM1-Erkennung, Mailbox-Verifikation, 239 W3-Frames im laufenden PAL-Spiel gestreamt).
- [x] Synthetisch gespeiste Bridge-Plätze P5–P8 durch Anmeldung und Auswahl bis zur Darstellung eines Achtspieler-Rennens geführt; Screenshot zeigt den Countdown.
- [ ] Ein echter zusätzlicher Wheel-Controller hinsichtlich Fahrgefühl, gewünschter Tastenbelegung, Items und Stunts abgenommen.
- [ ] Vier zusätzliche echte Controller gemeinsam lokal abgenommen; die bisherigen automatisierten Menüs-/Rennaufbautests verwenden synthetische Snapshots.
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
- Laut übernommenem Hardwareprotokoll wurde der ESP32 auf W3 geflasht und ein serieller Lauf mit Dolphin durchgeführt. Die vier zusätzlichen Spielplätze wurden in den automatisierten Beitritts-/Rennaufbautests direkt mit synthetischen `HostView`-Snapshots gespeist. Das ist ein Integrationsnachweis für Mailbox, Binding und Darstellung, keine Abnahme von vier echten physischen Wheels. Das 1-MB-Backup ist nur ein Teilabbild des festgestellten 4-MB-Flashs.
- Vor einem manuellen Fahrtest sind native Wheel-Filter, gewünschte B-/1-Belegung und die tatsächliche Nutzung sequenzierter Ereignisse fertigzustellen. Danach `tools/run_live_bridge.py` mit expliziter Konfiguration verwenden. Die zuvor genannte Datei `tools/live_race_bridge.py` existiert nicht.
- Vor Weiterarbeit diese Datei, den Plan und `git status` im Hauptrepo sowie im Pulsar-Submodul lesen.

### 2026-10-24 — Bericht des weiteren Agents übernommen und Nachweisgrenzen berichtigt

**Aktion:** Nutzerbericht, Commit, Arbeitskopie, Gastcode und vorhandene Screenshots abgeglichen. Parallele eigene Schreibaufgaben vorübergehend angehalten, um die weiterentwickelten Quellen zu erhalten.

**Ergebnis:** Hauptrepo steht auf lokalem Commit `b6b5d7b` und liegt einen Commit vor `origin/esp32-support`. Der Pulsar-Gitlink bleibt `a959466…`; seine tatsächlichen Änderungen liegen uncommittet im Submodul und zusätzlich im exportierten Patch. Laut übergebenem Bericht wurde der Push mit HTTP 403 abgewiesen. Es wurden hier keine Anmeldedaten geändert und kein erneuter Push versucht.

**Bestätigte Befunde:** `BridgeWheelController`, Placement-New-Initialisierung, Update vor den erweiterten Holdern, Join-Anbindung und automatisierte Menüskripte sind vorhanden. Die Screenshots belegen acht gebundene Plätze und acht Rennansichten im Countdown. `tools/test_player8_race.py` erzeugt die vier Bridge-Slots selbst mit `HostView(..., events=())`; dies prüft keine physische Funkstrecke. Eine Momentaufnahme des Rennaufbaus zeigt ungefähr 34 FPS und ist weder ein 60-FPS-Nachweis noch eine Messung der Echtzeit-Spielgeschwindigkeit.

**Offene Implementierungsdefekte gegenüber dem Auftrag:** Lenkung verwendet bislang eine frei gewählte Deadzone und lineares `accelX / 100` mit Rundung statt der akzeptierten nativen Filter. B löst bei manueller Drift derzeit Drift statt Itemhalten aus. Sequenzierte Ereignisse werden zwar quittiert, aber vom Controller nicht als geordnete Aktionen verarbeitet; der Stuntpfad liest lediglich das diagnostische Snapshotflag. Die Checkboxen für echte Wheel-Abnahmen wurden entsprechend zurückgesetzt. Historische Logeinträge weiter oben geben den damaligen Bericht wieder und sind durch diesen Befund zu interpretieren.

**Nächste Arbeiten / Schreibbereiche:** Firmware-Agent portiert ausschließlich `WheelNative.hpp/.cpp` und neue native Symbol-Aliases; Host-Agent entwirft die ABI-erhaltende Gameplay-Ereignisverarbeitung; Protokoll-Agent prüft Startwerkzeuge und Nachweisaussagen zunächst lesend. Hauptagent integriert die Controlleranbindung und pflegt dieses Log. Keine neue Firmwareänderung oder erneutes Flashen für diese Softwarearbeiten.

### 2026-10-24 — Native Wheel-/Item-Parität und geordnete Gameplay-Ereignisse integriert

**Aktion:** Die lineare Ersatzlenkung durch `WheelNative.hpp/.cpp` ersetzt. Der Bridge-Controller verwendet private KPAD-/Wheel-Zustände und die originalen PAL-Filter, native Operationsreihenfolge und `fctiwz`-Quantisierung. Derselbe Aktionshelfer setzt B=Itemhalten, 1 bei gehaltenem 2=Hüpfen/Drift und A=Rückblick für Bridge- und native Wheels um. Der native Viererpfad wird erst nach seiner eigenen Sensorverarbeitung am anhand des Originalcodes geprüften PAL-Callsite `0x8051FE4C` angepasst; originale X-Lenkung und Flickzustände bleiben dabei erhalten.

**Ereignisvertrag:** `Receiver.SetGameplayMode(true)` hält geordnete Ereignisse über Publishes und Ticks. `ConsumeActions()` liefert pro Slot höchstens einen Buttonwechsel und einen Stuntimpuls je Tick. Quittiert wird erst nach Verarbeitung bzw. einer definierten neutralen Verwerfungsgrenze. Das diagnostische Snapshot-Stuntflag wird nicht als Spieleingabe verwendet. Der Controller cacht seine Ausgabe pro Tick und setzt private Zustände bei Timeout, Sitzung, Initialisierung oder Szenenwechsel zurück. Frische Gameplay-Sensoren müssen zusätzlich als kalibriert markiert sein.

**Prüfergebnisse:** 41 Tests des echten CodeWarrior-PPC-Gastreceivers bestanden. Neun dauerhafte Tests des nativen Ports bestanden: darunter 50 Quantisierungsfälle, 2.624 Zustandsvergleiche gegen getrennte originale PAL-Filter, 504 Item-Ausgaben und drei tatsächliche PPC-Prüfungen der logischen Controlleridentitäten. Originalressourcen werden ausschließlich lokal über `MKW_PAL_RESOURCE_ROOT` gelesen. Emulatorgrenzen: PSQ-Spills werden übersprungen, Sin/Cos-Tabellenzugriffe gleichartig als float32-Interpolation ausgeführt. Kein Funk-, Render- oder Haptiknachweis durch diese Tests.

**Gesamtbuild:** `tools/.venv/Scripts/python.exe tools/build_code.py --vanilla --wheel-bridge --menu-script -j 4` kompiliert und linkt erfolgreich. Der anschließende erste gesamte Testlauf meldete eine Windows-Dateifreigabesperre beim Entfernen einer temporären Patch-Testdatei, keine fachliche Assertion. Die Testbereinigung wiederholt jetzt ausschließlich Win32-Sharing-Verletzungen kurz und begrenzt; Nachprüfung läuft.

### 2026-10-24 — Native/Bridge-Geräteidentität und Lautsprecherrouting getrennt

**Befund aus Originalcode:** Native `ControllerParams::Fill` ruft für WHEEL mit Channel 0–3 `WPADProbe` und `GetDevAddr` auf. Der Prototyp hätte dadurch die MAC-Adresse einer tatsächlichen P1–P4-Wiimote in P5–P8 übernommen. Native `calculateID` erzeugt für beide Gruppen identische Werte `0x111/0x211/0x311/0x411`. Außerdem wurde derselbe ID-Zugang in UI und Wii-Speaker-Routing verwendet.

**Änderung:** Exakt erkannte Bridge-Objekte erhalten explizite 16-Byte-Parameter mit eigenen lokal administrierten logischen Proxy-Adressen, ohne native WPAD-Abfragen. Ihre internen Join-IDs sind `0x53530001` bis `0x53530004`; nur an den UI-Ausgabepfaden werden diese in native Darstellungs-IDs übersetzt. Bridge-Speaker-Routing liefert 0 statt eines fremden nativen Kanals. Physische MAC→Spieler-Reservierungen bleiben beim Host. Kein Kanal 4–7 wird erfunden.

**Aussagegrenze:** Diese konkret belegten Pfade sind korrigiert. Die kombinierte Nutzung mit vier echten nativen Laptop-Wiimotes, Pause und Wiederverbinden bleibt praktisch abzunehmen. Start-/Testwerkzeuge werden gerade auf getrennte Prozessbesitzrechte, passende Buildmanifeste und belastbare Rennzustandskriterien umgestellt.

### 2026-10-24 — Integrierte Achtspieler-Regression, Lifecycle-Fixes und sichere Starter bestanden

**Änderungen:** Die fünf Start-/Testwerkzeuge verwenden jetzt den gemeinsamen profilgebundenen `runner.py`: Sperre vor Profiländerungen, explizites passendes Buildmanifest, Prüfung von EXE/PID/Startzeit und aktueller Logsession, validierte RAM-Aliases sowie Cleanup ausschließlich des eigenen Popen-Prozesshandles. Feste lokale EXE-/COM3-Annahmen und Start aus fremdem Arbeitsverzeichnis sind beseitigt. 24 gezielte Runner-Prüfungen bestanden. Race-Smokes dürfen nicht mehr allein aufgrund der Beitrittsmaske oder eines großen Tickzählers Erfolg melden.

**Weitere ABI-Korrekturen:** Native Aktions-Latches werden beim echten Motion-Init-Callsite `0x8051F2E8` zurückgesetzt. `ResetSelf` entspricht dagegen StopRumble und löst keinen Filterreset aus. Der exklusive Core-Postfilter-Hook prüft keine noch veraltete Controllerart des ersten Extensionwechselticks. Frische Bridge-UI-Eingaben setzen nun wie das Original das Gültigkeitsbit an `UIState+0x30`; neutrale Eingaben löschen es.

**Gesamte Softwareprüfung:** Mit Projekt-Python 3.12, Unicorn und lokal angegebenem PAL-Ressourcenordner laufen **142 Tests erfolgreich, eine optionale native g++/clang++-Parity-Klasse übersprungen**. Die tatsächlichen CodeWarrior-PPC-Receiver-, Wheel- und Identitätsprüfungen wurden ausgeführt. Der Windows-Temporärdatei-Test besteht nach der begrenzten Sharing-Violation-Bereinigung ebenfalls.

**Dolphin-Ergebnis:** Der integrierte Menübuild wurde im isolierten Profil mit synthetischen kalibrierten Sensoren und geordneten Buttonereignissen ausgeführt. Acht gebundene lokale Plätze und die VS-Rennszene mit anschließendem Gastfortschritt sind bestätigt: `bound_player_mask = 0xF0`, `guest_tick = 9673`, `accepted_count = 5896`, `rejected_count = 0`, `last_error = 0`. Alle vier Ereignis-ACKs stehen bei 331. Drei RAM-Aliases wurden gegen denselben aktuellen Descriptor verifiziert. JSON-Bericht: `build/dev-vanilla/synthetic-race-report.json`; Bilder: `build/dev-vanilla/shots/synthetic-race-observation-*.png`. Der Bericht markiert physische Wheels, Fahrbewegung und FPS ausdrücklich nicht als automatisch verifiziert. Der eigene Dolphin-Prozess und die Profilsperre wurden anschließend entfernt; andere Dolphin-Prozesse wurden nicht beendet.

**Build-Fingerprints:** Nach einer ausschließlich deaktivierten Präprozessorpfad-Bereinigung wurde der Menübuild erneut gebaut. Vergleich zum gerade getesteten PPC-Binary: gleiche Länge und identisches Linklayout; exakt die 16 Build-ID-Bytes änderten sich. Neuer Menü-Build-ID: `1fefc90d89954eb6c9399fac019401da`. Der zugehörige JSON-Laufbericht enthält noch den davor geprüften Fingerprint `9fa72e2503ce8cb0952f18fe94d85ae7`. Die unveränderte Funktionalität ist durch diesen Binärvergleich eingegrenzt. Auch der Build ohne Bridge kompiliert; er ist nicht byteidentisch zum eingefrorenen Ausgangsbuild, weshalb hier kein Bytegleichheitsnachweis behauptet wird.

**Serieller Smoke ohne Gameplay:** Ein eindeutig als CP210x erkannter ESP32 wurde fünf Sekunden im Diagnosemodus gelesen: letzte Zusammenfassung 179 gültige Frames, 0 ungültige Frames, 0 Ereignislücken, 0 Queueüberläufe, keine frischen zugeordneten Spieler. 472 Nichtframe-/Bootbytes wurden beim Resynchronisieren verworfen. Das bestätigt den W3-Transport, keine physische Wheel-Fahrt. Log: `build/dev-vanilla/serial-diagnose.log`. Kein erneutes Flashen.

**Wiederaufnahme:** [START-8-WIIMOTES.md](START-8-WIIMOTES.md) beschreibt Build, manuelle normale Variante, explizite Gerätezuordnung und getrennte synthetische Regression. Als Nächstes echte P5–P8-Fahr-/Item-/Stunt-/Pause-/Reconnect-Abnahme durchführen; danach den Ziel-Laptop mit nativen P1–P4 und Leistungs-/Zeitmessung prüfen. Automatischer serieller Port-Reconnect, Rumble/Lautsprecher und zusätzliche Regionen/Retro Rewind bleiben offen. Es wurde kein weiterer Commit/Push oder Credential-Eingriff vorgenommen.

### 2026-10-24 — Manuellen Build und aktualisierten Wiederaufnahmepatch gesichert

**Aktion / Ergebnis:** Normalen Bridge-Build ohne Menüskript kompiliert und in das eigene Profil `build/dev-vanilla` installiert. Build-ID `3ea844c222b0c1bfba28466251e055b3`, `Code.pul` SHA256 `5f1df86d087d17908781a9b8acda08a2046c9e1c08d4016652f4df131eef5047`. Das Profil ist beendet und frei; der synthetische Bericht und die Screenshots bleiben als Nachweise erhalten. Für einen manuellen Lauf das Manifest unter `build/code-vanilla-wheel/` auswählen; für eine neue synthetische Regression erst den Menübuild wieder installieren und das Skript packen, wie in der Startanleitung beschrieben.

**Pulsar-Sicherung:** Acht Quelldateien gegen Basis `a9594663478325ca68ab8e8c3cf7fd332524e821` exportiert und mit `export_pulsar_patch.py --check` bestätigt. Patch-SHA256 `9704bba39258ec75c485e9ee3b1b9e4da6f7ce602e2ba8fce7ca85ede5a8f798`. Die Änderungen bleiben als Arbeitskopie plus Patch vorhanden; der Hauptrepo-Gitlink wurde nicht auf einen unveröffentlichten Commit umgestellt.

**Abschließende Isolation:** 0 von 23 überwachten Originaldateien verändert. Der Whitespacecheck für Unified-Diff-Artefakte wird über `*.patch -whitespace` ausdrücklich ausgenommen, weil leere Kontextzeilen dort zwingend das einzelne Präfix-Leerzeichen tragen. Die eigentlichen Quelltexte behalten ihre normale Whitespaceprüfung.

### 2026-10-25 — Vorbereitung des manuellen Hardwaretests

**Aktion / Ergebnis:** Auf Nutzerwunsch den vorhandenen normalen Build und die Startanleitung geprüft. Der Build unter `build/code-vanilla-wheel/Code.pul` hat weiterhin SHA256 `5f1df86d087d17908781a9b8acda08a2046c9e1c08d4016652f4df131eef5047`. USB-UART wird eindeutig als CP210x auf COM3 erkannt. Ein fünfsekündiger lesender W3-Diagnoselauf außerhalb der eingeschränkten Sandbox meldet zuletzt 177 gültige Frames, zwei ungültige Frames und 1.144 verworfene Boot-/Diagnosebytes. Alle vier Slots sind getrennt; noch keine Geräteadresse und keine Hostzuordnung (`build/wiimote-bridge/config.json` fehlt). Kein erneutes Flashen und kein Dolphin-Start. Nächster Schritt erfordert physische Kopplung durch den Nutzer, anschließend MAC-Adressen ausdrücklich P5–P8 zuordnen. Das isolierte Profil enthält emulierte Wiimotes für die lokale Menübedienung; native Laptop-Wiimotes sind weiterhin ein späterer Test.

**Fortsetzung:** Nutzer meldet zwei gekoppelte Fernbedienungen mit LED 1 bzw. 2. Erneutes Auslesen kann COM3 nicht öffnen. Prozessprüfung erklärt den Zugriff: Ein vom Nutzer bereits gestarteter `run_live_bridge.py`-Lauf hält über seinen seriellen Kindprozess COM3 offen und verwendet Dolphin PID 21716 im isolierten Profil. Hostkonfiguration fehlt weiterhin. Kein zweiter Dolphin gestartet und keine bestehenden Prozesse beendet. Zur Adresserkennung zunächst diesen Live-Lauf im zugehörigen Terminal mit Strg+C beenden; danach Diagnose, ausdrückliche P5/P6-Zuordnung und Neustart. Die LEDs allein beweisen weder Kalibrierung noch Hostzuordnung.

### 2026-10-25 — Zwei physische Wiimotes erkannt und manuellen Lauf gestartet

**Aktion:** Nach bestätigtem Nutzerstopp seriell diagnostiziert. ESP32 meldet die reservierten Adressen `00:24:1E:AB:7B:CB` in Slot 0 und `00:1F:C5:07:D7:BA` in Slot 1. Explizite P5-/P6-Zuordnung mit dem CLI unter `build/wiimote-bridge/config.json` gespeichert. Normalen manuellen Build über `run_live_bridge.py` mit explizitem Manifest, Dolphin-EXE und COM3 gestartet. Eigener Dolphin PID 21528; Tool-Exec-Session 3084. Lauf bleibt für die Nutzerbedienung offen; Schließen dieses Dolphin beendet den zugehörigen Runner/seriellen Kindprozess. Ein anderer Dolphin wurde nicht beendet.

**Ergebnis:** Nach dem seriellen Neustart verbinden sich beide Geräte wieder und liefern frische kalibrierte Sensordaten (`players_fresh=[5,6]`, Flags 7). Zum beobachteten Stand 852 gültige Frames, 0 ungültige Frames, 0 Ereignislücken, 0 Queueüberläufe; Sensorfolgen steigen auf beiden Slots, Buttonänderung auf Slot 1 sichtbar. Retransmits werden als Duplikate erkannt. Dies belegt zwei physische Funk-/Sensoreingänge und ihre Hostzuordnung, noch keine manuelle Fahr-/Stuntabnahme. Laufendes Log: `build/dev-vanilla/manual-live-2026-10-25.log`. Nutzerkonfiguration im isolierten Dolphin wurde erhalten; sie enthält inzwischen auch GameCube-Adapter-Portkonfigurationen. Keine globalen Eingabeeinstellungen überschrieben.

**Manueller Beitrittsbefund:** Nutzerbild zeigt sechs Felder mit ausschließlich angemeldetem P1. `JoinPage::AfterControlUpdate` fordert absichtlich jeweils den ersten noch unbesetzten Platz an; deshalb werden P5/P6 erst nach P2–P4 angefordert. Zur lokalen Bedienung sind im aktuellen isolierten Wiimote-Profil V/B/N jeweils A und 2 für P2/P3/P4 zugeordnet. Nutzer auf diese Reihenfolge hingewiesen. Der erste von uns gestartete Lauf ist inzwischen beendet (letzter Fehler Win32 299); ein vom Nutzer neu gestarteter Lauf verwendet PID 17308 und einen anderen MEM1-Basiswert. Diesen nur lesend gegen EXE und Manifest geprüft: Gasttick 4597, 2773 akzeptierte Publishes, 0 verworfene, Fehler 0, Bound-Maske 0. Zum Lesezeitpunkt ist Sensorfolge für Bridge-Slot 1 aktiv, Slot 0 noch 0; beide physisch frischen Geräte des vorherigen Laufs sind deshalb keine Zusicherung für den neuen Lauf. Kein weiterer Prozessstart oder Quellcodefix in diesem Schritt.

**Nach P1–P4-Anmeldung:** Nutzer meldet Suche nach GameCube-Ports. Quellcodeprüfung: `TakePad` versucht zuerst den bestehenden nativen Auswahlpfad, besitzt danach aber ausdrücklich die Bridge-Abfrage (`IsFresh` + `HasConfirm`); GameCube-Hardware ist für P5/P6 nicht Voraussetzung. Erneuter Live-Lesezustand: 8860 Publishes akzeptiert, 0 verworfen, Gastfehler 0, Bridge-Boundmaske 0. Mailbox-Slot 0/P5 ist vollständig neutral (Flags 0, Sensorfolge 0); Slot 1/P6 ist kalibriert/frisch (Flags 7, Sensorfolge 22828, Ereignis-ACK 107). Damit ist im aktuellen Lauf nur P6 als gültiger physischer Eingang angekommen; die sequenzielle Registrierung wartet noch auf P5. Nutzer soll die erste Wiimote erneut verbinden, während die laufende serielle Verbindung offen bleibt. Keine Portkonfiguration geändert und kein laufender Test beendet.

### 2026-10-25 — Physischer Beitritt bestätigt, fehlende Stuntanimation gemeldet

**Nutzerbefund:** Nach Wiederverbindung funktioniert der Test mit echten P5/P6. Bei Stunts entsteht ein Boost, die sichtbare Figurenanimation fehlt jedoch meistens, nach Präzisierung vor allem bei kleinen Sprüngen. Dies bestätigt den praktischen Beitritt und die Stuntannahme laut Nutzer; keine vollständige Fahr-/Item-/Leistungsabnahme daraus ableiten.

**Untersuchung läuft:** Getrennte Read-only-Audits der nativen Eingabepufferung und Figurenanimation gestartet. Native Stuntimpulse sind ebenfalls kurz; `Trick::UpdateNext` puffert den Flick für 14 Ticks. Kein begründeter Anlass, Bridge-Impulse künstlich zu verlängern. Konkreter Animationsbefund: Driver-Setup ruft an PAL `0x807CB2D8` die Distanzfunktion `0x80787D18`, die nur vier Kameraabstände berücksichtigt. Daraus entsteht das Far-Feld `DriverController+0xB4`; der Stuntcallback `0x807D18EC` verwirft bei gesetztem Feld die Animationsanforderung. Zusätzliche Clip-Schattenabstände für P5–P8 sind bereits vorhanden, werden von dieser Funktion bislang aber nicht verwendet. Gezielt begrenzte Korrektur und echte PPC-Regressionsprüfungen in Arbeit. Laufenden Nutzertest weder beendet noch verändert.

### 2026-10-25 — Stuntanimation: Abstand zu zusätzlichen Kameras korrigiert

**Implementiert:** `Culling.cpp` ersetzt die originale Clip-Minimaldistanzfunktion durch denselben Vierer-Vergleich plus die aktiven Schattenkameraabstände P5–P8. Dadurch bewertet der originale Driver-Callback eine in der eigenen zusätzlichen Kamera nahe Figur nicht mehr allein wegen der entfernten Kameras P1–P4 als zu weit entfernt. Kein erzwungenes Detaillevel, kein pauschales Abschalten der Distanzgrenze und keine Änderung an Stuntimpulsen, Flugdauer, Cooldown oder Boost. Die normale Vierkamera-Reihenfolge und NaN-/Inf-/Nullwertbehandlung bleiben erhalten. Ein erster Vergleichsentwurf mit `!(minimum <= candidate)` wurde vor Installation durch die tatsächlichen PPC-Tests als falsch verworfen; die endgültige native Semantik ist `minimum > candidate` (bei ungeordnetem Vergleich bisherigen Wert behalten).

**Prüfung:** Acht zusätzliche echte CodeWarrior/Unicorn-PPC-Prüfungen in `test_clip_distance_ppc.py` samt Produktions-Harness `clip_distance_harness.cpp`. Darunter 207 Vektoren gegen die unabhängig geladene originale Vierkamera-Funktion, Grenzen für aktive Zusatzkameras sowie die echte Driver-Entfernungsentscheidung `0x807CB2D4..0x807CB2F4` und anschließend der originale Stuntcallback: alter Pfad verwirft die Animation, korrigierter Pfad erreicht die Animationsplanung. Vollsuite mit lokalem PAL-Ressourcenordner: **150 Tests erfolgreich, eine optionale native Compilerklasse übersprungen**. Normaler manueller Build kompiliert/linkt erfolgreich.

**Gesichert und installiert:** Build-ID `9f800f7401161d3c29703371bd853877`, Code-SHA256 `224aa0da6159cd028f049376e8d8324156f81f27cf80191296cee144d28775ea`. Neun Pulsar-Quelldateien im aktualisierten Patch gegen `a959466…`, geprüft mit `--check`; Patch-SHA256 `74545aaeb295ad3177fb5014de43f5082c98d08dba4925c5b285205ffc67b75d`. Nach ausdrücklicher Nutzerfreigabe den bisherigen isolierten Dolphin PID 17308 anhand EXE/Startzeit geprüft und beendet, dessen Runner/serieller Kindprozess beendet sich ebenfalls. Globaler Dolphin PID 11824 bleibt erhalten. Korrigierten normalen Build in `build/dev-vanilla` installiert und Live-Lauf mit denselben P5/P6-Reservierungen neu gestartet (Tool-Session 56781). Neues Log `build/dev-vanilla/manual-stunt-fix-2026-10-25.log`.

**Noch offen:** Sichtbare Bestätigung durch den Nutzer an Rampen, während P1–P4 zurückbleiben, danach kleine Sprünge vergleichen. Kurze Flugzeiten können auch beim nativen Verhalten die sichtbare Animationsdauer begrenzen. Kein automatischer Render-/Hardwarebeweis durch die PPC-Prüfung und kein Leistungsnachweis.

**Neustartkontrolle:** Neuer isolierter Dolphin PID 17640. Gastmailbox mit korrigiertem Manifest erfolgreich verifiziert; serielle Bridge aktiv. P6 liefert bereits wieder frische kalibrierte Daten, P5 nach dem Neustart noch neutral und muss vom Nutzer erneut verbunden werden. Beobachteter Zwischenstand 1.402 gültige Frames, 0 ungültige, 0 Ereignislücken, 0 Queueüberläufe. Keine Hardware-Animationsabnahme behauptet.

### 2026-10-25 — Stuntkorrektur manuell bestätigt, automatische Gerätezuordnung umgesetzt

**Nutzerergebnis / geänderter Auftrag:** Nutzer bestätigt ausdrücklich, dass die Stuntanimationskorrektur funktioniert. Anschließend wünscht er automatische Zuordnung auch beim Wechsel zu anderen Wiimotes, ohne erneute manuelle MAC-Konfiguration. Das ersetzt frühere Pflichtreservierungen. Keine vollständige Item-/Achtgeräte-/Leistungsabnahme daraus ableiten.

**Host:** CLI und Live-Starter verwenden standardmäßig automatische sitzungsbezogene Zuordnung. Tatsächlich verbundene Wiimotes bekommen freie P5–P8-Plätze, unabhängig von Funk-/LED-Platz. Getrennte NVS-Adressen belegen keinen Host-Spielerplatz. Aktive Spieler bleiben stehen; bekannte Wiederverbindungen bevorzugen ihren bisherigen freien Platz, neue Geräte können getrennte Plätze übernehmen. Gleichzeitig neu gemeldete Geräte werden nach Quellslot verarbeitet. Nach ESP32-/Hostneustart beginnt die Reihenfolge neu. `assignments` und `assignment_mode` erscheinen im Konsolenlog. Alte Konfiguration bleibt unverändert und wird nur mit `--manual-mapping` verwendet; automatischer Betrieb benötigt keine Konfigurationsdatei.

**Sitzungsgrenzen:** Geänderte Bindungen/Reconnects erhöhen `routing_revision`. Der Service verwirft Altaktionen an einer definierten ACK-Basis, und der CLI erneuert vor dem nächsten Publish die Mailbox-Hostsession. Dadurch dürfen Geräte mit neu gestarteten Rohzählern übernehmen; alte Gast-ACKs werden anhand der alten Hostsession zurückgewiesen. Die Commitgeneration bleibt monoton. Die vorhandene Gast-ABI bleibt unverändert; alle vier Bridge-Filter durchlaufen dabei einmal die neutrale Sitzungsgrenze. Keine Verschiebung bereits verbundener Spieler. Tatsächlicher PPC-Test belegt die Wiederannahme von Samplefolge 1/Ereignis 1 nach zuvor Samplefolge 500/Ereignis-ACK 100.

**Firmware:** Neue Wiimotes erhalten im normalen BOOT-Kopplungsfenster zuerst einen nie reservierten Funkplatz, sonst automatisch die erste getrennte Reservierung. Aktive Geräte werden nicht verdrängt. Die neue gesamte 24-Byte-Adresstabelle wird vor Live-Übernahme in NVS geschrieben; bei Schreibfehler bleiben alte Tabelle/Erlaubnisliste erhalten. Nach erfolgreichem Austausch wird die Erlaubnisliste aktualisiert. Bekannte Reconnects behalten ihren freien ESP32-Platz und verursachen keinen unnötigen NVS-Schreibzugriff.

**Prüfungen / Artefakte:** 113 gezielte CLI-/Host-/Mailbox-/Runner-/echte PPC-Gasttests erfolgreich. Zusätzlich acht tatsächliche PPC-Prüfungen des portablen Firmware-Zuordnungshelfers, einschließlich aller 16 aktiven Platzmasken und simuliertem NVS-Schreibfehler. Gepinnter PlatformIO-ESP32-Build erfolgreich, vier Frameworkarchive unverändert geprüft; RAM 89.708 Byte, Flash 720.929 Byte. `firmware.bin` SHA256 `6c5a115cba945fd0b160f2994a75c0d5273c398ff19abd9bf8127c657b3511d8`. Noch kein Upload dieser Firmware und kein Abbruch des Nutzertests. Die Hostquellen greifen im laufenden alten Prozess erst nach Neustart. Quellen, Planfortschreibung und Start-/Host-/Firmwareanleitungen aktualisiert.

**Nächster Schritt:** Konkreter geprüfter Uploadstand liegt bereit. Nutzer gefragt, ob der aktuelle Test jetzt beendet, zuvor eine vollständige 4-MB-Sicherung erstellt, die Firmware aktualisiert und Dolphin mit automatischer Zuordnung neu gestartet werden soll. Bestehendes `build/esp32-backup-1mb.bin` ist weiterhin ausschließlich die ältere Teilsicherung. Bei Zustimmung nur den isolierten Testprozess nach EXE/Startzeitprüfung stoppen, COM3/Chip neu abgleichen, vollständige Sicherung vor dem Upload anlegen. Anderen globalen Dolphin erhalten.

### 2026-10-25 — Automatische Zuordnung: freigegebene Geräteaktualisierung begonnen

**Freigabe / Vorbereitung:** Nutzer wählt ausdrücklich „Jetzt aktualisieren und starten“ für vollständige Sicherung, Firmwareupdate und Neustart. Isolierten Dolphin PID 17640 mit EXE/Startzeit `134373921802882565` geprüft und beendet; serieller Kindprozess/Runner wurden freigegeben. Globaler Dolphin PID 11824 bleibt unberührt. COM3 ist weiter eindeutig CP210x. esptool 4.5.1 bestätigt ESP32-D0WD-V3 rev3.1, 240 MHz, 40-MHz-Quarz, Chip-MAC `20:50:0D:D3:23:FC`, Flashhersteller `5e`, Gerät `4016`, erkannte Flashgröße 4 MB.

**In Arbeit:** Vollständiges `read_flash 0x0 0x400000` mit 460800 Baud nach `build/esp32-backup-2026-10-25-before-auto-4mb.bin` (neue Datei, vorhandene Sicherungen nicht überschreiben). Tool-Session 62565, Log `build/esp32-backup-2026-10-25-before-auto.log`. Erst nach erfolgreichem Abschluss, exakter Länge 4.194.304 Byte und Hash sowie Vergleich der vorhandenen Partitionstabelle mit dem Build darf der freigegebene Upload folgen. Geprüfte neue BIN-SHA256 weiterhin `6c5a115cba945fd0b160f2994a75c0d5273c398ff19abd9bf8127c657b3511d8`.

**Lesetransport-Nachtrag:** Zwei Bulk-Läufe mit 460800 Baud schlossen nicht ab und wurden gezielt beendet; es wurde keine vollständige Sicherungsdatei angelegt. Standard-Bulk-Lauf bei 115200 Baud übertrug Daten, brach aber nach ungefähr 741 KB mit `Corrupt data, expected 0x1000 bytes but received 0x10 bytes` ab. Noch kein Flashupload. Lokaler Read-only-Helfer `build/read_flash_windowed.py` nutzt die installierte esptool-4.5.1-Leseroutine mit einem statt 64 unbestätigten UART-Paketen und 64-KB-Abschnitten, jeweils mit originaler Längen-/Geräte-MD5-Prüfung. Paketprotokoll bleibt ausschließlich im lokalen Log. Erste 128 KB so erfolgreich verifiziert; aktueller Lauf Tool-Session 72041, Log `build/esp32-backup-2026-10-25-windowed-debug.log`. Erst vollständiger erfolgreicher Abschluss legitimiert den anschließenden freigegebenen Upload. Die Dateien unter `build/` bleiben außerhalb von Git.

### 2026-10-25 — Vollständige Sicherung und Firmwareupdate erfolgreich, Automatik gestartet

**Sicherung abgeschlossen:** Auch der erste Abschnittslauf brach nach sechs geprüften 64-KB-Abschnitten mit einem Übertragungsfehler ab. Daraufhin derselbe Read-only-Helfer auf 16-KB-Abschnitte mit begrenzter Wiederholung fehlerhafter Reads und gespeicherten geprüften Teilblöcken umgestellt. Alle 256 Abschnitte anschließend erfolgreich gelesen; zusätzlich stimmt die Prüfsumme des gesamten 4-MB-Flashs vom Gerät mit der vollständigen Datei überein. 385,8 Sekunden bei 115200 Baud. Datei `build/esp32-backup-2026-10-25-before-auto-4mb.bin`, exakt **4.194.304 Byte**, SHA256 `7022269a1560804db54c231784b53116794ab2953b1510f7a86dfef4e70e330e`, Geräte-MD5 `daee4532daabe824a29a5cfb4f402f1b`. Metadaten daneben als `.json`, Log `build/esp32-backup-2026-10-25-retry-blocks.log`. Die ältere 1-MB-Sicherung bleibt unverändert. Keine installierten esptool-Pakete dauerhaft verändert.

**Vor Upload geprüft:** Vorhandene Partitionstabelle bei `0x8000` ist bytegleich mit der gebauten Tabelle. NVS liegt bei `0x9000`, Größe `0x5000`; der Upload beschreibt diesen Kopplungsdatenbereich nicht. Firmwaredatei vor und nach Upload SHA256 `6c5a115cba945fd0b160f2994a75c0d5273c398ff19abd9bf8127c657b3511d8`.

**Freigegebener Upload:** PlatformIO `esp32dev` auf explizitem COM3 bei 115200 Baud erfolgreich, Gesamtzeit 49,42 Sekunden. Boot-/Partitions-/Appbereiche jeweils nach Schreiben per Gerätehash geprüft. Anwendung: 727.504 Binärdateibytes (449.440 komprimiert), geschrieben ab `0x10000`. Das ist die Dateigröße einschließlich Imageformat; der zuvor genannte Flashbelegungswert 720.929 Byte ist die Build-Speicherstatistik. Log `build/esp32-auto-upload-2026-10-25.log`. Kein Chip-Erase, keine manuelle NVS-Löschung.

**Neustart:** Normaler Gastbuild mit Stuntkorrektur bleibt unverändert installiert (`9f800f7401161d3c29703371bd853877`). Live-Starter ohne `--manual-mapping` neu gestartet, Tool-Session 4852; Log `build/dev-vanilla/manual-auto-mapping-2026-10-25.log`. Vorhandene manuelle Konfigurationsdatei bleibt erhalten und wird im Standardmodus ignoriert. Andere globale Dolphin-Instanz nicht beendet. Nachprüfung von Verbindung/automatischen Spielerplätzen folgt im laufenden Test; Viergeräte-Ersatzpaarung und Achtgeräte-Laptopabnahme bleiben eigene Hardwareprüfungen.

**Neustart bestätigt:** Neuer isolierter Dolphin PID 22840, Gastmailbox verifiziert und serieller Lauf aktiv. Log zeigt `assignment_mode=automatic`; die beiden bisherigen gespeicherten Geräteadressen sind erhalten. Zuletzt 1.333 gültige Frames, 0 ungültige, keine Ereignislücken/Queueüberläufe, aber noch keine tatsächlich verbundenen Sensorquellen (`assignments={}`, `players_fresh=[]`). Nutzer muss die Wiimotes nach dem Geräteupdate wieder verbinden. Die leeren automatischen Plätze trotz vorhandener alter Adressen bestätigen, dass getrennte NVS-Reservierungen keine Spieler blockieren. Hardwareprüfung neuer Ersatz-Wiimotes bleibt offen. Root/Submodul-Whitespace und vorhandener Wiederaufnahmepatch geprüft.

### 2026-10-31 — Git-Übergabe an den Laptop vorbereitet

**Auftrag / Zugriff:** Nutzer verlangt den Push der Änderungen für die Weiterarbeit am Laptop. Zunächst verweigerte GitHub dem angemeldeten Konto `tillfriedemann-commits` den Zugriff mit HTTP 403; auch die verbundene GitHub-App meldete keine Schreibrechte. Nach der Nutzerbestätigung „Jetzt gehts“ funktionieren Fetch und Push-Dry-Run auf `origin/esp32-support`. Keine Credentials oder Remotes durch diesen Agent geändert, kein Force-Push.

**Gesicherter Umfang:** Alle aktuellen Host-/Firmware-/Gastreceiver-/Test-/Dokumentationsänderungen werden im Hauptrepo zusammengefasst. Die neun lokalen Pulsar-Quelldateien bleiben vollständig im versionierten Patch gegen `a9594663478325ca68ab8e8c3cf7fd332524e821`; dessen SHA256 `74545aaeb295ad3177fb5014de43f5082c98d08dba4925c5b285205ffc67b75d` und Aktualität wurden erneut geprüft. Der Gitlink wird nicht auf einen unveröffentlichten Submodulcommit geändert. Deshalb auf dem Laptop nach der Submodulinitialisierung den Patch einmal anwenden. `docs/LAPTOP-WEITERARBEIT.md` enthält die konkreten Schritte und wurde im README verlinkt. Toolchains, Spielressourcen, lokale Konfiguration, Builds und Flashbackups bleiben außerhalb von Git.

**Aktuelle Prüfergebnisse:** Gesamte Toolsuite mit lokalen PAL-Ressourcen: **167 Tests erfolgreich, eine optionale native Compilerklasse übersprungen**. Zusätzlich **acht Firmware-Zuordnungstests erfolgreich**. Der aktuelle installierte Gastbuild bleibt der bereits manuell geprüfte Stuntfix; durch diesen Git-Übergabeschritt wurde kein neuer Dolphin-Lauf und kein erneuter Firmwareupload ausgelöst. Offene Laptop-/Viergeräte-/Leistungstests stehen in der Laptopanleitung.

**Push erfolgreich:** Quellstand als Commit `fd125e7d0a3a20765a7b08ba7941d8b05b1a8849` erstellt und zusammen mit dem zuvor lokalen Commit `b6b5d7b` auf `https://github.com/Till-glitch/mkwii-8p-splitscreen.git`, Branch `esp32-support`, gepusht. `git ls-remote` bestätigt denselben Commit auf dem Server. Die Anwendbarkeit des Pulsar-Patches auf den sauberen ursprünglichen Submodulindex wurde zusätzlich mit `git apply --cached --check` bestätigt. Das lokale Pulsar-Submodul bleibt erwartungsgemäß geändert; sämtliche neun Quelldateien sind im gepushten Patch enthalten. Für den Laptop zuerst `docs/LAPTOP-WEITERARBEIT.md` lesen.

### 2026-10-31 — Laptop meldet 50 % Geschwindigkeit; Grafik-Override korrigiert

**Nutzerbefund:** Laptop mit i7-1355U, Intel Iris Xe und 16 GB RAM erreicht laut Nutzer bereits bei vier Spielern nur halbe Geschwindigkeit. Auf Nachfrage ausdrücklich etwa 50 % Dolphin-Geschwindigkeit bestätigt; dies ist von den nativen 30 FPS im unveränderten Drei-/Vier-Spieler-Modus zu unterscheiden. Ob der unveränderte Titel unter denselben Einstellungen ebenfalls betroffen ist, wurde zur Eingrenzung nachgefragt. Kein Fernzugriff auf die Laptopkonfiguration; deshalb keine Behauptung einer bereits gemessenen CPU-/GPU-Ursache oder achtspielerfähigen Leistung.

**Belegter Starterfehler / Fix:** `tools/wiimote_bridge/runner.py` und der unbeaufsichtigte Start in `tools/install_8p.py` verwendeten das falsche Config-System `GFX` für `-C`-Overrides. Dolphins Originalquelle, auch Tag 2609a, benennt dieses System `Graphics` (Dateiname bleibt GFX.ini). Beide Startpfade auf `Graphics.Settings.InternalResolution` bzw. `Graphics.Enhancements.MaxAnisotropy` korrigiert. Damit kann eine geerbte höhere Auflösung nicht mehr trotz des beabsichtigten 1×-Overrides aktiv bleiben. Ob dies die konkrete Laptop-Verlangsamung verursacht hat, muss der Nutzer nach Neustart vergleichen. Keine pauschale Änderung von V-Sync, Backend, Takt, Dual-Core-Einstellung oder gespeicherten Profilen.

**Prüfung / nächste Eingrenzung:** 25 Runner-Tests erfolgreich, einschließlich neuem Regressionstest des tatsächlich an Dolphin übergebenen Auflösungs-Overrides. Laptopanleitung um Basistest mit Netzteil/Leistungsmodus, 100%-Geschwindigkeitslimit, V-Sync aus, 1× nativ und Direct3D-12/11-Vergleich für Iris Xe erweitert. Native Vier-Spieler-Basis und Mod mit identischen Einstellungen vergleichen. Die dokumentierten Vorschläge folgen Dolphins Leistungsleitfaden; insbesondere kann V-Sync an einem 30-Hz-Bildschirm genau halbe Geschwindigkeit verursachen. Fix betrifft Python-Starter, kein neuer Code.pul-Build oder Firmwareupload erforderlich.
