# Deep-Thinking Analyse & Review-Punkte für nachfolgende Agents

Dieses Dokument richtet sich an tiefer denkende Folge-Agents und Systemarchitekten. Es fasst die getroffenen Low-Level- und Architektur-Entscheidungen der ESP32-Wii-Bridge für den 8-Spieler-Splitscreen in Mario Kart Wii zusammen und definiert eine priorisierte Liste von Aspekten, die vor dem finalen Produktiveinsatz (insbesondere auf dem Ziel-Laptop mit 8 echten Wiimotes) einer tieferen Prüfung unterzogen werden sollten.

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
  - Snapshot pro Slot: 16 Bytes. 4 Slots = 64 Bytes Payload + 16 Bytes Frame-Header/CRC = ~80 Bytes pro W3-Frame.
  - Bei 60 Hz Update-Rate: $80 \times 60 = 4.800\text{ Bytes/s}$.
  - Serial-Overhead (8N1): 1 Startbit, 8 Datenbits, 1 Stopbit = 10 Bits pro Byte $\rightarrow 48.000\text{ Baud}$.
  - Bei 115.200 Baud liegt die nominale Auslastung bei ca. **42%**.
- **Spitzenlast durch Ereignisse (Shake / Gesten):**
  - Schüttel-Ereignisse (Stunts/Wheelies) erzeugen zusätzliche `EVENT`-Records (8 Bytes pro Event).
  - *Prüffrage:* Bei gleichzeitigem Schütteln von 4 Spielern kann die Datenrate kurzzeitig ansteigen.
  - *Empfehlung für den Agenten:* Prüfen, ob eine Erhöhung der UART-Baudrate auf **230.400** oder **460.800 Baud** auf dem ESP32 ([`firmware/esp32-wii-bridge/platformio.ini`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/firmware/esp32-wii-bridge/platformio.ini)) und im Host-Service ([`tools/wiimote_bridge/service.py`](file:///c:/Users/Till/Documents/mkwii-8p-splitscreen-esp32-support/tools/wiimote_bridge/service.py)) zusätzliche Latenzreserven schafft, ohne die Signalintegrität des USB-Serial-Wandlers (CP2102/CH340) zu beeinträchtigen.

---

### Fokus 3: Lenkungsphysik & Wheel-Kalibrierungsmatrix

- **Aktuelle Heuristik in `BridgeWheelController::UpdateImpl`:**
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
  - Mario Kart Wii verwendet im Originaltreiber (`WiiController::UpdateStatesCore` bei `0x8051fbe0`) eine nichtlineare Kalibrierungsfunktion mit Rollwinkelberechnung $\arctan2(X, Y)$ und Glättung, um Gravitationseinflüsse bei Neigung der Fernbedienung herauszurechnen.
  - Die aktuelle Implementierung projiziert rein die Rohachse $X$ mit linearer Skalierung (`/ 100.0f`) auf 15 diskrete Stufen (`0..14`).
  - *Aufgabe:* Im manuellen Fahrtest das Ansprechverhalten und den Nullpunkt bei waagerechter Haltung bewerten. Falls das Einlenken zu giftig oder zu träge wirkt: Formel auf echten Rollwinkel $\theta = \operatorname{atan2}(a_x, a_y)$ erweitern.

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
- Das Endziel des Gesamtsystems ist der Einsatz unter **Retro Rewind 6 (RR6)**:
  - *Unterschiede:* RR6 nutzt MEM2 intensiv für Custom Tracks (Szs), Custom Characters und zusätzliche Sounds.
  - `WheelBridge` belegt ca. 1.200 Bytes in MEM1 (BSS).
  - *Prüfaufgabe:* Bei Übergang auf das volle RR6-Profil (`build_code.py --wheel-bridge` ohne `--vanilla`) prüfen, ob die Linker-Symbole und Speicherheaps mit den erweiterten Pulsar-Heaps harmonieren.

---

### Fokus 7: Dolphin Controller-Sicherheit & WPAD Kanal-Grenzen

- **WPAD Kanal-Grenzen (`WPAD_CHAN_0` .. `WPAD_CHAN_3`):**
  - Im originalen RVL-WPAD-Subsystem der Wii sind nur 4 Kanäle definiert.
  - `BridgeWheelController` implementiert `GetChannel() const override { return slotId; }` mit Werten `0..3`.
  - Da Spieler 5–8 über Holders `4..7` angebunden sind, fängt Pulsar alle Zugriffe ab, sodass kein unberechtigter Aufruf an `WPADControlSpeaker` oder `WPADProbe` für Kanäle $\ge 4$ im Wii-Systemtreiber erfolgt.
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
