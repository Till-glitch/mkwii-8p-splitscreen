# Start und Prüfen der Wheel-Bridge

Stand: 25.10.2026. Entwicklungsstand für Dolphin, Vanilla und PAL/RMCP01.

## Was bereits geprüft ist

- Native PAL-Wheel-/Item-Verarbeitung statt der früheren linearen Ersatzlenkung.
- Geordnete Button-/Stunt-Ereignisse mit Quittierung erst nach Verarbeitung.
- Getrennte logische Identitäten für Bridge-Plätze P5–P8 und native Wii-Kanäle.
- Kompilierter Vanilla-Gastbuild und ein synthetischer Achtspieler-Durchlauf bis zur VS-Rennszene mit weiterem Eingabefortschritt.
- PowerPC-Vergleichstests gegen getrennte Originalfunktionen. Deren Emulatorgrenzen stehen in [WHEEL-NATIVE-PORT.md](WHEEL-NATIVE-PORT.md).

Eine Abnahme mit vier physischen Bridge-Wiimotes, acht echten Geräten am Ziel-Laptop, sichtbaren Stuntanimationen und gemessenen 60 FPS steht weiterhin aus. Der Entwicklungsrechner braucht kein Bluetooth-Modul: Der ESP32 empfängt seine vier Wiimotes selbst und ist über USB angeschlossen. Auf dem Laptop sind P1–P4 direkt über Dolphin vorgesehen.

## Build und eigenes Profil

Alle Befehle laufen aus der Repositorywurzel in PowerShell. Toolchain und `.env` werden gemäß Haupt-README eingerichtet. Die vorhandene neue Projektumgebung liegt unter `tools/.venv`; auf einem anderen Rechner eine eigene Umgebung mit den gepinnten Anforderungen anlegen.

```powershell
tools/.venv/Scripts/python.exe -m pip install -r tools/requirements-build.txt -r tools/requirements-bridge.txt
tools/.venv/Scripts/python.exe tools/build_code.py --vanilla --wheel-bridge
```

Für manuelles Spielen den normalen Build verwenden. `--menu-script` enthält automatisierte Testeingaben und gehört ausschließlich in einen Testlauf.

Die lokale Entwicklungskopie `build/dev-vanilla` wurde bereits separat mit dem Original-PAL-Abbild eingerichtet. Auf einem neuen Rechner zuerst `tools/install_8p.py --help` und die Vorbereitung im Haupt-README verwenden. Das Originalabbild ausdrücklich auswählen, wenn die bisherige Wheel-Wizard-Konfiguration noch auf eine alte modifizierte WBFS-Datei zeigt.

Den normalen Bridge-Build anschließend nur in die eigene Kopie installieren:

```powershell
tools/.venv/Scripts/python.exe tools/install_8p.py --vanilla --root build/dev-vanilla code vanilla --from build/code-vanilla-wheel/Code.pul
```

Die Starter verlangen ein ausdrücklich ausgewähltes Buildmanifest. Dessen benachbartes `Code.pul` muss mit dem installierten übereinstimmen; eine alte beliebige Buildvariante wird nicht automatisch gewählt.

## ESP32 und Zuordnung

Der vorhandene ESP32 wurde bereits auf W3 umgestellt. Die Hostzuordnung erfolgt jetzt automatisch. Die Firmwareerweiterung vom 25.10.2026 erlaubt außerdem den automatischen Austausch getrennter Geräte, wenn alle vier ESP32-Plätze bereits reserviert sind; dafür muss der neue Firmwarebuild installiert sein. Den tatsächlichen lokalen Uploadstand führt [IMPLEMENTIERUNGSSTAND.md](IMPLEMENTIERUNGSSTAND.md). Firmwarequellen und Upload stehen in [firmware/README.md](../firmware/README.md).

Serielle Geräte auflisten und zunächst ohne Dolphin diagnostizieren:

```powershell
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --ports
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --diagnose --seconds 10
```

Automatische Portwahl funktioniert nur bei einem eindeutig geeigneten USB-UART-Gerät. Bei mehreren Kandidaten den ermittelten Port mit `--port` angeben. `COM3` ist keine allgemeine Vorgabe.

Die erste tatsächlich verbundene Wiimote bekommt automatisch P5, die nächsten P6–P8. Die LED-/ESP32-Slotnummer ist dafür unerheblich. Gespeicherte Adressen getrennter Geräte belegen im Host keinen Spielerplatz. Innerhalb eines Hostlaufs kehrt ein bekanntes Gerät an seinen bisherigen Platz zurück, solange er frei ist. Neue Geräte dürfen freie Plätze übernehmen; bereits verbundene Spieler werden dabei nicht verschoben. Bei gleichzeitig gemeldeten Verbindungen entscheidet die Reihenfolge der ESP32-Slots.

Es sind keine MAC-Eingaben und keine Konfigurationsdatei nötig. Neue Geräte normal koppeln: BOOT kurz drücken und loslassen, dann SYNC an der Wiimote. Die automatische Hostzuordnung und ihre Geräteadressen stehen im Konsolenlog.

Nur für eine ausdrücklich gewünschte feste Zuordnung bleibt der manuelle Modus verfügbar:

```powershell
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --assign '00:11:22:33:44:55=5'
```

Die Beispieladresse ersetzen. Solche Reservierungen unter `build/wiimote-bridge/config.json` werden ausschließlich mit `--manual-mapping` verwendet; den Schalter beim Live-Starter ergänzen. Vorhandene alte Konfigurationen bleiben erhalten und schränken den automatischen Standardmodus nicht ein. `--config` wählt bei Bedarf eine andere manuelle Datei. Weitere Details stehen in [HOST-BRIDGE.md](HOST-BRIDGE.md).

