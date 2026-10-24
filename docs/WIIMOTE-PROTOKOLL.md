# Wii-Bridge-Protokoll W3, Version 1

Stand: 24.10.2026. Dieser Vertrag ist in `shared/wii_bridge_protocol.h` und `tools/wiimote_bridge/protocol.py` implementiert. Er beschreibt den ESP32-/Host-Transport. Eine Gast-Mailbox ist ein eigener Vertrag und darf nicht durch einen ungeprüften Schreibzugriff auf alte Gastadressen ersetzt werden.

## Ziel und Grenzen

Vier ESP32-Geräteslots `0..3` stehen standardmäßig für die zusätzlichen Spieler P5–P8. Ein Slot bezeichnet eine reservierte Geräteidentität; die Verbindungsreihenfolge ist keine Spielernummer. Die native Dolphin-Vierergruppe benutzt dieses USB-Protokoll nicht.

W3 trennt Paketfortschritt, echte Sensorreports und Ereignisse. CRC erkennt Übertragungsfehler; sie ist keine Authentifizierung. Sitzungsprüfung, Reihenfolgen, Timeout, Pufferüberlauf und Gastbestätigung sind Aufgaben der Firmware-/Host-/Gastdienste. Die Codecs prüfen Struktur und Werte und ändern kein Spiel.

Alle Mehrbytewerte sind **big endian**. Die serialisierten Felder werden einzeln gelesen/geschrieben. Die Größe und Ausrichtung eines C++-Structs ist ausdrücklich kein Wireformat.

## Rahmen

Jeder W3-Rahmen hat einen 18-Byte-Header, `payload_length` Nutzbytes und zwei CRC-Bytes. Maximal sind 512 Nutzbytes bzw. 532 Rahmenbytes erlaubt. Ein Rahmen enthält genau einen Nachrichtentyp.

| Offset | Bytes | Feld | Bedeutung |
| --- | --- | --- | --- |
| 0 | 2 | magic | ASCII `W3`, Hex `57 33` |
| 2 | 1 | version | `1` |
| 3 | 1 | kind | Einer der unten definierten Typen |
| 4 | 2 | payload_length | Anzahl Bytes nach dem Header und vor der CRC |
| 6 | 4 | boot_session | Boot-/Transport-Sitzung des ESP32 |
| 10 | 4 | transport_sequence | Paketfolge des jeweiligen Senders |
| 14 | 4 | sender_time_ms | Monotone lokale Senderzeit in Millisekunden, modulo 2³² |
| 18 | variabel | payload | Typabhängige Records |
| 18 + payload_length | 2 | CRC | CRC-16/CCITT-FALSE über Header und Payload |

Python-Headerformat: `>2sBBHIII`. Die CRC verwendet Polynom `0x1021`, Startwert `0xFFFF`, keine Bitreflexion, `xorout=0`. Prüfvektor: ASCII `123456789` ergibt `0x29B1`.

Die Paketfolge läuft je Sender modulo 2³² weiter. Beim ACK übernimmt der Host die gerade gültige ESP32-`boot_session`; sein eigener Paketzähler und sein Zeitstempel gehören weiterhin dem Host. Zahlen werden nicht zwischen unterschiedlichen Zeitdomänen subtrahiert. Null ist auf Codec-Ebene ein gültiger 32-Bit-Wert; die Laufzeitdienste müssen ihre Sitzungsidentität selbst sinnvoll erzeugen und prüfen.

Unbekannte Versionen, Nachrichtentypen, Flags und nicht auf null gesetzte Reserved-Felder werden abgelehnt. Typ `5` ist nicht definiert. Eine künftige Erweiterung braucht eine ausdrücklich kompatible Fähigkeitsvereinbarung oder eine neue Protokollversion.

## Typ 1: SNAPSHOT

Genau vier Records à 24 Byte, mit den vier unterschiedlichen Slot-IDs `0..3`. Normale Sender verwenden die Reihenfolge `0,1,2,3`; Decoder verlangen Vollständigkeit und Eindeutigkeit, keine bestimmte Reihenfolge. Gesamtlänge: **116 Byte**.

