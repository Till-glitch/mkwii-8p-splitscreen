// SPDX-License-Identifier: GPL-3.0-or-later
// Sensor calibration/normalisation adapted from the user's 8 Player MK reference.
#ifndef SS8_WII_INPUT_MODEL_H
#define SS8_WII_INPUT_MODEL_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "../../../shared/wii_bridge_protocol.h"

namespace WiiBridgeFirmware {

static const size_t kSlots = 4;
static const size_t kEventCapacity = 32;
static const uint32_t kSensorTimeoutMs = 250;
static const uint32_t kTrickHoldMs = 100;

inline bool After(uint32_t a, uint32_t b) {
    return static_cast<int32_t>(a - b) > 0;
}

inline int ClampSensor(int value) {
    return value < -512 ? -512 : value > 511 ? 511 : value;
}

// Factory EEPROM blocks at 0x16 and 0x20: zero-g[4], one-g[4], flags, checksum.
inline bool ReadCalibration(const uint8_t* block, int* zero, int* span) {
    uint8_t sum = 0x55;
    for (size_t i = 0; i < 9; ++i) sum = static_cast<uint8_t>(sum + block[i]);
    if (sum != block[9]) return false;
    int candidateZero[3], candidateSpan[3];
    for (size_t i = 0; i < 3; ++i) {
        const unsigned shift = 4 - i * 2;
        const int base = (block[i] << 2) | ((block[3] >> shift) & 3);
        const int one = (block[4 + i] << 2) | ((block[7] >> shift) & 3);
        if (one - base < 40 || one - base > 250) return false;
        candidateZero[i] = base;
        candidateSpan[i] = one - base;
    }
    memcpy(zero, candidateZero, sizeof(candidateZero));
    memcpy(span, candidateSpan, sizeof(candidateSpan));
    return true;
}

inline int NormaliseSensor(int raw, int zero, int span) {
    int value = (raw - zero) * 128;
    // Same symmetric nearest-integer transport conversion as the reference.
    value += value < 0 ? -span / 2 : span / 2;
    return ClampSensor(value / span);
}

struct EventQueue {
    WiiBridgeProtocol::InputEvent records[kEventCapacity];
    size_t head;
    size_t count;

    void Clear() { head = count = 0; }

    bool Push(const WiiBridgeProtocol::InputEvent& event) {
        if (count == kEventCapacity) return false;
        records[(head + count) % kEventCapacity] = event;
        ++count;
        return true;
    }

    // Reject an ACK beyond the last event actually generated on this device.
    void Acknowledge(uint32_t sequence, uint32_t lastGenerated) {
        if (After(sequence, lastGenerated)) return;
        while (count && !After(records[head].eventSequence, sequence)) {
            head = (head + 1) % kEventCapacity;
            --count;
        }
    }

    size_t Copy(WiiBridgeProtocol::InputEvent* output, size_t capacity) const {
        const size_t copied = count < capacity ? count : capacity;
        for (size_t i = 0; i < copied; ++i) output[i] = records[(head + i) % kEventCapacity];
        return copied;
    }
};

struct RemoteSample {
    int raw[3];
    int zero[3];
    int span[3];
    uint16_t buttons;
    uint16_t previousButtons;
    uint32_t receivedAt;
    uint32_t sampleSequence;
    uint32_t lastEventSequence;
    uint32_t trickUntil;
    int32_t previousMagnitude;
    bool valid;
    bool calibrated;
    bool needBackup;
    bool hasButtonBaseline;
    bool haveMagnitude;
    bool eventOverflow;
    EventQueue events;

    void ResetInput() {
        // Keep sequences monotonic across reconnects during the same boot.
        const uint32_t savedSampleSequence = sampleSequence;
        const uint32_t savedEventSequence = lastEventSequence;
        memset(this, 0, sizeof(*this));
        sampleSequence = savedSampleSequence;
        lastEventSequence = savedEventSequence;
        for (size_t axis = 0; axis < 3; ++axis) {
            zero[axis] = 512;
            span[axis] = 104;
        }
    }

    bool Fresh(uint32_t now) const {
        return valid && calibrated && !eventOverflow && now - receivedAt <= kSensorTimeoutMs;
    }

