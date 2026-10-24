#ifndef SS8_WHEEL_BRIDGE_MAILBOX_H
#define SS8_WHEEL_BRIDGE_MAILBOX_H

// GPL-3.0-or-later. Portable, allocation-free diagnostic receiver. This ABI
// deliberately does not advertise gameplay/controller support yet.
#include "wii_bridge_protocol.h"

namespace WiiBridgeMailbox {
using namespace WiiBridgeProtocol;

enum {
    ABI_VERSION = 1, DESCRIPTOR_SIZE = 64, INPUT_SIZE = 640, STATUS_SIZE = 96,
    MAX_EVENTS = 32, CAP_DIAGNOSTIC = 1, CAP_WHEEL_INPUT = 2,
    STATUS_READY = 1, STATUS_APPLIED = 2, STATUS_TIMEOUT = 4, STATUS_PROTOCOL_ERROR = 8,
    ERROR_NONE = 0, ERROR_SESSION = 1, ERROR_CRC = 2, ERROR_SHAPE = 3,
    ERROR_SEQUENCE = 4, ERROR_EVENT = 5, TIMEOUT_MS = 250
};

inline uint32_t Crc32Part(uint32_t crc, const uint8_t* data, unsigned int length) {
    for (unsigned int i = 0; i < length; ++i) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320U : 0);
    }
    return crc;
}
inline uint32_t Crc32(const uint8_t* data, unsigned int length) {
    return Crc32Part(0xffffffffU, data, length) ^ 0xffffffffU;
}
inline uint32_t InputCrc(const uint8_t* input) {
    return Crc32Part(Crc32Part(0xffffffffU, input + 4, 24), input + 32, INPUT_SIZE - 32) ^ 0xffffffffU;
}
inline bool Newer(uint32_t value, uint32_t previous) {
    const uint32_t difference = value - previous;
    return difference != 0 && difference < 0x80000000U;
}
inline void Clear(uint8_t* bytes, unsigned int length) {
    for (unsigned int i = 0; i < length; ++i) bytes[i] = 0;
}

struct Receiver {
    uint32_t guestSession, guestTick, hostSession, publishSequence, sourceSession;
    uint32_t flags, lastError, accepted, rejected, lastPublishAtMs, ageTicks;
    uint32_t eventAck[4], sampleSequence[4], sampleSeenAtMs[4], sampleAgeMs[4];
    bool active, hasSample[4], hasEventAck[4];
    SnapshotSlot slots[4];