Python-Recordformat: `>BBHhhhHIIHH`.

| Recordoffset | Bytes | Feld | Bedeutung |
| --- | --- | --- | --- |
| 0 | 1 | slot_id | `0..3` |
| 1 | 1 | flags | Verbindungs-/Datenzustand |
| 2 | 2 | buttons | Vollständiger aktueller WPAD-Buttonzustand |
| 4 | 2 | accel_x | Kalibrierte Sensorachse, signed int16, zulässig `-512..511` |
| 6 | 2 | accel_y | Wie X |
| 8 | 2 | accel_z | Wie X |
| 10 | 2 | sample_age_ms | Alter des letzten echten Sensorreports, gesättigt bei 65535 |
| 12 | 4 | sample_sequence | Fortschritt echter akzeptierter Sensorreports; kein Versandzähler |
| 16 | 4 | last_event_sequence | Höchste für diesen Slot erzeugte Ereignisfolge |
| 20 | 2 | event_flags | Diagnoseinformationen; kein Ereigniszustellpfad |
| 22 | 2 | reserved | Null |

Sensorwerte verwenden 128 Einheiten pro g. Es wird bereits kalibrierter KPAD-Koordinatenraum transportiert. Der Vertrag selbst führt keine Sensorfilterung oder Winkel-zu-Stick-Umrechnung aus.

Flags:

| Maske | Konstante | Bedeutung |
| --- | --- | --- |
| `0x01` | `FLAG_CONNECTED` | Das reservierte Gerät ist physisch verbunden |
| `0x02` | `FLAG_CALIBRATED` | Gültige EEPROM-Kalibrierung wurde ermittelt |
| `0x04` | `FLAG_SAMPLE_VALID` | Sensorreport ist nach Firmwarekriterien verwendbar |
| `0x08` | `FLAG_EVENT_OVERFLOW` | Ereignisverlust/Überlauf, Eingaben müssen neutral bleiben |

Die Codecs erlauben die vier Bits in beliebiger Kombination. Die Laufzeit prüft zusätzlich sinnvolle Kombinationen und Frische. Ein verbundenes Gerät ohne frischen Sensorreport ist keine gültige Eingabequelle.

`event_flags & 1` (`EVENT_FLAG_TRICK`) zeigt einen momentan beobachteten Schüttel-/Stuntzustand zu Diagnosezwecken. Der Host oder Gast darf daraus keinen weiteren Stunt erzeugen. Zustellung erfolgt ausschließlich über Typ 3.

Bei Sensor-Timeout oder Reconnect darf die Firmware alte wartende Ereignisse verwerfen. `last_event_sequence` und der Ereigniszähler werden dabei innerhalb derselben Bootsession nicht zurückgesetzt. Der Host nutzt den Snapshot als Grenze für eine bewusste Resynchronisierung und darf keine vorher verworfenen Aktionen nachholen. `FLAG_EVENT_OVERFLOW` wird von der aktuellen Firmware bis zum Wiederverbinden gelatcht. Die Regel muss in Host und Gast berücksichtigt werden, nicht im reinen Decoder.

## Typ 2: DEVICES

Genau vier Records à 8 Byte mit unterschiedlichen IDs `0..3`. Gesamtlänge: **52 Byte**. Python-Recordformat: `>BB6s`.

| Recordoffset | Bytes | Feld | Bedeutung |
| --- | --- | --- | --- |
| 0 | 1 | slot_id | `0..3` |
| 1 | 1 | flags | Bit 0 `DEVICE_PRESENT`: diesem Slot ist eine Identität zugeordnet |
| 2 | 6 | mac | Stabile Bluetooth-Geräteadresse in der von der Firmware gelieferten Bytefolge |

`DEVICE_PRESENT` beschreibt eine **reservierte Identität**, auch wenn das Gerät gerade getrennt ist. Der aktuelle Verbindungsstatus kommt aus dem Snapshot. Nicht reservierte Slots haben Flags null; Sender verwenden dort eine Nulladresse. Persönliche Geräteadressen gehören in lokale Konfiguration und werden nicht als allgemeine Beispielzuordnung eingecheckt.

