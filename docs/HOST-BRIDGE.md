# Windows-Host-Bridge: aktueller Implementierungsstand

Stand: 24.10.2026. Der Host transportiert validierte W3-Eingaben und unterstützt die neue **diagnostische** Gast-Mailbox. Ein Gast mit ausschließlich Capability `1` bindet noch keine Wheel-Controller an Spieler-Holder. Ein erfolgreiches ACK dieses Gasts bestätigt Diagnosekonsum, keine Spielsteuerung.

## Einstieg

Alle Befehle werden in der Repositorywurzel ausgeführt. Der Python-Aufruf kann durch den tatsächlichen Interpreter der eigenen Projektumgebung ersetzt werden.

```powershell
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --help
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --ports
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --diagnose --port COM7 --seconds 20
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --diagnose --port COM7 --record build/captures/first-w3.jsonl
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --replay build/captures/first-w3.jsonl
```

`COM7` ist ein Beispiel, kein voreingestellter Port. Für serielle Modi wird `pyserial` benötigt. Hilfe, Konfiguration, Dateireplay, Parser und Servicekern benötigen nur die Python-Standardbibliothek. Das alte `dolphin_memory_engine` wird nicht zum Schreiben verwendet, weil die lokal vorgefundene API keine verifizierbare Auswahl eines konkreten Dolphin-PID bereitstellt.

Die Portliste wird nur automatisch ausgewählt, wenn genau ein bekannter USB/UART-Kandidat vorhanden ist. Bei mehreren Kandidaten oder unbekanntem Chip ist `--port` erforderlich. Ein beliebiges erstes USB-Gerät wird nicht geöffnet. VID/PID erkennen nur einen UART-Kandidaten; anschließend werden W3-Rahmen, Sitzungen und Geräteidentitäten geprüft.

`--diagnose` ist ein ausdrücklicher Diagnoseempfänger: gültige Ereignisse werden untersucht und optional aufgezeichnet, danach bestätigt, damit die Firmwarewarteschlange nicht durch fehlende Diagnose-ACKs überläuft. Dabei findet kein Dolphin-Zugriff statt. Das normale Konsolenprotokoll wird auf ungefähr eine Zusammenfassung pro Sekunde begrenzt; es zeigt Rohslots, Sensorfolge, gemeldetes Sensoralter, Geräte, Zuordnung und Fehlerzähler.

Eine Aufnahme wird exklusiv neu angelegt; vorhandene Dateien werden nicht überschrieben. Die JSONL-Datei enthält die ursprünglichen seriellen Byteblöcke mit monotonen relativen Nanosekunden. Replay durchläuft denselben Parser und Servicekern. `--speed 1` spielt in aufgezeichneter Zeit, `--speed 0` ohne Wartezeit. Replay greift weder auf einen COM-Port noch auf einen Dolphin-Prozess zu.

Alte W2-Aufnahmen lassen sich mit `--allow-w2` diagnostizieren. W2 bekommt eine gesonderte Referenzanzeige und kann nicht an die neue Gast-Mailbox angehängt werden. Das veraltete WM-Format wird nicht als W3- oder Wheel-Nachweis behandelt.

## Geräte explizit für P5–P8 reservieren

```powershell
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --assign 00:11:22:33:44:55=5
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --assign 00:11:22:33:44:66=6
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --remove 00:11:22:33:44:55
```

Die Beispieladressen sind durch echte, aus der Diagnose bekannte Adressen zu ersetzen. Die lokale Datei liegt standardmäßig unter `build/wiimote-bridge/config.json`; sie bleibt außerhalb von Git. `--config` wählt eine andere lokale Datei.

Format:

```json
{
  "version": 1,
  "assignments": {
    "00:11:22:33:44:55": 5
  }
}
```

Die Reservierung wird atomar gespeichert. Ein Gerät oder Spieler kann nicht stillschweigend einer anderen Reservierung zugewiesen werden. Eine alte Zuordnung muss ausdrücklich entfernt werden. Unbekannte Geräte erscheinen in der Diagnose, liefern aber keine aktiven Gast-Slots. Eine doppelte Geräteidentität in einer Metadatentabelle neutralisiert den mehrdeutigen Zustand.

