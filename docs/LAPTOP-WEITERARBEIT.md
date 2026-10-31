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

## Wenn das Spiel zu langsam läuft

FPS und Emulationsgeschwindigkeit getrennt beurteilen: Das unveränderte Mario Kart Wii rendert bei drei/vier Spielern normalerweise 30 FPS. Eine Dolphin-Anzeige von 50 % bedeutet dagegen tatsächliche halbe Emulationsgeschwindigkeit.

Für einen vergleichbaren Basistest im tatsächlich gestarteten isolierten Profil:

1. Laptop am Netzteil betreiben, Windows-Energiemodus auf beste Leistung stellen und Dolphins Geschwindigkeitslimit auf 100 %/Normal prüfen.
2. V-Sync zunächst ausschalten und die Windows-Bildschirmfrequenz prüfen. Dolphin nennt V-Sync bei 30-Hz-Bildschirmen ausdrücklich als mögliche Ursache exakt halber Geschwindigkeit.
3. Interne Auflösung 1× nativ, Kantenglättung aus, keine HD-Texturen/Postprocessing. Auf Intel Iris Xe zuerst Direct3D 12 testen, danach dieselbe Szene mit Direct3D 11 vergleichen. CPU-Taktüberschreibung für diesen Basistest deaktiviert lassen; CPU-Engine auf Standard/JIT und Audio auf DSP-HLE belassen. Dual Core prüfen.
4. Dieselbe Strecke zuerst unverändert mit vier Spielern, dann mit unserem Build vergleichen. Geschwindigkeit, interne Auflösung und Backend notieren. Erst danach acht Spieler beurteilen. Eine Entlastung durch geringere Auflösung deutet auf Grafiklast; unveränderte Geschwindigkeit allein beweist noch keine reine CPU-Grenze.

Am 31.10.2026 wurde ein Starterfehler korrigiert: Kommandozeilen-Overrides benötigen `Graphics.Settings.InternalResolution`, obwohl die Konfigurationsdatei `GFX.ini` heißt. Der alte `GFX`-Override konnte die beabsichtigte native Auflösung nicht durchsetzen. Nach `git pull --ff-only` den Starter neu ausführen; ein neuer Gastbuild oder ESP32-Flash ist für diese Korrektur nicht nötig. Bereits gespeicherte Grafikprofile werden nicht überschrieben.

Primärquellen: [Dolphin-Konfigurationsnamen, Version 2609a](https://github.com/dolphin-emu/dolphin/blob/2609a/Source/Core/Common/Config/Config.cpp), [Dolphin-Leistungsleitfaden](https://dolphin-emu.org/docs/guides/performance-guide/), [Mario Kart Wii im Dolphin-Wiki](https://wiki.dolphin-emu.org/index.php?title=Mario_Kart_Wii).
