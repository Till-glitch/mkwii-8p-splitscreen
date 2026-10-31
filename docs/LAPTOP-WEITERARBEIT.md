# Auf dem Laptop weiterarbeiten

Stand: 31.10.2026. Branch: `esp32-support`.

## Repository und Pulsar-Quellen übernehmen

Für eine neue Arbeitskopie einen kurzen Windows-Pfad wählen:

```powershell
git clone --branch esp32-support --recurse-submodules https://github.com/Till-glitch/mkwii-8p-splitscreen.git C:\src\mkwii-8p
cd C:\src\mkwii-8p
```

Bei einer vorhandenen sauberen Arbeitskopie stattdessen:

```powershell
git fetch origin
git switch esp32-support
git pull --ff-only origin esp32-support
git submodule update --init --recursive
```

**Anschließend den mitversionierten Pulsar-Patch anwenden.** Der Gitlink zeigt auf die ursprüngliche Revision; die neun geänderten Pulsar-Dateien werden als Patch im Hauptrepo übertragen. Auf einem sauberen Submodul einmal ausführen:

```powershell
git -C external/rr-pulsar apply --check ../../patches/rr-pulsar-wheel-bridge.patch
git -C external/rr-pulsar apply ../../patches/rr-pulsar-wheel-bridge.patch
```

Bei bereits angewendetem Patch oder eigenen Submoduländerungen nicht erneut anwenden. Details und Basisrevision: [PULSAR-PATCH.md](PULSAR-PATCH.md). Ein danach als geändert angezeigtes Pulsar-Submodul ist für diesen Entwicklungsstand erwartet.

## Lokale Umgebung

Python 3.12 und die Toolchain aus dem Haupt-README einrichten. Lokale Compiler, `.env`, Spielabbild, Dolphin-Profil, Builddateien und Flashbackups werden nicht über Git übertragen.

```powershell
py -3.12 -m venv tools/.venv
tools/.venv/Scripts/python.exe -m pip install -r tools/requirements-build.txt -r tools/requirements-bridge.txt -r tools/requirements-test.txt
tools/.venv/Scripts/python.exe tools/export_pulsar_patch.py --check
tools/.venv/Scripts/python.exe tools/build_code.py --vanilla --wheel-bridge
```

CodeWarrior/Kamek müssen davor gemäß README lokal vorhanden und in `.env` eingetragen sein. Originales PAL-Spielabbild und tatsächlichen Dolphin-Pfad des Laptops für ein eigenes Profil verwenden; keine absoluten Pfade des Entwicklungs-PCs übernehmen. Installation und manueller Start: [START-8-WIIMOTES.md](START-8-WIIMOTES.md).

## Hardware und nächster Test

Der vorhandene ESP32 ist bereits mit der neuen Firmware geflasht. Ein Rechnerwechsel allein erfordert kein erneutes Flashen. USB-Port automatisch erkennen lassen oder den auf dem Laptop ermittelten COM-Port angeben. Wiimotes erhalten automatisch freie P5–P8-Plätze; keine MAC-Konfiguration übertragen. Neue Fernbedienungen über BOOT am ESP32 und SYNC koppeln.

Im isolierten Dolphin-Profil die vier nativen Wiimotes für P1–P4 konfigurieren. Danach zuerst die kombinierte Nutzung mit ESP32-Wiimotes prüfen: unabhängige Anmeldung, Lenkung, Items, Stunts, Pause und Wiederverbinden. Acht echte Geräte und die Leistungsabnahme auf dem Laptop stehen noch aus. Die sichtbare Stuntkorrektur wurde auf dem Entwicklungs-PC vom Nutzer bestätigt.

Nachfolgende Agents lesen zuerst [IMPLEMENTIERUNGSSTAND.md](IMPLEMENTIERUNGSSTAND.md). Dort stehen Änderungen, Prüfergebnisse und die nächsten offenen Schritte.