Der Host übersetzt Firmware-Slots anhand der MAC-Reservierung in logische Slots `0..3`, entsprechend P5–P8. Gast-ACKs werden entsprechend zurück auf den Firmware-Slot übersetzt. Die native Vierergruppe P1–P4 auf dem Laptop verwendet diesen ESP32-Transport nicht.

## Frische, Ereignisse und Wiederherstellung

- Eine neue Transportfolge bedeutet nicht automatisch einen frischen Funkreport.
- Derselbe Sensorzähler verlängert die Gültigkeit einer Eingabe nicht. Gemeldetes Sensoralter und monotone Hostzeit bestimmen die Frische.
- Für aktive Gastdaten sind Verbindung, Sensorvalidität und geprüfte Kalibrierung erforderlich. Standardtimeout: 250 ms, über `--timeout-ms` konfigurierbar.
- Ereignisse werden pro Slot sequenziert, entdoppelt und begrenzt vorgehalten. Im Gastbetrieb folgen ACKs dem bestätigten Gastkonsum; Diagnosebetrieb ist ein gesonderter ausdrücklicher Empfänger.
- Erste Verbindung und Disconnect definieren neutrale Synchronisationspunkte. Der High-Watermark aus dem Snapshot wird als verworfene Altbasis übernommen; frühere Trigger werden nicht nachgespielt.
- Eine neue ESP32-Bootsitzung löscht Geräte-/Sensor-/Ereigniszustände. Vorherige Sitzungen werden nicht erneut angenommen.
- Ereignislücke, Warteschlangenüberlauf, zu alte Ereignisse oder ausbleibender Gastkonsum neutralisieren den betroffenen Slot. Beim nächsten Fehler-Snapshot wird die alte Ereignisbasis ausdrücklich bestätigt und verworfen. Die Firmware kann ihren Überlauf nach passendem High-Watermark-ACK und Loslassen aller physischen Tasten aufheben. Der Host gibt den Slot nach einem frischen gültigen Snapshot ohne Überlauf und mit losgelassenen Tasten wieder frei. Alternativ ist ein kontrolliertes Wiederverbinden möglich.
- Bei COM-/Prozessfehlern beendet diese erste CLI-Version den Lauf mit einer Fehlermeldung. Eine erneute Ausführung verbindet die Quelle neu und handelt Sitzungen neu aus. Automatisches Wiederöffnen eines möglicherweise anders belegten COM-Ports ist noch nicht implementiert.

Ein neutraler Abbruch kann beim späteren nativen Itemdecoder dessen regulären Releaseeffekt auslösen. Die eigentliche Itemsemantik und vollständige Pause-/Wiederverbindungsabnahme sind Aufgaben der Wheel-Controllerintegration; der derzeitige Diagnoseempfänger beweist sie nicht.

## Explizite diagnostische Gastanbindung

Erforderlich sind:

1. Ein unterstützter PAL/RMCP01-Gastbuild mit aktivierter Bridge und zugehörigem Buildmanifest.
2. Der konkrete bereits gestartete Dolphin-PID und der vollständige Pfad seiner EXE.
3. Die Gastadresse des `SS8WBRG1`-Descriptors aus diesem Build bzw. dem Debugger.
4. Die Hostadresse der MEM1-Abbildung genau dieses Dolphin-Prozesses; gegebenenfalls zusätzlich MEM2.

Es gibt in dieser Version noch keine automatische RAM-/Descriptor-Discovery. Die Adressen werden nicht aus dem alten Projekt übernommen oder anhand unbekannter Dolphin-Offets geraten.

```powershell
tools/.venv/Scripts/python.exe -m tools.wiimote_bridge --attach --port COM7 `
  --pid <DOLPHIN_PID> --dolphin-exe '<DOLPHIN_EXE>' `
  --mem1-base <HOST_MEM1_BASIS> --descriptor <GAST_DESCRIPTOR_ADRESSE> `
  --manifest build/code-vanilla-wheel/wheel-bridge-manifest.json
