# Firmware-Portierung: Befunde, Ergebnis und Weiterarbeit

Stand: 2026-10-24. Dieser Bericht ergänzt das zentrale [Implementierungsprotokoll](IMPLEMENTIERUNGSSTAND.md).

## Herkunft und Umfang

Die neue Firmware liegt unter `firmware/esp32-wii-bridge`. Übernommen wurden die notwendigen Eingabeteile der vorhandenen Nutzerreferenz:

- `C:\Users\Till\Documents\8 Player MK\esp32-wii-bridge\src\main.cpp`
- `C:\Users\Till\Documents\8 Player MK\shared\wii_sensor_protocol.h`

Die alte Quelle blieb unverändert. Die neue Implementierung enthält keine Rendering-/Injection-Bestandteile und kopiert keine Nintendo-Ressourcen. Die Quelldateien stehen entsprechend der Projektbasis unter GPLv3 oder später; die externen Frameworkbibliotheken behalten ihre eigenen Lizenzen.

## Implementierte Änderungen

1. Vier Geräte, EEPROM-Kalibrierung und native `0x31`-Reportaufnahme kontrolliert portiert.
2. W3-Vertrag aus `shared/wii_bridge_protocol.h` für Snapshots, Geräteidentitäten, Ereignisse und ACKs eingebunden.
3. Sensorfrische vom Transport getrennt: Funksequenz nur bei echten Reports; Snapshots erhalten Sensoralter und Boot-Sitzung.
4. Geordnete Ereignisqueue pro Slot mit 32 Einträgen, Wiederholung bis zur Bestätigung, modularer Sequenzbehandlung und begrenztem Übertragungsumfang.
5. Timeout-/Überlastbehandlung neutralisiert und verwirft verspätete Ereignisse. Recovery benötigt Tail-ACK und vollständig losgelassene echte Buttons oder einen Reconnect.
6. MAC-basierte Reservierung in eigener NVS-Namespace; Reconnect verändert den Spielerplatz nicht.
7. Explizites Kopplungsfenster, Erlaubnisliste und kontrollierte physische Zurücksetzung der Reservierungen.
8. EEPROM-Daten werden vor Übernahme vollständig geprüft. Primär-/Backupblock werden bei Fehlerantwort oder nach 750 ms ohne Antwort mit insgesamt höchstens vier Anfragen pro Verbindung versucht. Ungültige Kalibrierung bleibt sichtbar und sperrt gültige Wheel-Eingaben.
9. Nichtblockierender Versand mit begrenzter UART-Warteschlange; Snapshot-Zielrate ungefähr 60 Hz. Die private Schüttelauswertung läuft davon unabhängig.
10. Framework-Commit gepinnt, vorkompilierte Abhängigkeiten gegen erwartete Hashes geprüft und Controllerressourcen als Quellcode eingerichtet.

## Verdeckte Änderung in der alten Toolchain gefunden

Die alte PlatformIO-Konfiguration verwies auf den veränderlichen Framework-Branch `main`. Der aktuelle Commit dieses Repositories wurde als `e010351b2cafe3a872f18878cb2d3e08f167c650` ermittelt. Metadaten und die relevanten Bibliotheken wurden gegen die vorhandene Installation verglichen.

| Archiv | Erwarteter Git-Blob-Hash am Pin | Lokaler Befund vor dem neuen Build |
| --- | --- | --- |
| `libbluepad32.a` | `21515f20403bea71f6dec720236b5dcf2d24321c` | identisch |
| `libbluepad32_arduino.a` | `e159aa1f8f63598824074c520a92cfa0729c57ad` | identisch |
| `libbluepad32_arduino_bootstrap.a` | `189861531ef3a28801f71dfc3eea14d4c9e433f4` | identisch |
| `libbtstack.a` | `da9e62629786700d5fd03fd5b61ed49cf8638499` | abweichend: `c3773f438a79b57ca7c87256c97cc53131dffba6` |

Das lokale `libbtstack.a.bak` entsprach exakt dem gepinnten Upstream-Archiv. Ein Vergleich seiner Archiveobjekte zeigte nur zwei abweichende Bytes in `btstack_port_esp32.c.obj`, `.rodata + 0x15/0x16`:

- `esp_bt_controller_config_t.ble_max_conn`: von 3 auf 1.
- `esp_bt_controller_config_t.bt_max_acl_conn`: von 2 auf 7.

Die Feldzuordnung wurde mit den gepinnten ESP-IDF-Headern überprüft und wird im neuen Quellcode durch `offsetof`-Assertions abgesichert. Ohne Übernahme dieser Konfiguration würde der unveränderte Frameworkpfad nur zwei BR/EDR-ACL-Verbindungen reservieren.

Die neue Datei `src/bt_controller_config.cpp` ersetzt den versteckten Binärpatch durch einen Linkerwrapper für `esp_bt_controller_init`. Er kopiert die übergebene Konfiguration und stellt dieselben beiden Werte vor dem Originalaufruf ein. Die Firmware akzeptiert weiterhin genau vier Wiimotes; die Ressourcenreservierung für sieben ACLs ist keine behauptete Unterstützung von sieben Controllern.

Der globale Cache wurde nicht gepatcht oder zurückgesetzt. Für den Prüfbau wurde ausschließlich eine projektlokale Kopie des nachweislich unveränderten Backup-Archivs verwendet. Die Linkmap bestätigt, dass diese Kopie tatsächlich gelinkt wurde.

## Buildnachweis und seine Grenze