## Manueller Live-Lauf

```powershell
tools/.venv/Scripts/python.exe tools/run_live_bridge.py --root build/dev-vanilla --manifest build/code-vanilla-wheel/wheel-bridge-manifest.json
```

Falls der Installer noch keinen gültigen Dolphin-Pfad kennt, `--dolphin-exe 'C:\Pfad\Dolphin.exe'` mit dem tatsächlichen Pfad ergänzen. Der Pfad wird nicht aus der Entwicklungsmaschine fest übernommen.

Der Starter sperrt das eigene Profil, startet genau einen eigenen Dolphin-Prozess, prüft seine Identität und die aktuelle Gastsession, ermittelt eine passende RAM-Ansicht und startet die serielle Bridge. `Strg+C` beendet den eigenen Lauf. Ein anderes laufendes Dolphin wird nicht über eine ausgetauschte PID-Datei beendet. Ein belegtes Profil wird vor Log-/PID-Änderungen abgewiesen. Eine verwaiste `lane.lock` erst nach Prüfung des aufgeführten Prozesses behandeln, nicht während eines noch laufenden Tests löschen.

P1–P4 auf dem Entwicklungsrechner mit tatsächlich bedienbaren emulierten/Keyboard-Controllern im isolierten Dolphin-Profil konfigurieren. Der physische Laptop-Test verwendet stattdessen die vier nativen Real-Wiimotes. Die bisherige globale Dolphin-Konfiguration und alte Renderer-Injections werden für diese Kopie nicht benötigt.

Die Controllerregistrierung fordert die Plätze der Reihe nach an. Auch bei bereits verbundenen ESP32-Wiimotes zuerst P2–P4 anmelden; erst danach nehmen die Felder P5–P8 deren A/2-Bestätigung an. Für einen Lauf mit zwei Bridge-Wiimotes sechs Spieler auswählen. In der aktuellen lokalen Tastaturkonfiguration bestätigen V, B und N die emulierten Wiimotes für P2, P3 und P4. Diese Tasten sind profilspezifisch und keine feste Vorgabe für andere Rechner.

### Sichtbarer Stunttest

Der manuelle Build vom 25.10.2026 berücksichtigt bei der Figuren-Abstandsprüfung auch die Kameras P5–P8. Zuvor konnte ein Spieler fern von P1–P4 als zu weit entfernt gelten: Das Spiel nahm den Stunt samt Boost an, übersprang aber die Figurenanimation. Die Korrektur ändert weder den originalen Stuntpuffer noch die Animations- oder Boostzeiten.

Für die Nachprüfung P1–P4 stehen lassen und mit P5 bzw. P6 wegfahren. Mehrfach an einer gut sichtbaren Rampe stunten und Animation sowie Landeboost getrennt beobachten. Anschließend kleinere Sprünge vergleichen; kurze Flugzeiten können die originale Animation weiterhin verkürzen. Prüfen, dass die Animation auch weit entfernt von den ersten vier Kameras sichtbar bleibt. Der PPC-Test reproduziert den alten Entfernungsfehler und bestätigt den korrigierten Animationsaufruf; die sichtbare Abnahme im echten manuellen Lauf bleibt separat zu dokumentieren.

## Synthetische Regression

Dieser Lauf verwendet kontrollierte Testeingaben und öffnet keinen seriellen Port. Er ersetzt keine Prüfung physischer Wiimotes.

```powershell
tools/.venv/Scripts/python.exe tools/build_code.py --vanilla --wheel-bridge --menu-script
tools/.venv/Scripts/python.exe tools/install_8p.py --vanilla --root build/dev-vanilla code vanilla --from build/code-vanilla-menu-wheel/Code.pul
tools/.venv/Scripts/python.exe tools/install_8p.py --vanilla --root build/dev-vanilla script tools/menu_scripts/v-8p-bridge-race.txt
tools/.venv/Scripts/python.exe tools/test_player8_race.py --root build/dev-vanilla --manifest build/code-vanilla-menu-wheel/wheel-bridge-manifest.json
```

Erfolg setzt acht gebundene Plätze, VS-Rennmarker für acht lokale Spieler sowie nachfolgende Gasttick-/Eingabefortschritte voraus. Allein eine hohe Generationsnummer oder die Join-Maske reicht nicht. Der JSON-Bericht unter `build/dev-vanilla/synthetic-race-report.json` kennzeichnet synthetische Daten, physische Abnahme und FPS-Nachweis getrennt. Screenshots liegen unter `build/dev-vanilla/shots/` und benötigen eine visuelle Prüfung.

## Softwareprüfungen und Weiterarbeit

```powershell
tools/.venv/Scripts/python.exe -m pip install -r tools/requirements-test.txt
tools/.venv/Scripts/python.exe -m unittest discover -s tools/wiimote_tests
```

Für den zusätzlichen Vergleich mit Original-PAL-Code `MKW_PAL_RESOURCE_ROOT` auf einen lokalen Ordner mit `sys/main.dol` und `files/rel/StaticR.rel` setzen. Diese Dateien werden weder heruntergeladen noch ins Repository aufgenommen. Ohne Ressourcen bzw. Toolchain werden die betreffenden optionalen Prüfungen ausdrücklich übersprungen.

Nachfolgende Agents lesen zuerst [IMPLEMENTIERUNGSSTAND.md](IMPLEMENTIERUNGSSTAND.md), [PULSAR-PATCH.md](PULSAR-PATCH.md) und den Status von Hauptrepo und Pulsar-Submodul. Das Patchartefakt sichert die aktuellen lokalen Pulsar-Änderungen; es ersetzt noch keinen veröffentlichten Submodulcommit.
