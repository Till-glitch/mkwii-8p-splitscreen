// SPDX-License-Identifier: GPL-3.0-or-later
// Based on the user's working 8 Player MK ESP32 input reference; no renderer code.
#include <Arduino.h>
#include <Bluepad32.h>
#include <Preferences.h>
#include <esp_system.h>
#include "wii_input_model.h"
#include "wii_slot_reservations.h"
extern "C" {
#include <uni_hid_device.h>
#include <parser/uni_hid_parser_wii.h>
#include <bt/uni_bt_allowlist.h>
}

#if !defined(CONFIG_IDF_TARGET_ESP32)
#error "Wii Remotes require the original ESP32 with Bluetooth Classic (BR/EDR)."
#endif

#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

using namespace WiiBridgeFirmware;
namespace Protocol = WiiBridgeProtocol;

static const uint8_t kBootButton = 0;
static const uint32_t kPairingMs = 60000;
static const uint32_t kClearSlotsHoldMs = 4000;
static const size_t kTxBufferSize = 256;
static const size_t kEventsPerFrame = 4;

static ControllerPtr controllers[kSlots] = {};
static uni_hid_device_t* devices[kSlots] = {};
static report_parse_input_report_fn_t originalParsers[kSlots] = {};
static RemoteSample samples[kSlots] = {};
static uint8_t calibrationAttempts[kSlots] = {};
static uint32_t calibrationDeadline[kSlots] = {};
static uint8_t slotAddresses[kSlots][6] = {};
static bool reserved[kSlots] = {};
static portMUX_TYPE sampleLock = portMUX_INITIALIZER_UNLOCKED;
static Preferences preferences;
static bool preferencesReady = false;
static bool pairing = false;
static uint32_t pairingDeadline = 0;
static bool metadataDirty = true;
static uint32_t bootSession;
static uint32_t transportSequence = 0;

static bool NonzeroAddress(const uint8_t* address) {
    return ValidReservationAddress(address);
}

static bool StoreReservations(const unsigned char* data, unsigned int size) {
    return preferencesReady && preferences.putBytes("slots", data, size) == size;
}

static void RestoreReservations() {
    preferencesReady = preferences.begin("ss8-wheels", false);
    if (!preferencesReady || preferences.getBytesLength("slots") != sizeof(slotAddresses)) return;
    preferences.getBytes("slots", slotAddresses, sizeof(slotAddresses));
    for (size_t i = 0; i < kSlots; ++i) {
        reserved[i] = NonzeroAddress(slotAddresses[i]);
        for (size_t earlier = 0; earlier < i; ++earlier)
            if (reserved[i] && reserved[earlier] && !memcmp(slotAddresses[i], slotAddresses[earlier], 6)) {
                reserved[i] = false;
                memset(slotAddresses[i], 0, 6);
            }
    }
}

static void ApplyAllowlist() {
    uni_bt_allowlist_set_enabled(false);
    uni_bt_allowlist_remove_all();
    for (size_t i = 0; i < kSlots; ++i)
        if (reserved[i]) uni_bt_allowlist_add_addr(slotAddresses[i]);
    uni_bt_allowlist_set_enabled(!pairing);
}

static void SetPairing(bool enabled) {
    pairing = enabled;
    pairingDeadline = millis() + kPairingMs;
    ApplyAllowlist();
    BP32.enableNewBluetoothConnections(enabled);
}

static void RequestCalibration(uni_hid_device_t* device, uint8_t address) {
    const uint8_t request[] = {0xa2, 0x17, 0, 0, 0, address, 0, 10};
    uni_hid_device_send_intr_report(device, request, sizeof(request));
}