Der Host verändert eine bekannte logische Spielerzuordnung nicht stillschweigend, wenn die Firmware eine andere MAC für denselben Transport-Slot meldet. Eine Bootsession-Änderung ist ebenfalls kein Auftrag, Geräte beliebig neu zuzuordnen.

## Typ 3: EVENTS

Ein bis 32 Records à 16 Byte. Gesamtlänge: `20 + 16*n`. Python-Recordformat: `>BBHIII`.

| Recordoffset | Bytes | Feld | Bedeutung |
| --- | --- | --- | --- |
| 0 | 1 | slot_id | `0..3` |
| 1 | 1 | event_kind | `1 = BUTTONS`, `2 = TRICK` |
| 2 | 2 | value | BUTTONS: vollständiger neuer Buttonzustand; TRICK: Impulswert |
| 4 | 4 | event_sequence | Ereignisfolge dieses Slots, modulo 2³² |
| 8 | 4 | sample_sequence | Zugehöriger echter Sensorreport |
| 12 | 4 | sample_time_ms | Zeitpunkt am ESP32 in dessen Millisekundendomäne |

Mehrere Records desselben Slots sind erlaubt und bleiben in Rahmenreihenfolge erhalten. Press–Release–Press ist eine geordnete Folge dreier vollständiger Buttonzustände. Sie darf nicht zu einer einzelnen Bitmaske zusammengefasst werden.

`value` ist auf Wireebene ein beliebiger uint16. Die Interpretation eines Stuntimpulses wird vom Sensor-/Wheeladapter festgelegt; der Codec behauptet keine vollständige Nintendo-Stuntsemantik.

Ereignisse werden anhand von Bootsession, Slot und Ereignisfolge dedupliziert. Modulo-Reihenfolgen müssen wrap-sicher geprüft werden, mit einer eindeutigen begrenzten Distanz. Ein neuer Snapshot, Paketempfang oder Diagnose-ACK darf nicht als Nachweis einer Verarbeitung im Gast gelten.

Die Queue ist begrenzt. Bei Verlust/Überlauf wird neutralisiert und sichtbar diagnostiziert. Wiederholungen und Nachlauf aus einer alten Sitzung dürfen keine späten Itemwürfe oder Stunts auslösen.

## Typ 4: ACK

Ein bis vier Records à 8 Byte; Slot-IDs innerhalb des ACK sind eindeutig. Gesamtlänge: `20 + 8*n`. Python-Recordformat: `>BBHI`.

| Recordoffset | Bytes | Feld | Bedeutung |
| --- | --- | --- | --- |
| 0 | 1 | slot_id | `0..3` |
| 1 | 1 | reserved | Null |
| 2 | 2 | reserved | Null |
| 4 | 4 | acked_event_sequence | Kumulative letzte bestätigte Ereignisfolge des Slots |

Die Firmware nimmt ACKs nur für ihre gültige Bootsession und gültige Queuepositionen an. Der Host sendet im produktiven Eingabepfad erst eine Bestätigung für Ereignisse, deren Übernahme durch den Gast belegt ist. Ein Diagnosemodus muss eine lokale Quittierung ausdrücklich als solche kennzeichnen und darf damit keine Gastabnahme suggerieren.

Bekannter Golden-Vektor für Session `0x01020304`, Hostfolge `5`, Zeit `6`, ACK für Slot 0 bis Ereignis 7:

```text
57 33 01 04 00 08 01 02 03 04 00 00 00 05 00 00 00 06
00 00 00 00 00 00 00 07 81 06
```

## Legacy W2: Nur Referenz und Diagnose

W2 ist ein fixes 32-Byte-Format ohne Versions-/Sitzungsfeld und ohne transportierte Geräteidentität. Es wird ausdrücklich über `decode_w2()` bzw. `StreamParser(allow_w2=True)` aktiviert. Das veraltete vorverarbeitete `WM`-Format wird nicht als Wheel-Paritätsformat akzeptiert.

