# ESP32-Wiimote-Bridge für zusätzliche Spieler 5–8

Status: erste W3-Firmware implementiert und lokal kompiliert. Es wurde kein Gerät geflasht und noch kein Funk-/Hardwaretest durchgeführt.

Der Entwicklungsrechner benötigt kein eigenes Bluetooth-Modul. Ein **originaler ESP32 mit Bluetooth Classic** empfängt vier Wii Remotes und sendet ihre Daten per USB/UART an den Host. ESP32-S3/C3 sind für diesen Wiimote-Pfad kein Ersatz. Die vier direkt mit Dolphin verbundenen Wiimotes kommen später auf dem Ziel-Laptop hinzu.

## Build

Das PlatformIO-Projekt liegt unter `firmware/esp32-wii-bridge/`. Seine reguläre Konfiguration verwendet einen eigenen PlatformIO-Core unter `.pio/core`; die vorhandene globale Installation wird dadurch nicht als veränderlicher Paketbestand vorausgesetzt.

```powershell
cd firmware/esp32-wii-bridge
pio run -e esp32dev
```

Falls PlatformIO nicht im PATH steht, dessen installierte `pio.exe` ausdrücklich verwenden. Der erste reguläre Build lädt die gepinnten Pakete. Die Archive enthalten Bibliotheken für mehrere Targets und können entsprechend groß sein.

Gepinnt sind:

| Bestandteil | Version |
| --- | --- |
| PlatformIO-Plattform | `espressif32@6.10.0` |
| Bluepad-Framework-Archiv | `maxgerhardt/pio-framework-bluepad32@e010351b2cafe3a872f18878cb2d3e08f167c650` |
| Framework-Metadaten | Paket `4.0.2`, Arduino `2.0.17`, Bluepad32-Header `4.1.0` |
| Boardprofil | `esp32dev`; tatsächliches Board vor dem Flashen prüfen |
| Serielle Verbindung | `115200`, 8N1 |

`verify_framework.py` prüft die Git-Blob-Hashes der vier relevanten vorkompilierten Bluepad-/BTstack-Archive und schreibt ein Manifest in das Buildverzeichnis. Eine abweichende lokal gepatchte Bibliothek führt zu einer verständlichen Buildfehlermeldung. Die gegenüber dem Framework benötigten Controllerressourcen werden im Quellcode eingestellt, siehe [Portierungsbefunde](../docs/FIRMWARE-PORTIERUNG.md).

Die Buildprodukte liegen unter `.pio/build/esp32dev/` und bleiben außerhalb von Git. Eine erfolgreiche Kompilierung bestätigt weder den tatsächlichen Chip noch den Viergeräte-Funkbetrieb.

## Vor einem späteren Upload

1. Originalen ESP32-Chip, Board und USB-UART-Gerät feststellen.
2. Den ausdrücklich ausgewählten Port mit `pio device list` und dem angeschlossenen Gerät abgleichen. Es ist kein `COM3` fest im Projekt hinterlegt.
3. Den aktuellen funktionierenden Firmwarestand und die verwendete Quelle dokumentieren.
4. Erst nach dieser Prüfung einen Upload auf genau dieses Gerät ausführen.

Der hier durchgeführte Implementierungsschritt hat keinen Upload gestartet.

## Kopplung und feste Plätze

- ESP32-Slot 0–3 entspricht standardmäßig P5–P8 im Spiel.
- Ein kurzer Druck auf die BOOT-Taste (`GPIO0`), nach dem Booten wieder losgelassen, öffnet bzw. beendet ein Kopplungsfenster von 60 Sekunden.
- In diesem Fenster nur die für den ESP32 vorgesehenen Wiimotes anmelden. Die Laptop-Gruppe bleibt getrennt.
- Die erste Anmeldung reserviert einen noch unbenutzten Platz anhand der Bluetooth-Adresse und speichert die vier Reservierungen in der eigenen NVS-Preferences-Namespace `ss8-wheels`.
- Ein bekanntes Gerät erhält nach dem Wiederverbinden denselben Platz. Ein neues Gerät kann keinen reservierten freien Platz stillschweigend übernehmen.
- Außerhalb des Kopplungsfensters wird die Bluepad-Erlaubnisliste auf die reservierten Geräte eingeschränkt. Unbekannte Geräte werden zusätzlich auf Anwendungsebene abgewiesen.
- Bei vier verbundenen Geräten endet das Kopplungsfenster automatisch.
- Ein BOOT-Druck von mindestens vier Sekunden löscht die eigenen Platzreservierungen **nur wenn kein Controller verbunden ist** und startet den ESP32 neu. Die Bluepad-Bondingdaten werden dabei nicht pauschal gelöscht.