static void ParseReport(uni_hid_device_t* device, const uint8_t* report, uint16_t length) {
    int slot = -1;
    report_parse_input_report_fn_t original = nullptr;
    bool calibrationReply = false;
    const uint32_t now = millis();
    portENTER_CRITICAL(&sampleLock);
    for (size_t i = 0; i < kSlots; ++i)
        if (devices[i] == device) { slot = i; original = originalParsers[i]; break; }
    if (slot >= 0) {
        RemoteSample& sample = samples[slot];
        if (length >= 6 && report[0] == 0x31) sample.ReadReport(slot, report, now);
        // Consume only the two EEPROM replies requested by this firmware.
        calibrationReply = length >= 6 && report[0] == 0x21 && report[4] == 0 &&
                           (report[5] == 0x16 || report[5] == 0x20);
        if (calibrationReply) {
            int zero[3], span[3];
            const bool valid = length >= 16 && !(report[3] & 15) &&
                (report[3] >> 4) + 1 >= 10 && ReadCalibration(report + 6, zero, span);
            if (valid) {
                memcpy(sample.zero, zero, sizeof(zero));
                memcpy(sample.span, span, sizeof(span));
                sample.calibrated = true;
                sample.hasButtonBaseline = false;
            } else if (report[5] == 0x16) sample.needBackup = true;
        }
    }
    portEXIT_CRITICAL(&sampleLock);
    if (original && !calibrationReply) original(device, report, length);
}

static void OnConnected(ControllerPtr controller) {
    if (controller->getProperties().type != Controller::CONTROLLER_TYPE_WiiController) {
        controller->disconnect();
        return;
    }
    uni_hid_device_t* device = uni_hid_device_get_instance_for_idx(controller->index());
    if (!device) { controller->disconnect(); return; }
    const ControllerProperties properties = controller->getProperties();
    const uint8_t* address = properties.btaddr;
    if (!NonzeroAddress(address)) { controller->disconnect(); return; }
    bool active[kSlots];
    for (size_t i = 0; i < kSlots; ++i) active[i] = controllers[i] != nullptr;
    const int slot = SelectReservationSlot(slotAddresses, active, address, pairing);
    if (slot < 0 || controllers[slot]) { controller->disconnect(); return; }
    const bool changed = !SameReservationAddress(slotAddresses[slot], address);
    if (!CommitReservation(slotAddresses, slot, address, StoreReservations)) {
        controller->disconnect();
        return;
    }
    reserved[slot] = true;
    if (changed) ApplyAllowlist();
    portENTER_CRITICAL(&sampleLock);
    samples[slot].ResetInput();
    calibrationAttempts[slot] = 1;
    calibrationDeadline[slot] = millis() + 750;
    controllers[slot] = controller;
    devices[slot] = device;
    originalParsers[slot] = device->report_parser.parse_input_report;
    device->report_parser.parse_input_report = ParseReport;
    portEXIT_CRITICAL(&sampleLock);
    uni_hid_parser_wii_set_mode(device, WII_MODE_ACCEL);
    const uint8_t reportMode[] = {0xa2, 0x12, 0x04, 0x31};
    uni_hid_device_send_intr_report(device, reportMode, sizeof(reportMode));
    RequestCalibration(device, 0x16);
    // Preserve the reference's empirically selected LEDs, local to the extra group.
    static const uint8_t playerLeds[kSlots] = {2, 1, 4, 8};
    static const uint8_t rawLeds[kSlots] = {0x20, 0x10, 0x40, 0x80};
    controller->setPlayerLEDs(playerLeds[slot]);
    const uint8_t ledReport[] = {0xa2, 0x11, rawLeds[slot]};
    uni_hid_device_send_intr_report(device, ledReport, sizeof(ledReport));
    metadataDirty = true;
    bool full = true;
    for (size_t i = 0; i < kSlots; ++i) full &= controllers[i] != nullptr;
    if (full) SetPairing(false);
    else if (pairing) pairingDeadline = millis() + kPairingMs;
}

static void OnDisconnected(ControllerPtr controller) {
    portENTER_CRITICAL(&sampleLock);
    for (size_t i = 0; i < kSlots; ++i) if (controllers[i] == controller) {
        if (devices[i]) devices[i]->report_parser.parse_input_report = originalParsers[i];
        controllers[i] = nullptr;
        devices[i] = nullptr;
        originalParsers[i] = nullptr;
        samples[i].ResetInput();
        calibrationAttempts[i] = 0;
    }
    portEXIT_CRITICAL(&sampleLock);
    metadataDirty = true;
}