| Offset | Bytes | Bedeutung |
| --- | --- | --- |
| 0 | 2 | ASCII `W2` |
| 2 | 1 | Connected-Maske; nur die unteren vier Bits |
| 3 | 1 | XOR über Maske und alle 28 Nutzbytes |
| 4 | 28 | Vier Slots à sieben Byte |

Ein W2-Slot enthält Buttons big endian (2 Byte), drei niedrige Sensorbytes (3 Byte), gepackte Sensorhighbits/Stunt/Kalibrierung (1 Byte) und eine achtbittige Sequenz (1 Byte).

Die Highbits der X/Y/Z-Achse liegen in den Bitpaaren 0–1/2–3/4–5; die zehn Bits werden mit Vorzeichen interpretiert. Bit 6 ist Stunt, Bit 7 EEPROM-kalibriert. Die Skala beträgt ebenfalls 128/g. Die Connected-Maske, Länge und XOR-Prüfung müssen gültig sein.

W2 liefert weder eine verlässliche Ereigniswarteschlange noch den W3-Frische-/Sitzungsvertrag. Insbesondere steigt die alte Referenzsequenz beim Senden und ist kein Nachweis eines neuen Sensorreports. W2 wird nicht stillschweigend in einen produktiven W3-Gasteingabepfad hochgestuft.

## Öffentliche Python-API

Import bei gesetztem `tools`-Suchpfad: `from wiimote_bridge.protocol import ...`.

```python
Frame(kind, boot_session, transport_sequence, sender_time_ms, records)
SnapshotSlot(slot_id, flags, buttons, accel_x, accel_y, accel_z,
             sample_age_ms, sample_sequence, last_event_sequence, event_flags=0)
DeviceRecord(slot_id, flags, mac)  # mac: bytes mit Länge sechs
InputEvent(slot_id, event_kind, value, event_sequence, sample_sequence, sample_time_ms)
EventAck(slot_id, acked_event_sequence)

encode_frame(frame)          # bytes; ProtocolError bei Vertragsverletzung
decode_frame(data)           # Frame mit typisierten, unveränderlichen Records
decode_w2(data)              # LegacySnapshot mit vier LegacySlot-Records
crc16(data)                 # uint16

parser = StreamParser(allow_w2=False, max_buffer=4096)
frames = parser.feed(chunk)  # Liste; Frames und optional LegacySnapshot
parser.reset()              # Teilrahmen verwerfen, Statistik behalten
```

`EventRecord`, `AckRecord` und `StreamDecoder` sind Aliase für `InputEvent`, `EventAck` und `StreamParser`. `crc16_ccitt_false` ist ein Alias für `crc16`.

`Frame.records` ist ein Tupel in empfangener Reihenfolge. `MessageKind` und `EventKind` sind `IntEnum`. Die gültigen Flags werden als Konstanten mit den Namen aus den Tabellen exportiert. Legacy-Dataclasses heißen `LegacySnapshot(connected_mask, slots)` und `LegacySlot(slot_id, connected, calibrated, buttons, accel_x, accel_y, accel_z, sequence, trick)`.

Der Parser akzeptiert beliebig fragmentierte/gemeinsam gelesene Pakete und Störbytes. Sein interner Puffer bleibt unabhängig von der Größe eines einzelnen `feed()`-Aufrufs begrenzt; `max_buffer` muss mindestens 532 sein. Bei ungültigem Rahmen wird byteweise nach einer neuen Magic resynchronisiert. Ein formal plausibler Teilrahmen kann die Resynchronisierung bis zum Eintreffen seiner begrenzten deklarierten Länge verzögern. Die Frischeprüfung des Dienstes bleibt deshalb erforderlich.

Diagnoseattribute: `discarded_bytes`, `invalid_frames`, `frames_decoded`, `buffered_bytes`. Ein gültig dekodierter Frame kann vom Dienst später wegen Sitzung, Folge oder Frische verworfen werden; diese höheren Entscheidungen gehören nicht in die Parserstatistik.

## Öffentliche C++-API

Header: `shared/wii_bridge_protocol.h`, Namespace `WiiBridgeProtocol`. Keine Heapallokation oder Abhängigkeit von Arduino. Bei `__MWERKS__` werden feste Ganzzahltypen mit Größenprüfungen lokal definiert, sodass der Wii-CodeWarrior-Build keine Host-C-Laufzeitheader benötigt.

