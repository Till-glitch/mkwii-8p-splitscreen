# Native PAL-Wheel-Verarbeitung: Port und Prüfnachweise

Stand: 2026-10-24. Ergänzung zum zentralen Implementierungsprotokoll.

## Zweck und Herkunft

`external/rr-pulsar/PulsarEngine/SplitScreen8/WheelNative.hpp/.cpp` ersetzt die bisherige lineare Beschleunigungswert-zu-Stick-Umrechnung durch die vom Nutzer akzeptierte native Filterkette. Grundlage sind die alten Nutzerdateien `mkw-8p/wii_wheel_native.h`, `wii_wheel_items.h` und die Aktionsbelegung aus `wii_bridge.h` unter der alten Projektwurzel.

Die neue Implementierung verwendet die aktuellen GameSource-Typen. Sie übernimmt keine alten Renderer-, Speicher-Mailbox- oder globalen Injection-Hooks. Native Spieladressen stehen ausschließlich als eindeutig präfixierte Aliase in `GameSource/symbols.txt`; der C++-Code ruft die Symbole auf.

## Schnittstelle und Speicher

Im Namensraum `SplitScreen8` stehen bereit:

```cpp
void ResetWheelNative(WheelNativeState&);
void StepWheelNative(WheelNativeState&, const WiiBridgeProtocol::SnapshotSlot&,
                     u16 rawButtons, bool autoDrift, u8 trickPulse, Input::State&);
void ResetWheelActions(WheelActionState&);
void ApplyWheelActions(WheelActionState&, u16 rawButtons, bool autoDrift, Input::State&);
u8 QuantiseWheelNativeSteering(f32 steering);
```

- `WheelNativeState`: `0x5F4` = 1.524 Byte pro Bridge-Controller; eigene Wheel-, SDK- und Itemzustände. Vier Instanzen benötigen 6.096 Byte.
- `WheelActionState`: `0x24` = 36 Byte pro nativer Wiimote; nur private Item-/Button-Latches, ohne doppelte Sensorfilter.
- Beide Zustände sind einfache Speicherstrukturen ohne globale Konstruktoren. Die Größen werden zur Kompilierzeit geprüft.
- `StepWheelNative` erwartet frische, vorab geprüfte Sensordaten und genau einen Aufruf pro Gast-Eingabetick. Der Adapter übernimmt Timeout, Tick-Caching und Ereignisreihenfolge.
- `rawButtons` stammen aus dem tatsächlich übernommenen geordneten Buttonzustand. `trickPulse` ist ein einmalig übernommenes Ereignis mit Werten 0–4, keine Auslösung aus dem Snapshot-Diagnoseflag.
- `ResetWheelNative` wird bei Session-/Szenenwechsel oder Verbindungsverlust benötigt. Ein Driftmoduswechsel initialisiert betroffene Zustände ebenfalls neu.
- `ApplyWheelActions` verändert die gewünschte Aktionsbelegung und Itemrichtung Y. Bereits nativ berechnete X-Lenkung und beide Flick-/Stuntfelder bleiben byteweise erhalten.

Die Bridge-Kette ist: kalibrierte `/128 g`-Achsen → originaler KPAD-Skalarfilter mit privatem SDK-Zustand → originaler adaptiver Wheel-Filter → native Quantisierung → nativer Spiegelsetter → gewünschte Aktionen und originale Itemdecoder → Stuntsetter.

Die Quantisierung führt zwei einzelne Gleitkommamultiplikationen in ursprünglicher Reihenfolge aus: erst `1.0800000429153442f * steering`, anschließend `7.0f * scaled`. Ein kleiner PPC-Helper benutzt ausdrücklich `fctiwz` und `extsb`, anschließend erfolgt die native Begrenzung auf −7…7 und die Verschiebung auf 0…14. Dadurch entstehen weder eine neue Deadzone noch Rundung oder undefinierte C++-Float-zu-Int-Konvertierungen bei NaN/Inf.

## Verifizierte PAL-Aufrufe