static void ServiceButton() {
    static bool previous = false;
    static bool clearHandled = false;
    static uint32_t pressedAt = 0;
    const uint32_t now = millis();
    const bool pressed = digitalRead(kBootButton) == LOW;
    if (pressed && !previous) { pressedAt = now; clearHandled = false; }
    if (pressed && !clearHandled && now - pressedAt >= kClearSlotsHoldMs) {
        bool anyConnected = false;
        for (size_t i = 0; i < kSlots; ++i) anyConnected |= controllers[i] != nullptr;
        if (!anyConnected && preferencesReady) {
            // Physical deliberate action, only when no player's controller is active.
            preferences.remove("slots");
            uni_bt_allowlist_remove_all();
            ESP.restart();
        }
        clearHandled = true;
    }
    if (!pressed && previous && !clearHandled && now - pressedAt >= 50) SetPairing(!pairing);
    previous = pressed;
    if (pairing && !After(pairingDeadline, now)) SetPairing(false);
    bool anyConnected = false;
    for (size_t i = 0; i < kSlots; ++i) anyConnected |= controllers[i] != nullptr;
    digitalWrite(LED_BUILTIN, pairing ? (now / 200) % 2 : anyConnected);
}

// No serial text is emitted by this sketch; Bluepad/boot diagnostics are tolerated
// by the host's bounded magic/CRC resynchronisation.
static bool SendFrame(const uint8_t* frame, size_t length) {
    // Keep at most one small frame's worth of UART backlog; never wait for space.
    if (!length || Serial.availableForWrite() < static_cast<int>(length) ||
        Serial.availableForWrite() < static_cast<int>(kTxBufferSize - 96)) return false;
    return Serial.write(frame, length) == length;
}

static void ServiceAck() {
    static uint8_t buffer[160];
    static size_t used = 0;
    unsigned processed = 0;
    while (Serial.available() && processed++ < 160) {
        const uint8_t byte = static_cast<uint8_t>(Serial.read());
        if (used == sizeof(buffer)) { memmove(buffer, buffer + 1, --used); }
        buffer[used++] = byte;
        while (used >= 2) {
            if (buffer[0] != 'W' || buffer[1] != '3') { memmove(buffer, buffer + 1, --used); continue; }
            if (used < 18) break;
            const size_t payload = (static_cast<size_t>(buffer[4]) << 8) | buffer[5];
            const size_t total = 18 + payload + 2;
            if (buffer[2] != 1 || buffer[3] != Protocol::ACK || total > sizeof(buffer)) {
                memmove(buffer, buffer + 1, --used);
                continue;
            }
            if (used < total) break;
            Protocol::FrameView view;
            Protocol::EventAck acknowledgements[kSlots];
            size_t count = 0;
            if (Protocol::DecodeFrame(buffer, total, view) && view.header.bootSession == bootSession &&
                Protocol::DecodeAck(view, acknowledgements, kSlots, count)) {
                portENTER_CRITICAL(&sampleLock);
                for (size_t i = 0; i < count; ++i) {
                    RemoteSample& sample = samples[acknowledgements[i].slotId];
                    sample.Acknowledge(acknowledgements[i].ackedEventSequence);
                }
                portEXIT_CRITICAL(&sampleLock);
                used -= total;
                memmove(buffer, buffer + total, used);
            } else memmove(buffer, buffer + 1, --used);
        }
    }
}

