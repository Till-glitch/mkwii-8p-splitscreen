# Deep-Thinking Analyse & Review-Punkte für nachfolgende Agents

Dieses Dokument richtet sich an tiefer denkende Folge-Agents und Systemarchitekten. Es fasst die getroffenen Low-Level- und Architektur-Entscheidungen der ESP32-Wii-Bridge für den 8-Spieler-Splitscreen in Mario Kart Wii zusammen und definiert eine priorisierte Liste von Aspekten, die vor dem finalen Produktiveinsatz (insbesondere auf dem Ziel-Laptop mit 8 echten Wiimotes) einer tieferen Prüfung unterzogen werden sollten.

**Einordnung nach Quellenabgleich:** Die automatisierten Beitritts-/Rennaufbautests speisen synthetische Snapshots direkt in die Gast-Mailbox ein. Sie bestätigen noch keine acht echten Wiimotes, originales Wheel-Fahrgefühl, korrekte Item-/Stuntverarbeitung oder 60 FPS im Rennen. Maßgeblich sind die korrigierten Nachweisgrenzen und nächsten Schritte in `IMPLEMENTIERUNGSSTAND.md`. Die nachfolgenden Adressen sind Beispiele aus einzelnen Läufen und keine wiederverwendbaren festen Mailboxadressen.

---

## 1. Aktueller Systemzustand & Verifizierter Status

Der vollständige Pfad von der Eingabe-Emulation über die W3-Protokollframes, den Windows-Host-Dienst, die MEM1-Mailbox und die Pulsar-Engine bis zum aktiven 8-Spieler-Splitscreen-Rennen wurde automatisiert durchgetestet und mit visuellen Snapshots nachgewiesen:

1. **Host-Gast-Kopplung (MEM1 Seqlock Mailbox):**
   - 64-Bit Dolphin-Prozess wird über [`windows_memory.py`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/tools/wiimote_bridge/windows_memory.py) via `VirtualQueryEx` und `ReadProcessMemory` nach der PAL-Signatur (`RMCP01` + Magic `0x5D1C9EA3`) gescannt.
   - Gast-Descriptor (`SS8WBRG1`, ABI 1, `CAP_DIAGNOSTIC | CAP_WHEEL_INPUT`) liegt im BSS von [`WheelBridge.cpp`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/external/rr-pulsar/PulsarEngine/SplitScreen8/WheelBridge.cpp) (`0x803b2284`).
   - Mailbox-Puffergrößen: 640 Bytes Input-Puffer (`u32 inputStorage[160]`), 96 Bytes Status-Puffer (`u32 statusStorage[24]`).
   - Seqlock-Konsistenz: `generation`-Zähler (ungerade = Schreibvorgang aktiv, gerade = konsistent, 0 = inaktiv).