Die übernommenen LED-Werte gehören zur alten akzeptierten Referenz. Ihre sichtbare Zuordnung ist auf dem echten Gerät noch zu prüfen; physische Aufkleber P5–P8 und die Hostdiagnose bleiben die verbindliche Zuordnung.

## Eingabedaten und Fehlerverhalten

- Native Reportdaten `0x31`, originale EEPROM-Kalibrierblöcke und die bisherige Achsennormalisierung werden verwendet.
- Snapshot-Zielrate bleibt ungefähr 60 Hz. Die tatsächliche Sensorfolge steigt ausschließlich bei einem neuen Funkreport.
- Buttons und Schüttelimpulse werden zusätzlich als geordnete sequenzierte Ereignisse gepuffert. Der Host bestätigt über W3-ACKs; Wiederholungen dürfen nicht doppelt ausgelöst werden.
- Der lokale Schütteldetektor läuft unabhängig vom UART-Versand ungefähr 60 Hz mit der alten Rohwertschwelle und einem zeitlichen 100-ms-Status. Die originale Wheel-Filterung erfolgt später im Gast.
- Nach mehr als 250 ms ohne neuen Sensorreport liefert der Snapshot keine gültigen gehaltenen Eingaben. Alte Ereignisse werden verworfen.
- Eine volle Ereignisqueue oder ein ältestes unbestätigtes Ereignis über 250 ms setzt `EVENT_OVERFLOW`; der Slot wird neutral. Der Host muss den aktuellen Ereignis-Highwatermark bestätigen. Erst wenn alle echten Buttons losgelassen sind, darf diese Bestätigung den Slot neu freigeben. Wiederverbinden ist der alternative Reset.
- Ein Host, der später als die Wiimote startet, übernimmt zuerst den Snapshot als Baseline und bestätigt den Highwatermark. Alte vor dem Hoststart gepufferte Tastendrücke werden nicht nachgespielt.
- Ohne gültige EEPROM-Kalibrierung wird kein `SAMPLE_VALID` behauptet. Primär- und Backupblock werden bei Fehlerantwort oder nach 750 ms ohne Antwort erneut angefragt, insgesamt höchstens vier Anfragen pro Verbindung.

Der normale Sketch schreibt keine Textlogs auf den Datenkanal. Boot-/Bluepad-Diagnosen sind abhängig vom vorkompilierten Framework dennoch möglich; der Host muss die W3-Rahmung über Magic, Länge und CRC wiederfinden.

## Noch offene Hardwarearbeit

- Vier echte Geräte gleichzeitig sowie Kopplung, NVS-Persistenz und Wiederverbinden testen.
- Kalibrierantworten unterschiedlicher Wiimote-Modelle sowie die begrenzten Wiederholungsversuche und den Backupblock prüfen.
- UART-Auslastung, tatsächliche Snapshot-/Ereignisrate und Latenz unter Last messen.
- Parser-Hook und Bluepad-Funktionen werden aus der bestehenden Referenz übernommen; ihre langfristige Stabilität mit der gepinnten Version bleibt praktisch zu prüfen.
- Host/Gast-Übernahme und genau einmalige Ereignisverarbeitung in Dolphin abnehmen.
- Rumble, Lautsprecher und ein eigener `+`/`−`-Feedbacktoggle sind noch nicht implementiert.

## Portable Modellprüfungen

`esp32-wii-bridge/test/native_input_model.cpp` prüft Kalibrierung, Achsenwerte, Buttonreihenfolge, ACK-Grenzen, Queueüberlauf, Timeout, sichere Recovery und Zählerüberlauf. Auf einem Rechner mit nativem C++-Compiler:

```powershell
g++ -std=c++11 -Wall -Wextra -Werror esp32-wii-bridge/test/native_input_model.cpp -o wheel-model-test.exe
./wheel-model-test.exe
```

Ein Xtensa-Syntaxcheck ist zusätzlich möglich. Er führt diese Prüfungen nicht aus und ersetzt keinen nativen Testlauf oder Hardwaretest.