static void ServiceInput() {
    static uint32_t deadline = 0;
    const uint32_t nowUs = micros();
    if (static_cast<int32_t>(nowUs - deadline) < 0) return;
    deadline = nowUs + 16667;
    const uint32_t now = millis();
    uni_hid_device_t* calibrationRequests[kSlots] = {};
    uint8_t calibrationAddresses[kSlots] = {};
    portENTER_CRITICAL(&sampleLock);
    for (size_t i = 0; i < kSlots; ++i) {
        samples[i].ServiceTrick(i, now);
        if (!samples[i].calibrated && devices[i] && calibrationAttempts[i] < 4 &&
            (samples[i].needBackup || !After(calibrationDeadline[i], now))) {
            calibrationAddresses[i] = samples[i].needBackup || (calibrationAttempts[i] & 1) ? 0x20 : 0x16;
            samples[i].needBackup = false;
            calibrationRequests[i] = devices[i];
            ++calibrationAttempts[i];
            calibrationDeadline[i] = now + 750;
        }
    }
    portEXIT_CRITICAL(&sampleLock);
    for (size_t i = 0; i < kSlots; ++i)
        if (calibrationRequests[i]) RequestCalibration(calibrationRequests[i], calibrationAddresses[i]);
}

static void ServiceTransport() {
    static uint32_t nextSnapshotUs = 0;
    static uint32_t nextEventUs = 0;
    static uint32_t nextMetadataMs = 0;
    static size_t nextEventSlot = 0;
    uint8_t frame[148];
    const uint32_t nowUs = micros();
    const uint32_t now = millis();
    if (static_cast<int32_t>(nowUs - nextSnapshotUs) >= 0) {
        Protocol::SnapshotSlot snapshot[kSlots];
        portENTER_CRITICAL(&sampleLock);
        for (size_t i = 0; i < kSlots; ++i) snapshot[i] = samples[i].Snapshot(i, controllers[i] != nullptr, now);
        portEXIT_CRITICAL(&sampleLock);
        const size_t length = Protocol::EncodeSnapshot(frame, sizeof(frame), bootSession,
            transportSequence + 1, now, snapshot, kSlots);
        if (SendFrame(frame, length)) { ++transportSequence; nextSnapshotUs = nowUs + 16667; }
    }
    if (static_cast<int32_t>(nowUs - nextEventUs) >= 0) {
        Protocol::InputEvent batch[kEventsPerFrame];
        size_t count = 0;
        portENTER_CRITICAL(&sampleLock);
        // Round-robin sources; within a source, always resend the oldest unacked events.
        for (size_t attempt = 0; attempt < kSlots; ++attempt) {
            const size_t slot = (nextEventSlot + attempt) % kSlots;
            if (devices[slot] && samples[slot].Fresh(now))
                count = samples[slot].events.Copy(batch, kEventsPerFrame);
            if (count) { nextEventSlot = (slot + 1) % kSlots; break; }
        }
        portEXIT_CRITICAL(&sampleLock);
        if (count) {
            const size_t length = Protocol::EncodeEvents(frame, sizeof(frame), bootSession,
                transportSequence + 1, now, batch, count);
            if (SendFrame(frame, length)) { ++transportSequence; nextEventUs = nowUs + 16667; }
        } else nextEventUs = nowUs + 16667;
    }
    if (metadataDirty || static_cast<int32_t>(now - nextMetadataMs) >= 0) {
        Protocol::DeviceRecord records[kSlots] = {};
        for (size_t i = 0; i < kSlots; ++i) {
            records[i].slotId = i;
            if (reserved[i]) {
                records[i].flags = Protocol::DEVICE_PRESENT;
                memcpy(records[i].mac, slotAddresses[i], 6);
            }
        }
        const size_t length = Protocol::EncodeDevices(frame, sizeof(frame), bootSession,
            transportSequence + 1, now, records, kSlots);
        if (SendFrame(frame, length)) { ++transportSequence; metadataDirty = false; nextMetadataMs = now + 1000; }
    }
}

void setup() {
    Serial.setTxBufferSize(kTxBufferSize);
    Serial.begin(115200);
    pinMode(kBootButton, INPUT_PULLUP);
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
    bootSession = esp_random();
    if (!bootSession) bootSession = 1;
    for (size_t i = 0; i < kSlots; ++i) samples[i].ResetInput();
    RestoreReservations();
    BP32.setup(&OnConnected, &OnDisconnected);
    SetPairing(false);
}

void loop() {
    BP32.update();
    ServiceButton();
    ServiceAck();
    ServiceInput();
    ServiceTransport();
    yield();
}