Erfolgreich kompiliert wurden `firmware.elf` und `firmware.bin` für `esp32dev` mit PlatformIO Core 6.2.0, Plattform 6.10.0 und dem vorhandenen Xtensa-Compiler 8.4.0+2021r2-patch5. Der Linkerwrapper wurde gegen das unveränderte geprüfte BTstack-Archiv gebaut.

Der Prüflauf nutzte eine gitignorierte projektlokale `.pio/cache-build.ini`, die auf den bereits vorhandenen Paketcache verweist. `SS8_BTSTACK_ARCHIVE` wählte die projektlokale unveränderte Bibliothek aus. Die reguläre versionierte Konfiguration verwendet den Framework-Commit und einen eigenen `.pio/core`; ein vollständiger neuer Download dieses Pins wurde bei diesem Prüflauf nicht durchgeführt. Der Hashabgleich sichert die vier relevanten vorkompilierten Bluetootharchive ab, behauptet aber keinen vollständigen Bytevergleich jedes Frameworkbestandteils.

Letzter erfolgreicher Build dieses Portierungsschritts: 8,01 Sekunden, RAM 89.708 / 327.680 Byte, Flash 720.645 / 1.310.720 Byte. SHA-256 von `firmware.bin`: `4B2A25BBABE458C3DE8972751AC1D4C74069510215D6891FCF515DE4D6EE8F9A`. Ein Buildmanifest mit den geprüften Bibliothekshashes wird unter `.pio/build/esp32dev/framework-manifest.json` erzeugt. Diese Werte gelten für den beschriebenen Stand und sind nach Änderungen neu zu erfassen.

Der portable Modelltest wurde mit `xtensa-esp32-elf-g++.exe -std=c++11 -Wall -Wextra -Werror -fsyntax-only test/native_input_model.cpp` erfolgreich auf Syntax und Warnungen geprüft. Damit ist sein Laufzeitverhalten noch nicht getestet; ein nativer Testlauf bleibt offen.

Es wurde **keine Firmware hochgeladen**. Viergeräte-Funkbetrieb, tatsächliche UART-Latenz, EEPROM-Antworten und Parser-/Threadverhalten sind noch nicht am Gerät nachgewiesen.

## Vertrag für Host und Gast

- `DEVICES` mit `DEVICE_PRESENT` bezeichnet eine reservierte Geräteidentität, auch während eines Disconnects. Der Verbindungszustand stammt aus dem Snapshot.
- Event- und Sensorsequenzen laufen innerhalb einer Boot-Sitzung auch über Disconnects hinweg weiter.
- Disconnect und Sensorstale verwerfen die Queue; bereits erzeugte Ereignisnummern werden dabei nicht zurückgesetzt.
- Der Host synchronisiert beim Erstkontakt, nach Disconnect und nach Fault über den Snapshot-Highwatermark und spielt alte Queues nicht nach.
- ACKs sind nur für die passende Boot-Sitzung gültig. Zukunfts-ACKs über die letzte erzeugte Ereignisnummer hinaus werden ignoriert.
- `EVENT_OVERFLOW` bedeutet volle Queue oder ältestes unbestätigtes Ereignis über 250 ms; der Host hält den Platz neutral und bestätigt den aktuellen Highwatermark weiter.
- Nur eine Bestätigung genau des aktuellen Highwatermarks bei losgelassenen echten Buttons hebt den Fault auf. Danach erzeugt der nächste frische Report eine neue Buttonbaseline.
- `event_flags` im Snapshot sind Diagnosezustand. Stunts werden aus den geordneten Ereignissen verarbeitet und dürfen daraus nicht zusätzlich ausgelöst werden.
- Der zeitliche Schüttelstatus bildet die alte Schwelle und ungefähr 100 ms Haltedauer ab. Die vollständige native Stunt-/Wheel-Verarbeitung und sichtbare Animation sind ein separater Dolphin-Nachweis.

## Noch zu tun

- Portablen Modelltest mit einem nativen C++-Compiler ausführen; der lokale Entwicklungsrechner hatte bislang keinen solchen Compiler im verfügbaren PATH.
- Regulären Build aus einem frisch geladenen Framework-Pin zusätzlich prüfen.
- Konkretes Board und Port feststellen; erst danach den Uploadschritt entscheiden und dokumentieren.
- Timeout/Backup/Wiederholung bei vollständig ausbleibender EEPROM-Antwort am echten Gerät prüfen.
- Mit vier echten Wiimotes Queue-/ACK-Latenz und Recovery unter USB-Unterbrechung prüfen.
- Prüfen, ob der Bluepad32-Parser eigene Discovery-/LED-/Reportmode-Meldungen in den UART-Kanal schreibt. Sketch selbst erzeugt keine Textlogs; Hostresynchronisierung ist erforderlich.
- Physische LED-Zuordnung, NVS-Persistenz und erlaubte Reconnects der gespeicherten MAC-Adressen prüfen.
- Feedback bleibt nachrangig: Rumble, Lautsprecher und spezieller Feedback-Toggle sind bislang ausgelassen.

## Primärquellen

- [Gepinntes Framework](https://github.com/maxgerhardt/pio-framework-bluepad32/tree/e010351b2cafe3a872f18878cb2d3e08f167c650).
- [ESP32-Bibliotheksverzeichnis an diesem Pin](https://github.com/maxgerhardt/pio-framework-bluepad32/tree/e010351b2cafe3a872f18878cb2d3e08f167c650/tools/sdk/esp32/lib).
- Lokale ESP-IDF-Header des geprüften Frameworks: `tools/sdk/esp32/include/bt/include/esp32/include/esp_bt.h`.
