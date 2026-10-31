#ifndef SS8_WHEEL_BRIDGE_MAILBOX_H
#define SS8_WHEEL_BRIDGE_MAILBOX_H

// GPL-3.0-or-later. Portable, allocation-free receiver. Reset defaults to the
// diagnostic consumer; gameplay explicitly opts in to tick-paced event delivery.
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
    bool gameplayMode, neutralPending[4], actionFresh[4];
    uint16_t actionButtons[4];
    uint8_t actionTrick[4];
    uint32_t actionTick[4], pendingCount, pendingSeenAtMs[MAX_EVENTS];
    InputEvent pendingEvents[MAX_EVENTS];

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
        gameplayMode = false; pendingCount = 0;
        for (unsigned int i = 0; i < 4; ++i) {
            eventAck[i] = sampleSequence[i] = sampleSeenAtMs[i] = sampleAgeMs[i] = 0;
            hasSample[i] = hasEventAck[i] = false;
            slots[i].slotId = uint8_t(i);
            slots[i].sampleAgeMs = 0xffff;
            slots[i].sampleSequence = slots[i].lastEventSequence = 0;
            neutralPending[i] = true; actionFresh[i] = false;
            actionButtons[i] = 0; actionTrick[i] = 0; actionTick[i] = 0xffffffffU;
            NeutralSlot(i);
        }
    }
    void SetGameplayMode(bool enabled) {
        gameplayMode = enabled;
        for (unsigned int i = 0; i < 4; ++i) {
            if (active) {
                // Mode switches are neutral discard boundaries, and must not
                // rewind an ACK if events are newer than the sensor snapshot.
                DropSlotActions(i);
                continue;
            }
            neutralPending[i] = true; actionFresh[i] = false;
            actionButtons[i] = 0; actionTrick[i] = 0; actionTick[i] = 0xffffffffU;
        }
        pendingCount = 0;
    }
    bool GameplaySlotValid(unsigned int index) const {
        const unsigned int required = FLAG_CONNECTED | FLAG_CALIBRATED | FLAG_SAMPLE_VALID;
        return active && hasSample[index] && (slots[index].flags & required) == required &&
               !(slots[index].flags & FLAG_EVENT_OVERFLOW);
    }
    void RemovePending(unsigned int index) {
        for (unsigned int i = index + 1; i < pendingCount; ++i) {
            pendingEvents[i - 1] = pendingEvents[i];
            pendingSeenAtMs[i - 1] = pendingSeenAtMs[i];
        }
        --pendingCount;
    }
    void DropSlotActions(unsigned int slot) {
        uint32_t boundary = eventAck[slot];
        bool hasBoundary = hasEventAck[slot];
        if (!hasBoundary || Newer(slots[slot].lastEventSequence, boundary)) {
            boundary = slots[slot].lastEventSequence; hasBoundary = true;
        }
        for (unsigned int i = 0; i < pendingCount;) {
            if (pendingEvents[i].slotId != slot) { ++i; continue; }
            if (!hasBoundary || Newer(pendingEvents[i].eventSequence, boundary)) {
                boundary = pendingEvents[i].eventSequence; hasBoundary = true;
            }
            RemovePending(i);
        }
        eventAck[slot] = boundary; hasEventAck[slot] = hasBoundary;
        actionButtons[slot] = 0; actionTrick[slot] = 0;
        actionFresh[slot] = false; neutralPending[slot] = true;
        actionTick[slot] = 0xffffffffU;
    }
    static bool SameEvent(const InputEvent& a, const InputEvent& b) {
        return a.slotId == b.slotId && a.eventKind == b.eventKind && a.value == b.value &&
               a.eventSequence == b.eventSequence && a.sampleSequence == b.sampleSequence &&
               a.sampleTimeMs == b.sampleTimeMs;
    }
    void ApplySample(unsigned int index, const SnapshotSlot& sample, bool newSession, uint32_t nowMs) {
        const bool disconnected = (sample.flags & (FLAG_CONNECTED | FLAG_SAMPLE_VALID)) !=
                                  (FLAG_CONNECTED | FLAG_SAMPLE_VALID) || (sample.flags & FLAG_EVENT_OVERFLOW);
        if (newSession || !hasSample[index] || sample.sampleSequence != sampleSequence[index]) {
            sampleSeenAtMs[index] = nowMs; sampleAgeMs[index] = sample.sampleAgeMs;
            sampleSequence[index] = sample.sampleSequence;
        } else {
            const uint32_t elapsedAge = sampleAgeMs[index] + uint32_t(nowMs - sampleSeenAtMs[index]);
            sampleAgeMs[index] = elapsedAge > sample.sampleAgeMs ? elapsedAge : sample.sampleAgeMs;
            sampleSeenAtMs[index] = nowMs;
        }
        hasSample[index] = !disconnected;
        slots[index] = sample;
        if (disconnected) NeutralSlot(index);
    }
    bool AcceptGameplay(const uint8_t* input, uint32_t nowMs, uint16_t count, bool newSession) {
        // Work on bounded local copies. No queue, ACK, sensor state or session
        // is committed until every event has passed validation.
        InputEvent nextEvents[MAX_EVENTS];
        uint32_t nextSeen[MAX_EVENTS], nextAck[4], lastKnown[4];
        bool nextHasAck[4], drop[4];
        unsigned int nextCount = 0;
        const unsigned int required = FLAG_CONNECTED | FLAG_CALIBRATED | FLAG_SAMPLE_VALID;
        for (unsigned int i = 0; i < 4; ++i) {
            const SnapshotSlot sample = ReadSnapshot(input + 32 + i * SNAPSHOT_RECORD_SIZE);
            drop[i] = newSession || (sample.flags & required) != required ||
                      (sample.flags & FLAG_EVENT_OVERFLOW) || sample.sampleAgeMs >= TIMEOUT_MS;
            nextAck[i] = newSession ? sample.lastEventSequence : eventAck[i];
            nextHasAck[i] = newSession || hasEventAck[i];
            if (drop[i] && (!nextHasAck[i] || Newer(sample.lastEventSequence, nextAck[i]))) {
                nextAck[i] = sample.lastEventSequence; nextHasAck[i] = true;
            }
        }
        if (!newSession) {
            for (unsigned int i = 0; i < pendingCount; ++i) {
                const InputEvent& previous = pendingEvents[i];
                const unsigned int slot = previous.slotId;
                if (drop[slot]) {
                    if (!nextHasAck[slot] || Newer(previous.eventSequence, nextAck[slot])) {
                        nextAck[slot] = previous.eventSequence; nextHasAck[slot] = true;
                    }
                } else {
                    nextEvents[nextCount] = previous;
                    nextSeen[nextCount++] = pendingSeenAtMs[i];
                }
            }
        }
        for (unsigned int i = 0; i < 4; ++i) lastKnown[i] = nextAck[i];
        for (unsigned int i = 0; i < nextCount; ++i)
            lastKnown[nextEvents[i].slotId] = nextEvents[i].eventSequence;
        for (unsigned int i = 0; i < count; ++i) {
            const InputEvent event = ReadEvent(input + 128 + i * EVENT_RECORD_SIZE);
            const unsigned int slot = event.slotId;
            if (drop[slot]) {
                if (!nextHasAck[slot] || Newer(event.eventSequence, nextAck[slot])) {
                    nextAck[slot] = event.eventSequence; nextHasAck[slot] = true;
                }
                continue;
            }
            if (nextHasAck[slot] && !Newer(event.eventSequence, nextAck[slot])) continue;
            bool retained = false;
            for (unsigned int j = 0; j < nextCount; ++j) {
                if (nextEvents[j].slotId == slot && nextEvents[j].eventSequence == event.eventSequence) {
                    if (!SameEvent(nextEvents[j], event)) return Fail(ERROR_EVENT);
                    retained = true; break;
                }
            }
            if (retained) continue;
            if (!nextHasAck[slot] || event.eventSequence != lastKnown[slot] + 1 || nextCount >= MAX_EVENTS)
                return Fail(ERROR_EVENT);
            nextEvents[nextCount] = event; nextSeen[nextCount++] = nowMs;
            lastKnown[slot] = event.eventSequence;
        }
        for (unsigned int i = 0; i < 4; ++i) {
            const SnapshotSlot sample = ReadSnapshot(input + 32 + i * SNAPSHOT_RECORD_SIZE);
            ApplySample(i, sample, newSession, nowMs);
            eventAck[i] = nextAck[i]; hasEventAck[i] = nextHasAck[i];
            if (drop[i]) {
                actionButtons[i] = 0; actionTrick[i] = 0; actionFresh[i] = false;
                actionTick[i] = 0xffffffffU; neutralPending[i] = true;
            }
        }
        pendingCount = nextCount;
        for (unsigned int i = 0; i < nextCount; ++i) {
            pendingEvents[i] = nextEvents[i]; pendingSeenAtMs[i] = nextSeen[i];
        }
        return true;
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

        if (gameplayMode) {
            for (unsigned int i = 0; i < 4; ++i) {
                const SnapshotSlot sample = ReadSnapshot(input + 32 + i * SNAPSHOT_RECORD_SIZE);
                if (sample.slotId != i) return Fail(ERROR_SHAPE);
                if (!newSession && hasSample[i] && sample.sampleSequence != sampleSequence[i] &&
                    !Newer(sample.sampleSequence, sampleSequence[i])) return Fail(ERROR_SEQUENCE);
            }
            if (!AcceptGameplay(input, nowMs, count, newSession)) return false;
            hostSession = nextHost; publishSequence = nextPublish; sourceSession = nextSource;
            active = true; lastPublishAtMs = nowMs; ageTicks = 0; ++accepted;
            flags = STATUS_READY | STATUS_APPLIED; lastError = ERROR_NONE;
            return true;
        }

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
            bool staleEvent = false;
            if (gameplayMode) {
                for (unsigned int j = 0; j < pendingCount; ++j) {
                    if (pendingEvents[j].slotId == i && uint32_t(nowMs - pendingSeenAtMs[j]) >= TIMEOUT_MS) {
                        staleEvent = true; break;
                    }
                }
            }
            if (hostTimedOut || !hasSample[i] ||
                sampleAgeMs[i] + uint32_t(nowMs - sampleSeenAtMs[i]) >= TIMEOUT_MS || staleEvent) {
                NeutralSlot(i);
                if (hasSample[i]) anyTimedOut = true;
                if (gameplayMode) DropSlotActions(i);
            }
        }
        if (anyTimedOut) flags |= STATUS_TIMEOUT;
    }
    bool ConsumeActions(unsigned int index, uint16_t& rawButtons, uint8_t& trickPulse) {
        rawButtons = 0; trickPulse = 0;
        if (!gameplayMode || index >= SLOT_COUNT) return false;
        if (actionTick[index] == guestTick) {
            rawButtons = actionButtons[index]; trickPulse = actionTrick[index];
            return actionFresh[index];
        }
        actionTick[index] = guestTick;
        actionFresh[index] = false; actionTrick[index] = 0;
        if (!GameplaySlotValid(index)) {
            DropSlotActions(index);
            actionTick[index] = guestTick;
            return false;
        }
        if (neutralPending[index]) {
            neutralPending[index] = false; actionButtons[index] = 0;
            return false;
        }

        bool usedButtons = false, usedTrick = false;
        for (unsigned int i = 0; i < pendingCount;) {
            const InputEvent event = pendingEvents[i];
            if (event.slotId != index) { ++i; continue; }
            // Preserve transitions across ticks: press/release/press cannot
            // collapse into the latest snapshot's final held value.
            if ((event.eventKind == BUTTONS && usedButtons) || (event.eventKind == TRICK && usedTrick)) break;
            if (event.eventKind == BUTTONS) {
                actionButtons[index] = event.value; usedButtons = true;
            } else {
                actionTrick[index] = event.value ? 1 : 0; usedTrick = true;
            }
            eventAck[index] = event.eventSequence; hasEventAck[index] = true;
            RemovePending(i);
        }
        bool pendingForSlot = false;
        for (unsigned int i = 0; i < pendingCount; ++i)
            if (pendingEvents[i].slotId == index) pendingForSlot = true;
        // Equality is deliberate: an older snapshot must not undo a newer
        // consumed event, and a future high-watermark must not bypass events.
        if (!usedButtons && !pendingForSlot && hasEventAck[index] &&
            slots[index].lastEventSequence == eventAck[index])
            actionButtons[index] = slots[index].buttons;
        actionFresh[index] = true;
        rawButtons = actionButtons[index]; trickPulse = actionTrick[index];
        return true;
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