| Alias | PAL-Adresse | Verifizierter Vertrag |
| --- | --- | --- |
| `ss8WheelNativeReset` | `0x80746AFC` | `r3 = eigener Wheel-Owner`, `r4 = Owner + 0x18`, `r5 = Auto-Drift` |
| `ss8WheelNativeUpdate` | `0x80746C64` | Gleiche Ownerzeiger, `r5 = KPAD-Präfix mit hold/trigger/release und drei f32-Achsen` |
| `ss8WheelNativeScalarFilter` | `0x8019548C` | `r3 = privater SDK-Owner`, `r4 = Komponenten-Zustand`, `f1 = neuer Achsenwert` |
| `ss8WheelNativeItemManual` | `0x8074612C` | Owner, `u16* Aktionen`, `hold/trigger/release`, `u8* Itemrichtung` |
| `ss8WheelNativeItemAutomatic` | `0x807462B8` | Gleicher Vertrag, automatischer Itemdecoder |
| `ss8WheelNativeSetStickXMirrorCheck` | `0x8051E960` | `Input::State*`, quantisierter Wert; Spiegelung genau einmal |
| `ss8WheelNativeSetMotionControlFlick` | `0x8051EB68` | `Input::State*`, Flick 0–4; Links/Rechts-Spiegelung genau einmal |
| `ss8WheelNativeKpadThreshold` | `0x8034587C` | Laufzeit-Schwellwert der nativen KPAD-Filterung |
| `ss8WheelNativeKpadGain` | `0x80345880` | Laufzeit-Gain der nativen KPAD-Filterung |
| `ss8WheelNativeKpadFlags` | `0x80345D14` | Übernommene native SDK-Filterflags |
| `ss8WheelNativeUpdateStatesCore` | `0x8051FBE0` | `WiiController*`, `UIState*`, `State*`; aktualisiert UI aus bereits berechnetem Rennzustand |
| `ss8WheelNativeMotionInit` | `0x807459E4` | `MotionController*`, Auto-Drift; originaler Lebenszyklus der nativen Bewegungszustände |

Alle zwölf Aliase liegen in genau einer Abbildungsrange je P/E/J in der vorhandenen `versions.txt`. Das bestätigt die Linkerabdeckung, noch keine funktionale Freigabe auf USA-/Japan-Ressourcen. Der ausgeführte Vergleich betrifft PAL.

Der automatische Itemdecoder liest zusätzlich einen vom Originalspiel initialisierten Maskenwert bei `0x809C2C40`. Der originale REL-Initializer `0x80747154` setzt dort `0x040C`. Die Tests führen diesen Originalinitializer aus; eine künstlich vollständig nullgesetzte REL-BSS wäre für diesen Decoder keine gültige Spielsituation.

## Anbindung der vier nativen Wiimotes

Der Originalcode von `WiiController::UpdateImpl` enthält die passende nachgelagerte Aufrufstelle:

```text
0x8051FE34  bl 0x80745DE4       MotionController::UpdateForCore ist abgeschlossen
0x8051FE40  mr r3, r26         WiiController* this
0x8051FE44  mr r4, r28         UIState*
0x8051FE48  mr r5, r27         State*
0x8051FE4C  bl 0x8051FBE0       UpdateStatesCore
```

Ein Wrapper an `0x8051FE4C` kann zuerst den originalen Core-UI-Aufruf ausführen und danach `ApplyWheelActions` auf einem privaten `WheelActionState` pro nativer Wiimote anwenden. Dabei werden keine nativen Sensordaten ein zweites Mal gefiltert. Die tatsächliche Hook-/Adapterintegration wird vom Hauptagent in `WheelBridge.cpp` vorgenommen; dieses Portierungsarbeitspaket hat jene Datei nicht verändert.

Die Integration ist inzwischen im Gesamtbuild vorhanden. Dieser Callsite gehört ausschließlich zum Core-/Wheel-Zweig. Ein zusätzlicher `GetType()==WHEEL`-Guard wäre dort falsch: Das neue Typfeld wird erst später bei `0x8051FE90` geschrieben, sodass ein Wechsel von einer Extension sonst einen Tick lang die alte Aktionsbelegung erhalten würde. Stattdessen werden native Kanalgrenze und tatsächliche Controllerzeiger geprüft.

Der direkte native `MotionController::Init`-Aufruf liegt bei `0x8051F2E8`: `r3 = controller->motionController`, `r4 = controller->isDriftAuto`. Ein eigener Wrapper setzt dort die privaten nativen Aktions-Latches zurück. `WiiController::ResetSelf` bei `0x805228B4` dispatcht hingegen lediglich zu `StopRumble`; es ist kein Sensorreset. Deshalb verwendet die Bridge für Filter-Lebenszyklen eine getrennte Methode `ResetWheelState()` und koppelt diese nicht an Rumble-Cleanup oder normale Reportlücken.

Zusätzlich veröffentlicht der Bridge-Adapter das vom Original bei `0x8051FF58–0x8051FF60` gesetzte UI-Gültigkeitsbit an `UIState+0x30`. Bei neutralen bzw. ungültigen Eingaben wird es gelöscht. Die erweiterten Menüs allein würden das fehlende Bit nicht zuverlässig aufdecken; native UI-/Pausepfade benötigen ebenfalls den richtigen Zustandsvertrag.

## Gewünschte Belegung

- `2`: Gas.
- `1`: vorhandene Brems-/Rückwärtsaktion; bei frisch gedrückter `1` unter gehaltenem `2` der akzeptierte Hop-/Drift-Latch bis zur Freigabe einer der beiden Tasten.
- `A`: Rückblick.
- `B`: Item halten, über eine äquivalente native Wheel-Halterichtung.
- Richtungsimpulse überschreiben die Halterichtung, sodass der native Decoder unmittelbar wirft und seine ursprüngliche kurze Richtungsnachhaltung behält.
- Manuelle und automatische Drift verwenden jeweils ihren originalen Itemdecoder.
- Stunts stammen aus einem übernommenen geordneten Ereignis. Snapshot-`eventFlags` lösen keine zusätzlichen Stunts aus.