    void PushEvent(uint8_t slotId, uint8_t kind, uint16_t value, uint32_t now) {
        if (eventOverflow) return;
        WiiBridgeProtocol::InputEvent event = {};
        event.slotId = slotId;
        event.eventKind = kind;
        event.value = value;
        event.eventSequence = ++lastEventSequence;
        event.sampleSequence = sampleSequence;
        event.sampleTimeMs = now;
        if (!events.Push(event)) {
            // Fail neutral until reconnect; never replay a delayed partial burst.
            eventOverflow = true;
            events.Clear();
        }
    }

    void Acknowledge(uint32_t sequence) {
        events.Acknowledge(sequence, lastEventSequence);
        // An explicit tail ACK plus released physical buttons is a safe resync.
        // This also recovers after connecting the host later than the Wiimotes.
        if (eventOverflow && sequence == lastEventSequence && buttons == 0) {
            eventOverflow = false;
            hasButtonBaseline = false;
            haveMagnitude = false;
        }
    }

    void ReadReport(uint8_t slotId, const uint8_t* report, uint32_t now) {
        buttons = static_cast<uint16_t>((report[2] & 0x9f) << 8) | (report[1] & 0x1f);
        raw[0] = (report[3] << 2) | ((report[1] >> 5) & 3);
        raw[1] = (report[4] << 2) | ((report[2] >> 4) & 2);
        raw[2] = (report[5] << 2) | ((report[2] >> 5) & 2);
        receivedAt = now;
        ++sampleSequence;
        valid = true;
        if (calibrated && !eventOverflow && (!hasButtonBaseline || buttons != previousButtons)) {
            PushEvent(slotId, WiiBridgeProtocol::BUTTONS, buttons, now);
            previousButtons = buttons;
            hasButtonBaseline = true;
        }
    }

    // Run at 60 Hz, independently of UART availability, as in the accepted reference.
    void ServiceTrick(uint8_t slotId, uint32_t now) {
        if (!Fresh(now)) {
            haveMagnitude = false;
            trickUntil = now;
            events.Clear();
            hasButtonBaseline = false;
            return;
        }
        if (events.count && now - events.records[events.head].sampleTimeMs > kSensorTimeoutMs) {
            eventOverflow = true;
            events.Clear();
            hasButtonBaseline = false;
            haveMagnitude = false;
            trickUntil = now;
            return;
        }
        int32_t magnitude = 0;
        for (size_t axis = 0; axis < 3; ++axis) {
            const int32_t value = raw[axis] - zero[axis];
            magnitude += value * value;
        }
        int32_t difference = magnitude - previousMagnitude;
        if (difference < 0) difference = -difference;
        if (haveMagnitude && difference > 6500) {
            if (!After(trickUntil, now)) PushEvent(slotId, WiiBridgeProtocol::TRICK, 1, now);
            trickUntil = now + kTrickHoldMs;
        }
        previousMagnitude = magnitude;
        haveMagnitude = true;
    }

    WiiBridgeProtocol::SnapshotSlot Snapshot(uint8_t slotId, bool connected, uint32_t now) const {
        WiiBridgeProtocol::SnapshotSlot out = {};
        out.slotId = slotId;
        if (connected) out.flags |= WiiBridgeProtocol::FLAG_CONNECTED;
        if (calibrated) out.flags |= WiiBridgeProtocol::FLAG_CALIBRATED;
        if (eventOverflow) out.flags |= WiiBridgeProtocol::FLAG_EVENT_OVERFLOW;
        const uint32_t age = valid ? now - receivedAt : 0xffffffffu;
        out.sampleAgeMs = age > 65535 ? 65535 : static_cast<uint16_t>(age);
        out.sampleSequence = sampleSequence;
        out.lastEventSequence = lastEventSequence;
        if (connected && Fresh(now)) {
            out.flags |= WiiBridgeProtocol::FLAG_SAMPLE_VALID;
            out.buttons = buttons;
            // PAL read_kpad_acc coordinates. Clamp after sign inversion too.
            out.accelX = ClampSensor(-NormaliseSensor(raw[0], zero[0], span[0]));
            out.accelY = ClampSensor(-NormaliseSensor(raw[2], zero[2], span[2]));
            out.accelZ = NormaliseSensor(raw[1], zero[1], span[1]);
            if (After(trickUntil, now)) out.eventFlags |= WiiBridgeProtocol::EVENT_FLAG_TRICK;
        }
        return out;
    }
};

}  // namespace WiiBridgeFirmware
#endif