POD-Namen entsprechen Python, mit camelCase-Feldern: `SnapshotSlot`, `DeviceRecord`, `InputEvent`, `EventAck`. Die zusätzlichen Ansichten heißen `Header` und `FrameView`. `FrameView.payload` zeigt auf den Speicher des Eingabepakets; dieser Speicher muss während der Verwendung gültig und unverändert bleiben.

```cpp
size_t EncodeSnapshot(uint8_t* output, size_t capacity,
    uint32_t bootSession, uint32_t transportSequence, uint32_t senderTimeMs,
    const SnapshotSlot* records, size_t count);
// EncodeDevices / EncodeEvents / EncodeAck analog mit ihrem Recordtyp.

bool DecodeFrame(const uint8_t* data, size_t length, FrameView& frame);
bool DecodeSnapshot(const FrameView& frame, SnapshotSlot* records,
    size_t capacity, size_t& count);
// DecodeDevices / DecodeEvents / DecodeAck analog.

bool DecodeW2(const uint8_t* data, size_t length, LegacySnapshot& result);
uint16_t Crc16(const uint8_t* data, size_t length);
```

Encoder liefern die gesamte Bytezahl, bei ungültigen Daten oder zu kleinem Puffer null. Decoder liefern `false` bei ungültigen Daten; `DecodeFrame` verändert seine Ausgabe nur bei Erfolg. Typdecoder setzen `count` bei einem Fehler auf null. Die Typdecoder werden mit einer zuvor durch `DecodeFrame` validierten, unverändert gebliebenen `FrameView` aufgerufen; sie prüfen deren Recordsemantik erneut, ersetzen aber keine erneute Rahmen-CRC für veränderten Speicher.

## Nachweise und nächste Integrationsprüfungen

`python -m unittest discover -s tools/wiimote_tests -p test_protocol.py -v` prüft ohne Geräte oder Spielressourcen:

- Header-/Recordgrößen, bekannte Bytes und CRC gegen die unabhängige Standardbibliotheksfunktion `binascii.crc_hqx`.
- Alle vier W3-Typen, Grenzwerte, unbekannte Felder, ungültige Reservierungen, Achsen und Slotlisten.
- Einzelbytekorruption, Trunkierung, zusätzliche Bytes und maximale Rahmen.
- Ereignisreihenfolge einschließlich modulo-Wrap und wiederholter Slot-IDs.
- Jede Teilungsposition mehrerer Frames, byteweisen Empfang, Rauschen und Wiederaufnahme nach CRC-/Headerfehlern.
- Pufferbegrenzung bei großen Eingaben sowie Reset bei physischem Reconnect.
- W2-Signierung, Flags, Checksumme und ausdrücklich aktivierten Mischlesebetrieb.

Ein optionaler C++-Harness im selben Testmodul kompiliert den Header mit einem verfügbaren nativen `g++`/`clang++` und vergleicht alle vier W3-Typen bytegenau mit Python. Ohne solchen Compiler wird dieser Nachweis sichtbar übersprungen. Zusätzlich müssen der tatsächliche ESP32-Build und der Wii-CodeWarrior-Build den Header erfolgreich kompilieren.

Noch separat nachzuweisen sind tatsächlicher UART-Betrieb, Boot-/Event-ACK-Lebenszyklus, Überlastung, Sender-/Empfängerfrische, konsistente Gastübergabe und das vollständige Verhalten echter Wheels. Ein erfolgreicher reiner Codec-Test ist keine Hardware- oder Spielabnahme.

Die Rate ist kein Bestandteil des Wireformats. Ein Snapshot benötigt 116 Byte und bei UART 115200/8N1 rechnerisch etwa 10,1 ms reine Leitungsauslastung. Bei 30 Snapshots/s sind das 3480 Byte/s; Ereignisse, Gerätemetadaten und Rückkanal werden zusätzlich budgetiert. Diese Rechenwerte beschreiben keine gemessene Funk-/USB-/Eingabelatenz.