Menüaktionen werden weiterhin vom Adapter unabhängig von den Rennaktionen erzeugt.

## Dauerhafte PPC-Prüfungen

Testquellen:

- `tools/wiimote_tests/wheel_native_harness.cpp` kompiliert die tatsächliche neue `WheelNative.cpp` und die gemeinsame logische Controlleridentität mit CodeWarrior.
- `tools/wiimote_tests/test_wheel_native_ppc.py` führt die erzeugten PPC-Funktionen in Unicorn aus und vergleicht sie mit unabhängig fortgeschriebenen Original-PAL-Funktionen.

Die optionalen lokalen Spielressourcen müssen als Verzeichnis mit `sys/main.dol` und `files/rel/StaticR.rel` vorliegen. Weder Spielressourcen noch abgeleitete Binärdaten werden eingecheckt. Lokaler geprüfter Aufruf:

```powershell
$env:MKW_PAL_RESOURCE_ROOT = 'C:\Users\Till\Documents\8 Player MK\mkw\orig\RMCP01'
tools/.venv/Scripts/python.exe -m unittest discover -s tools/wiimote_tests -p test_wheel_native_ppc.py -v
```

Alternativ direkt mit Parameter:

```powershell
tools/.venv/Scripts/python.exe tools/wiimote_tests/test_wheel_native_ppc.py --pal-resource-root 'C:\Pfad\zu\RMCP01' -v
```

Die Tests benutzen den vorhandenen `tools/mkwdis.py`-Loader und dessen tatsächliche REL-Relokationen. Sie lesen nicht die alten Injection-Builds oder deren globalen Hookzustand. Bei fehlender Ressourcenangabe wird die native Ressourcenklasse mit deutlicher Begründung übersprungen. Eine ausdrücklich konfigurierte, aber unvollständige Ressourcenwurzel ist ein Fehler.

### Durchgeführtes Ergebnis

Neun Testmethoden bestanden ohne Skip mit den lokalen PAL-Ressourcen:

- 50 Quantisierungsfälle gegen den originalen PPC-Quantisierungstail, einschließlich Grenzwerte, NaN, ±Inf und sehr großer endlicher Werte.
- 2.624 Lenkzustände gegen vier getrennte originale KPAD-/Wheel-Referenzzustände, jeweils manuell/automatisch und normal/gespiegelt. Langsame Neigungen, Gegenlenken, Schüttelvektoren, Invertierung und Nullvektoren sind enthalten.
- 504 Item-Ausgaben gegen unabhängig fortgeschriebene Originaldecoder, inklusive explizitem längerem B-Halten und unmittelbarem Richtungswurf bei gehaltenem B.
- Prüfung der gewünschten Hop-/Drift-/Rückblickfolge, Driftmoduswechsel und vollständiger Resets.
- Nachweis, dass native X-Lenkung und Flick bei reiner Aktionsanpassung unverändert bleiben.
- Diagnose-Stuntflag wird ignoriert; echte Flickimpulse und ihre Spiegelung werden einmalig korrekt übernommen.
- Drei echte PPC-Tests für getrennte Registrierungs-IDs, native Display-ID-Übersetzung und exakt 16 Byte große Proxyparameter mit unabhängigen logischen Adressen. Ungültige Slots verändern keine Bytes.

Ohne PAL-Ressourcen laufen die drei Identitätsprüfungen weiterhin erfolgreich. Nur die zusätzlichen sechs Methoden der Ressourcenklasse werden dann als Klasse übersprungen.

### Grenzen der Prüfung

Unicorn unterstützt die benötigten Gekko-PSQ-Speicherbefehle nicht vollständig. Wie im alten unabhängigen Verifier werden die entsprechenden Registerspill-/Restorebefehle übersprungen und die originalen Sinus-/Kosinus-Tabellenzugriffe durch gleichartige float32-Interpolation repräsentiert. Die entscheidenden Filter- und Decoderfunktionen sowie Quantisierung und Setter laufen als PPC-Code. Dieser Vergleich ersetzt keine gesamte Funkstrecke, keine praktische Fahrgefühlabnahme und keinen Nachweis sichtbarer Stuntanimationen in Dolphin.

Der integrierte Vanilla-Menübuild kompiliert und linkt erfolgreich. Den aktuellen Stand der synthetischen Dolphin-Regressionsläufe führt `IMPLEMENTIERUNGSSTAND.md`. Reale Fahr-/Menütests auf dem Entwicklungsrechner bzw. Ziel-Laptop bleiben eigene Abnahmen. Die ältere lineare Gastlenkung und deren Snapshot-Stuntauslösung dürfen nach dieser Umstellung nicht mehr als Steuerungsreferenz verwendet werden.