2. **Gastseitige Controller-Integration ([`BridgeWheelController`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/external/rr-pulsar/PulsarEngine/SplitScreen8/WheelBridge.hpp)):**
   - Erbt von `Input::Controller` (`GetType() == WHEEL`).
   - Dynamische Instanziierung über Placement-New in `Initialize()` verhindert statische Konstruktoraufrufe in `_ctors` vor dem Laden von `StaticR.rel`.
   - **Zyklische Aktualisierung:** In `UpdateWheelBridge()` wird für alle 4 Bridge-Controller `sBridgeControllers[i].UpdateImpl(...)` aufgerufen, bevor `Holder(4..7).Update(isPaused)` in `UpdateExtHolders` ([`Input.cpp`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/external/rr-pulsar/PulsarEngine/SplitScreen8/Input.cpp#L80-L86)) die Zustände in `holder.uiinputStates` und `holder.inputStates` übernimmt.

3. **Verifizierter End-to-End-Fluss:**
   - 8-Spieler-Beitritt (`bound_player_mask = 0xF0`, Slots 0–3 gebunden an Spieler 5–8).
   - 8-Spieler-Charakterauswahl (alle 8 Spieler bestätigt mit `[OK]`).
   - 8-Spieler-Fahrzeug- und Drift-Auswahl.
   - **8-Spieler-Splitscreen-Rennen (Luigi Circuit) mit 8 parallelen 3D-Kamerarenderings, HUDs und aktiver Beschleunigung/Lenkung aller 4 Bridge-Karts.**
   - 6.940 Frames ohne Protokollfehler übertragen (Status-Generation 19.606).

---

## 2. Deep-Thinking Review-Punkte nach Themenbereichen

### Fokus 1: Speicherkonsistenz & PowerPC JIT Schranken (Host vs. JIT)

- **PowerPC Speicherschranken (`MemoryBarrier`):**
  - In [`WheelBridge.cpp`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/external/rr-pulsar/PulsarEngine/SplitScreen8/WheelBridge.cpp#L24-L26) wird `asm { sync }` genutzt:
    ```cpp
    static void MemoryBarrier() { asm { sync } }
    ```
  - *Prüffrage:* Reicht `sync` im Dolphin PowerPC-JIT unter allen Compiler-Optimierungsstufen (CodeWarrior `-O4,p`) aus, um Compiler-Reordering zu verhindern, oder sollte ein Compiler-Barrier `asm { ; }` bzw. `volatile`-Zugriff auf alle Puffer-Elemente erzwungen werden?
  - *Status:* `source` ist als `volatile u8*` deklariert; Seqlock-Generation-Checks validieren `before == after && Read32(copy) == before`. In bisherigen Tests über 15.000 Frames trat kein einziger CRC- oder Seqlock-Fehler auf.

- **Dolphin MEM1 Paging & Dual-Core-Modus:**
  - Im Standard-Dolphin-Betrieb läuft der CPU-Thread getrennt vom GPU-Thread (`Dual Core = Yes`).
  - *Prüffrage:* Wenn Dolphin mit getrenntem CPU-Thread läuft, greift `WriteProcessMemory` des Host-Prozesses asynchron zum PowerPC-Interpretationszyklus ein.
  - *Zu prüfen:* Führt eine Schreiboperation während eines laufenden Frames zu einem transienten `ERROR_CRC` im Mailbox-Receiver? Der Receiver verwirft inkonsistente Frames sauber (`Fail(ERROR_CRC)`), ohne abzustürzen. Gibt es bei sehr hoher Frame-Frequenz verworfene Frames?

---

### Fokus 2: UART-Bandbreite, Latenz & Baudraten-Skalierung

- **Berechnung der Datenrate bei 4 aktiven Wiimotes:**
  - Protokoll: W3 Frame ([`wii_bridge_protocol.h`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/shared/wii_bridge_protocol.h)).
   - Snapshot pro Slot: **24 Bytes**. 4 Slots = 96 Bytes Payload + 18 Bytes Header + 2 Bytes CRC = **116 Bytes pro W3-Frame**.
   - Bei 60 Hz Update-Rate: $116 \times 60 = 6.960\text{ Bytes/s}$.
   - Serial-Overhead (8N1): 10 Bits pro Byte $\rightarrow 69.600\text{ Bit/s}$.
   - Bei 115.200 Baud liegt die rechnerische Auslastung allein für Snapshots bei ungefähr **60,4%**; Übertragungszeit je Snapshot ungefähr **10,1 ms**. Das sind Rechenwerte, keine End-to-End-Latenzmessung.
- **Spitzenlast durch Ereignisse (Shake / Gesten):**
  - Schüttel-Ereignisse (Stunts/Wheelies) erzeugen zusätzliche `EVENT`-Records (**16 Bytes pro Event**), zuzüglich Rahmen- und gegebenenfalls Wiederholungsaufwand.
  - *Prüffrage:* Bei gleichzeitigem Schütteln von 4 Spielern kann die Datenrate kurzzeitig ansteigen.
  - *Empfehlung für den Agenten:* Prüfen, ob eine Erhöhung der UART-Baudrate auf **230.400** oder **460.800 Baud** auf dem ESP32 ([`firmware/esp32-wii-bridge/platformio.ini`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/firmware/esp32-wii-bridge/platformio.ini)) und im Host-Service ([`tools/wiimote_bridge/service.py`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/tools/wiimote_bridge/service.py)) zusätzliche Latenzreserven schafft, ohne die Signalintegrität des USB-Serial-Wandlers (CP2102/CH340) zu beeinträchtigen.

---

### Fokus 3: Lenkungsphysik & Wheel-Kalibrierungsmatrix

- **Heuristik des übernommenen Prototyps (inzwischen ersetzt):**
  ```cpp
  float steer = 0.0f;
  const int rawX = slot.accelX; // 128 Einheiten = 1g
  if (rawX < -8 || rawX > 8) {
      steer = float(rawX) / 100.0f;
      if (steer < -1.0f) steer = -1.0f;
      if (steer > 1.0f) steer = 1.0f;
  }
  const int qX = 7 + int(steer * 7.0f + (steer >= 0.0f ? 0.5f : -0.5f));
  const u8 quantX = u8(qX < 0 ? 0 : (qX > 14 ? 14 : qX));
  state.quantisedStickX = quantX;
  state.stick.x = float(int(quantX) - 7) / 7.0f;
  ```
- *Prüffrage für den Agenten:*
  - Die akzeptierte Referenz nutzt originale KPAD-/Wheel-Funktionen, private Filterzustände und die native Quantisierung. Die im ursprünglichen Review behauptete konkrete `atan2`-Formel ist damit noch nicht als vollständiger Originalalgorithmus belegt.
  - Die aktuelle Implementierung projiziert rein die Rohachse $X$ mit linearer Skalierung (`/ 100.0f`) auf 15 diskrete Stufen (`0..14`).
  - *Aufgabe:* Die akzeptierten originalen Funktionen samt Operationsreihenfolge portieren und gegen unabhängige Referenzen prüfen. Keine weitere frei gewählte Winkel-, Deadzone- oder Rundungsformel als Ersatz einführen. Anschließend das gesamte Fahrgefühl auf echten Geräten vergleichen.
  - *Aktualisierung:* `WheelNative.hpp/.cpp` ersetzt diese Heuristik inzwischen durch die akzeptierten originalen PAL-Funktionen. Native Codevergleiche und ihre Grenzen sind in `WHEEL-NATIVE-PORT.md` dokumentiert. Die physische Fahrprüfung bleibt erforderlich.

---

### Fokus 4: Menü- und Szenenübergänge (Lifecycle & Garbage Collection)

- **Verhalten bei Rückkehr ins Hauptmenü:**
  - In [`Entry.cpp`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/external/rr-pulsar/PulsarEngine/SplitScreen8/Entry.cpp):
    ```cpp
    menuLocalCount = 0;
    ClearExtPads();
    ```
  - `ClearExtPads()` setzt die `Holder(4..7)` wieder auf `&input->dummyController` zurück, merkt sich jedoch den gebundenen Controller in `extPads[i].controller`.
  - *Prüffrage:* Wenn ein 8-Spieler-Rennen beendet wird und die Spieler wieder im Menü landen: Werden die `BridgeWheelController` sauber wiedererkannt, ohne dass die Wiimotes neu registriert werden müssen?
  - *Prüfpfad:* Im Menüskript oder Live-Test eine Rennebene verlassen und wieder ansteuern.

- **Award Ceremony / Battle Mode:**
  - In `Hud.cpp` und `Entry.cpp` gibt es Guards für `MODE_AWARD` und `MODE_BATTLE`.
  - *Prüffrage:* Werden im Battle-Modus die erweiterten HUDs und Culling-Matrizen für Spieler 5–8 ebenso fehlerfrei wie im VS-Rennen instanziiert?

---

### Fokus 5: 2.4-GHz-Funkkoexistenz auf dem Ziel-Laptop

- **Kritische Hardwarekonfiguration auf dem Ziel-Laptop:**
  - **Spieler 1–4:** Direkt über internes Bluetooth des Laptops in Dolphin (Native Wiimote Mode / Real Wiimotes).
  - **Spieler 5–8:** Über Bluetooth des ESP32, der per USB am Laptop angeschlossen ist.
  - **Koexistenz:** 8 Bluetooth-Controller (Human Interface Device / L2CAP-Streams) funken simultan im 2,4-GHz-ISM-Band in unmittelbarer Nähe zueinander.
- *Prüffrage für den Agenten:*
  - Können Paketkollisionen oder Frequenz-Hopping-Konflikte auftreten?
  - *Empfohlene Best Practices:*
    1. Den ESP32 nicht direkt an die USB-Buchse direkt neben der internen WLAN/Bluetooth-Antenne des Laptops stecken, sondern ein kurzes USB-Verlängerungskabel (30–50 cm) verwenden, um räumliche Antennentrennung zu erreichen.
    2. Wenn möglich, das Laptop-WLAN auf 5 GHz festlegen, damit der 2,4-GHz-Äther ausschließlich den Wiimotes zur Verfügung steht.

---

### Fokus 6: Portierung auf Retro Rewind (Full Mod mit Custom Tracks)

- Der bisherige Durchstich ist isoliert auf **Vanilla PAL (`RMCP01`)** nachgewiesen (`-DSS8_VANILLA -DSS8_WHEEL_BRIDGE`).
- **Retro Rewind ist eine spätere optionale Erweiterung**; der aktuelle Implementierungseinstieg und erste Abnahmen bleiben Vanilla/PAL:
  - *Unterschiede:* RR6 nutzt MEM2 intensiv für Custom Tracks (Szs), Custom Characters und zusätzliche Sounds.
  - `WheelBridge` belegt ca. 1.200 Bytes in MEM1 (BSS).
  - *Prüfaufgabe:* Bei Übergang auf das volle RR6-Profil (`build_code.py --wheel-bridge` ohne `--vanilla`) prüfen, ob die Linker-Symbole und Speicherheaps mit den erweiterten Pulsar-Heaps harmonieren.

---

### Fokus 7: Dolphin Controller-Sicherheit & WPAD Kanal-Grenzen

- **WPAD Kanal-Grenzen (`WPAD_CHAN_0` .. `WPAD_CHAN_3`):**
  - Im originalen RVL-WPAD-Subsystem der Wii sind nur 4 Kanäle definiert.
  - `BridgeWheelController` implementiert `GetChannel() const override { return slotId; }` mit Werten `0..3`.
  - Die erweiterten Holder allein beweisen nicht, dass sämtliche Typ-/Kanalzugriffe korrekt behandelt werden. Neben Kanälen ab 4 ist insbesondere eine Verwechslung der Bridge-IDs mit den gleichzeitig belegten nativen Kanälen 0–3 zu prüfen. Native Metadatenfunktionen und alle relevanten Controller-Aufrufpfade benötigen dafür konkrete Befunde.
  - *Aktualisierung:* Der Originalcode-Abgleich hat identische native IDs sowie MAC-Abfragen am falschen nativen Kanal bestätigt. Bridge-Metadaten werden deshalb explizit mit logischen Proxy-Adressen gefüllt; Join verwendet private IDs und nur UI-Ausgaben Darstellungs-IDs. Für Bridge-Geräte wird kein nativer Lautsprecher ausgewählt. Der kombinierte Laptop-Lauf bleibt ein eigener Nachweis.
  - *Zu prüfen:* Ruft das Spiel bei Items oder Hindernissen Force-Feedback / Rumble auf? Die Rückkopplung ist aktuell als Dummy implementiert; zukünftige Erweiterungen können Rumble über die Mailbox-Statusbytes zurück an den ESP32 melden.

---

## 3. Empfohlene Prüfreihenfolge für den nächsten Agenten

1. **Manueller Haptik- & Fahrtest mit physischen Wiimotes:**
   - Skript starten: `python tools/run_live_bridge.py --port COM3`
   - Wiimote einschalten und mit ESP32 koppeln (LED 1 leuchtet dauerhaft).
   - Menünavigation, Nullpunkt und Fahrgefühl (Driften, Wheelie/Schütteln, Items) verifizieren.
2. **Signalqualitätsprüfung des ESP32 UART:**
   - Mit `python tools/test_live_bridge.py --bridge --seconds 60` die Zähler `invalid_frames`, `discarded_bytes` und `rejected_count` nach längerer Fahrt analysieren.
3. **Laptop-Deployment-Vorbereitung:**
   - Git-Repository auf Ziel-Laptop klonen: `git clone <repo>`
   - 4 Wiimotes mit Dolphin intern koppeln (GC/Wiimote-Ports 1–4).
   - ESP32 an USB anschließen und die übrigen 4 Wiimotes verbinden.
   - 60-FPS-Stabilität und Audioausgabe auf dem Laptop-Grafikchip prüfen.