```

Die Platzhalter sind ausdrücklich keine ausführbaren Beispieladressen. Numerische Adressen können hexadezimal mit `0x` angegeben werden. Bei MEM2-Adressen ist zusätzlich `--mem2-base` erforderlich.

Das Windows-Backend öffnet ausschließlich den gewählten PID und prüft EXE-Pfad, Prozessstartzeit und Lebendigkeit. Es verlangt keine Debugprivilegien und hängt sich nicht an den ersten passenden Prozessnamen. Gastzugriffe werden nur auf explizit abgebildetes MEM1/MEM2 übersetzt. Erst nach Prüfung von Spiel-ID, Descriptorkopie, CRC, ABI, Build-ID, Gastsession und nicht überlappenden Speicherbereichen wird der **640-Byte-Eingabepuffer** als einzige Schreibregion freigegeben.

Eine geänderte Gastsession, geänderter Descriptor oder beendeter Prozess erfordert eine ausdrückliche neue Verbindung. Es gibt keine unbegrenzten Warteschleifen beim Lesen eines Statussnapshots. `--drive` verlangt Capability `2` und wird bei einem reinen Diagnosebuild abgewiesen.

## Gastvertrag v1

Alle Mehrbytefelder sind Big Endian. CRC32 ist IEEE, entsprechend Python `zlib.crc32`. Ein ungerader Generationswert bedeutet „in Bearbeitung“; vollständige Generationen sind gerade und ungleich null.

| Region | Aufbau |
| --- | --- |
| Descriptor 64 Byte | `SS8WBRG1` ab 0; ABI/Größe ab 8; Capabilities ab 12; Build-ID16 ab 16; Gastsession ab 32; Inputadresse/-größe ab 36; Statusadresse/-größe ab 44; Slotzahl4/reserved ab 52; ready1 ab 56; CRC32 der ersten 60 Byte ab 60 |
| Input 640 Byte | Generation ab 0; Gastsession4; Hostsession8; Publishfolge12; ESP32-Bootsession16; Hostzeit20; Ereigniszahl24; Slotzahl26; CRC28; vier W3-Slotrecords ab 32; höchstens 32 W3-Ereignisse ab 128; Rest null |
| Input-CRC | Bytebereich `[4:28]` zusammen mit `[32:640]`, Generation und CRC-Feld ausgenommen |
| Status 96 Byte | Generation0; Gastsession4; Gasttick8; Hostsession12; Publishfolge16; Quellsession20; Flags24; Fehler28; vier Ereignis-ACKs32; vier Sensorfolgen48; Bindungsmaske64; Inputalter68; akzeptiert72; abgelehnt76; reserved80–91; CRC92 |
| Status-CRC | `[4:92]` |

Der Host schreibt ungerade Generation → Nutzdaten/CRC → gerade Generation. Der Gaststatus wird kopiert und seine Generation erneut gelesen; Generation, Session, CRC und reservierte Felder müssen passen. Host und Gast schreiben getrennte Bereiche.

## Prüfnachweise und offene Arbeit

```powershell
tools/.venv/Scripts/python.exe -m unittest discover -s tools/wiimote_tests -p 'test_host*.py' -v
```

Aktuell geprüft: Mapping/Persistenz, eindeutige Portwahl, Quellenzuordnung, Sensorfrische trotz Transportfortschritt, Ereignisduplikate/-lücken, ACK-Grenzen, Disconnect-/Boot-/Überlaufverhalten, gealterte Ereignisse, JSONL-Roundtrip, CLI-Hilfe und Replay ohne optionale Pakete, Mailboxlayout/CRC/Commit sowie abgewiesene Schreibversuche bei falschem Spiel, Build, Prozess oder überlappenden Speichern.

Nicht als geprüft ausgegeben werden echter COM-Betrieb, tatsächliche Windows-ReadProcessMemory-Anbindung an Dolphin, Hardwarelatenz oder Fahrverhalten. Die erste Version benötigt noch automatische, belegte RAM-Discovery und automatischen kontrollierten Port-Reconnect. Der nächste funktionale Schritt bleibt die tatsächliche Gast-Wheel-/Holder-Anbindung.