    void NeutralSlot(unsigned int index) {
        slots[index].flags = 0;
        slots[index].buttons = 0;
        slots[index].accelX = slots[index].accelY = slots[index].accelZ = 0;
        slots[index].eventFlags = 0;
    }
    void Reset(uint32_t session) {
        guestSession = session;
        guestTick = hostSession = publishSequence = sourceSession = 0;
        flags = STATUS_READY; lastError = accepted = rejected = lastPublishAtMs = ageTicks = 0;
        active = false;
        for (unsigned int i = 0; i < 4; ++i) {
            eventAck[i] = sampleSequence[i] = sampleSeenAtMs[i] = sampleAgeMs[i] = 0;
            hasSample[i] = hasEventAck[i] = false;
            slots[i].slotId = uint8_t(i);
            slots[i].sampleAgeMs = 0xffff;
            slots[i].sampleSequence = slots[i].lastEventSequence = 0;
            NeutralSlot(i);
        }
    }
    bool Fail(uint32_t error) {
        lastError = error; ++rejected; flags |= STATUS_PROTOCOL_ERROR;
        return false;
    }
    bool Accept(const uint8_t* input, uint32_t nowMs) {
        if (!Read32(input) || (Read32(input) & 1)) return Fail(ERROR_SHAPE);
        if (Read32(input + 4) != guestSession || !Read32(input + 8) || !Read32(input + 16))
            return Fail(ERROR_SESSION);
        if (Read32(input + 28) != InputCrc(input)) return Fail(ERROR_CRC);
        const uint16_t count = Read16(input + 24);
        if (Read16(input + 26) != 4 || count > MAX_EVENTS) return Fail(ERROR_SHAPE);
        FrameView view;
        view.header.kind = SNAPSHOT;
        view.header.payloadLength = 4 * SNAPSHOT_RECORD_SIZE;
        view.payload = input + 32;
        if (!ValidPayload(view)) return Fail(ERROR_SHAPE);
        if (count) {
            view.header.kind = EVENTS;
            view.header.payloadLength = count * EVENT_RECORD_SIZE;
            view.payload = input + 128;
            if (!ValidPayload(view)) return Fail(ERROR_EVENT);
        }
        for (unsigned int i = 128 + count * EVENT_RECORD_SIZE; i < INPUT_SIZE; ++i)
            if (input[i]) return Fail(ERROR_SHAPE);

        const uint32_t nextHost = Read32(input + 8), nextPublish = Read32(input + 12);
        const uint32_t nextSource = Read32(input + 16);
        const bool newSession = !active || nextHost != hostSession || nextSource != sourceSession;
        if (!newSession && !Newer(nextPublish, publishSequence)) return Fail(ERROR_SEQUENCE);

        // Validate all events before changing any accepted state or acknowledgements.
        uint32_t nextAck[4]; bool nextHasAck[4];
        for (unsigned int i = 0; i < 4; ++i) {
            nextAck[i] = newSession ? 0 : eventAck[i];
            nextHasAck[i] = !newSession && hasEventAck[i];
        }
        for (unsigned int i = 0; i < count; ++i) {
            const InputEvent event = ReadEvent(input + 128 + i * EVENT_RECORD_SIZE);
            const unsigned int slot = event.slotId;
            if (nextHasAck[slot] && event.eventSequence != nextAck[slot] &&
                Newer(event.eventSequence, nextAck[slot]) && event.eventSequence != nextAck[slot] + 1)
                return Fail(ERROR_EVENT);
            if (!nextHasAck[slot] || Newer(event.eventSequence, nextAck[slot])) {
                nextAck[slot] = event.eventSequence; nextHasAck[slot] = true;
            }
        }

        for (unsigned int i = 0; i < 4; ++i) {
            const SnapshotSlot sample = ReadSnapshot(input + 32 + i * SNAPSHOT_RECORD_SIZE);
            if (sample.slotId != i) return Fail(ERROR_SHAPE);
            if (!newSession && hasSample[i] && sample.sampleSequence != sampleSequence[i] &&
                !Newer(sample.sampleSequence, sampleSequence[i])) return Fail(ERROR_SEQUENCE);
        }
        for (unsigned int i = 0; i < 4; ++i) {
            const SnapshotSlot sample = ReadSnapshot(input + 32 + i * SNAPSHOT_RECORD_SIZE);
            const bool disconnected = (sample.flags & (FLAG_CONNECTED | FLAG_SAMPLE_VALID)) !=
                                      (FLAG_CONNECTED | FLAG_SAMPLE_VALID) || (sample.flags & FLAG_EVENT_OVERFLOW);
            if (newSession || !hasSample[i] || sample.sampleSequence != sampleSequence[i]) {
                sampleSeenAtMs[i] = nowMs; sampleAgeMs[i] = sample.sampleAgeMs;
                sampleSequence[i] = sample.sampleSequence;
            } else {
                // Forwarded duplicates cannot reset the age of a radio sample.
                const uint32_t elapsedAge = sampleAgeMs[i] + uint32_t(nowMs - sampleSeenAtMs[i]);
                sampleAgeMs[i] = elapsedAge > sample.sampleAgeMs ? elapsedAge : sample.sampleAgeMs;
                sampleSeenAtMs[i] = nowMs;
            }
            hasSample[i] = !disconnected;
            slots[i] = sample;
            eventAck[i] = nextAck[i]; hasEventAck[i] = nextHasAck[i];
            if (disconnected) {
                NeutralSlot(i);
                // Drop stale events at the same explicit boundary as the host/firmware.
                eventAck[i] = sample.lastEventSequence; hasEventAck[i] = true;
            }
        }
        hostSession = nextHost; publishSequence = nextPublish; sourceSession = nextSource;
        active = true; lastPublishAtMs = nowMs; ageTicks = 0; ++accepted;
        flags = STATUS_READY | STATUS_APPLIED; lastError = ERROR_NONE;
        return true;
    }
    void Tick(uint32_t nowMs) {
        ++guestTick;
        if (ageTicks != 0xffffffffU) ++ageTicks;
        const bool hostTimedOut = !active || uint32_t(nowMs - lastPublishAtMs) >= TIMEOUT_MS;
        bool anyTimedOut = hostTimedOut;
        for (unsigned int i = 0; i < 4; ++i) {
            if (hostTimedOut || !hasSample[i] ||
                sampleAgeMs[i] + uint32_t(nowMs - sampleSeenAtMs[i]) >= TIMEOUT_MS) {
                NeutralSlot(i);
                if (hasSample[i]) anyTimedOut = true;
            }
        }
        if (anyTimedOut) flags |= STATUS_TIMEOUT;
    }
    void WriteStatus(uint8_t* status, uint32_t generation) const {
        Clear(status, STATUS_SIZE);
        Write32(status, generation);
        Write32(status + 4, guestSession); Write32(status + 8, guestTick);
        Write32(status + 12, hostSession); Write32(status + 16, publishSequence);
        Write32(status + 20, sourceSession); Write32(status + 24, flags);
        Write32(status + 28, lastError);
        for (unsigned int i = 0; i < 4; ++i) {
            Write32(status + 32 + i * 4, eventAck[i]);
            Write32(status + 48 + i * 4, sampleSequence[i]);
        }
        Write32(status + 64, 0); // Diagnostic mode owns no gameplay holders.
        Write32(status + 68, ageTicks); Write32(status + 72, accepted); Write32(status + 76, rejected);
        Write32(status + 92, Crc32(status + 4, 88));
    }
};

} // namespace WiiBridgeMailbox
#endif
