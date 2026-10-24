# Pulsar-Änderungen als Entwicklungsstand sichern

Die aktuellen Bridge-Änderungen liegen zunächst uncommittet im Submodul `external/rr-pulsar`. Ein normaler Checkout des Hauptrepositories reproduziert solche lokalen Änderungen nicht. Dafür exportiert `tools/export_pulsar_patch.py` einen anwendbaren Textpatch einschließlich neuer Quelldateien und eine Metadatendatei mit Basiscommit und SHA256.

Der geplante Basiscommit ist `a9594663478325ca68ab8e8c3cf7fd332524e821`. Maßgeblich ist der vom Export tatsächlich in `patches/rr-pulsar-wheel-bridge.json` dokumentierte `base_commit`.

## Export und Aktualitätsprüfung

In der Hauptrepositorywurzel mit einem funktionsfähigen Git im PATH:

```powershell
$env:PATH = 'C:\Program Files\Git\cmd;' + $env:PATH
tools/.venv/Scripts/python.exe tools/export_pulsar_patch.py
tools/.venv/Scripts/python.exe tools/export_pulsar_patch.py --check
```

Standardausgaben:

- `patches/rr-pulsar-wheel-bridge.patch`
- `patches/rr-pulsar-wheel-bridge.json`

`--check` schreibt nichts. Es vergleicht den aktuellen Quellstand, Basiscommit und Patchhash mit den vorhandenen Artefakten. Nach weiteren Pulsar-Änderungen muss der Export erneut ausgeführt werden.

Der Export ruft weder `git add` noch `git commit` auf und aktualisiert den Submodule-Gitlink nicht. Git läuft mit `GIT_OPTIONAL_LOCKS=0`, damit Statusabfragen den Index nicht nebenbei aktualisieren. Neue und geänderte Dateien müssen UTF-8-Text mit einer erlaubten Quellendung sein: `.cpp`, `.hpp`, `.h`, `.S`, `.txt` oder `.md`. Binärdateien, Spielassets, generierte/buildbezogene Pfade und unerwartete Dirty-Dateien führen zu einem Fehler statt zu einem unvollständigen Export. Ignorierte Dateien werden nicht aufgenommen.

## In einer frischen Arbeitskopie fortsetzen

```powershell
git submodule update --init --recursive
git -C external/rr-pulsar rev-parse HEAD
git -C external/rr-pulsar status --short
git -C external/rr-pulsar apply --check ../../patches/rr-pulsar-wheel-bridge.patch
git -C external/rr-pulsar apply ../../patches/rr-pulsar-wheel-bridge.patch
tools/.venv/Scripts/python.exe tools/export_pulsar_patch.py --check
```

Vor dem Anwenden müssen der Basiscommit aus der JSON-Datei und die aktuelle Pulsar-Revision übereinstimmen. Das Submodul soll sauber sein; ein bereits angewendeter Patch wird nicht erneut angewendet. Die Metadaten und der Patch sind gemeinsam zu übertragen. Das Hauptrepo benötigt zusätzlich die anderen neuen Bridge-Quellen und die dokumentierte Toolchain.

Der Patch ist ein Wiederaufnahme- und Entwicklungsartefakt. Er ist kein veröffentlichter Pulsar-Commit, kein bereits aktualisierter Gitlink und kein Nachweis eines sauberen Releasebuilds. Vor einer finalen Veröffentlichung bleibt ein erreichbarer Submodule-Commit mit entsprechend aktualisiertem Hauptrepo erforderlich.
