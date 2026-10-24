#ifndef SS8_WII_BRIDGE_PROTOCOL_H
#define SS8_WII_BRIDGE_PROTOCOL_H

// W3 v1, GPL-3.0-or-later. The serialized format never depends on sizeof(POD).
// Arduino-independent; no allocation, exceptions, reinterpret casts or packing.
#ifndef __MWERKS__
#include <stddef.h>
#include <stdint.h>
#endif

namespace WiiBridgeProtocol {

// The Wii CodeWarrior build intentionally uses no host C runtime headers.
#ifdef __MWERKS__
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef signed short int16_t;
typedef unsigned int uint32_t;
typedef signed int int32_t;
typedef unsigned int size_t;
typedef char CheckU8[sizeof(uint8_t) == 1 ? 1 : -1];
typedef char CheckU16[sizeof(uint16_t) == 2 ? 1 : -1];
typedef char CheckU32[sizeof(uint32_t) == 4 ? 1 : -1];
#endif

enum MessageKind { SNAPSHOT = 1, DEVICES = 2, EVENTS = 3, ACK = 4 };
enum EventKind { BUTTONS = 1, TRICK = 2 };
enum {
    VERSION = 1,
    SLOT_COUNT = 4,
    HEADER_SIZE = 18,
    CRC_SIZE = 2,
    MAX_PAYLOAD = 512,
    MAX_FRAME_SIZE = HEADER_SIZE + MAX_PAYLOAD + CRC_SIZE,
    SNAPSHOT_RECORD_SIZE = 24,
    DEVICE_RECORD_SIZE = 8,
    EVENT_RECORD_SIZE = 16,
    ACK_RECORD_SIZE = 8,
    LEGACY_SIZE = 32,
    FLAG_CONNECTED = 1,
    FLAG_CALIBRATED = 2,
    FLAG_SAMPLE_VALID = 4,
    FLAG_EVENT_OVERFLOW = 8,
    EVENT_FLAG_TRICK = 1,
    DEVICE_PRESENT = 1
};

struct Header {
    uint8_t kind;
    uint16_t payloadLength;
    uint32_t bootSession, transportSequence, senderTimeMs;
};
struct FrameView {
    Header header;
    const uint8_t* payload;
};
struct SnapshotSlot {
    uint8_t slotId, flags;
    uint16_t buttons;
    int16_t accelX, accelY, accelZ;
    uint16_t sampleAgeMs;
    uint32_t sampleSequence, lastEventSequence;
    uint16_t eventFlags;
};
struct DeviceRecord {
    uint8_t slotId, flags, mac[6];
};
struct InputEvent {
    uint8_t slotId, eventKind;
    uint16_t value;
    uint32_t eventSequence, sampleSequence, sampleTimeMs;
};
struct EventAck {
    uint8_t slotId;
    uint32_t ackedEventSequence;
};
struct LegacySlot {
    uint8_t slotId;
    bool connected, calibrated;
    uint16_t buttons;
    int16_t accelX, accelY, accelZ;
    uint8_t sequence;
    bool trick;
};
struct LegacySnapshot {
    uint8_t connectedMask;
    LegacySlot slots[SLOT_COUNT];
};

inline uint16_t Read16(const uint8_t* data) {
    return uint16_t((uint16_t(data[0]) << 8) | data[1]);
}
inline int16_t ReadSigned16(const uint8_t* data) {
    const uint16_t value = Read16(data);
    return int16_t(value < 0x8000U ? int32_t(value) : int32_t(value) - 65536);
}
inline uint32_t Read32(const uint8_t* data) {
    return (uint32_t(data[0]) << 24) | (uint32_t(data[1]) << 16) |
           (uint32_t(data[2]) << 8) | uint32_t(data[3]);
}
inline void Write16(uint8_t* data, uint16_t value) {
    data[0] = uint8_t(value >> 8);
    data[1] = uint8_t(value);
}
inline void Write32(uint8_t* data, uint32_t value) {
    data[0] = uint8_t(value >> 24);
    data[1] = uint8_t(value >> 16);
    data[2] = uint8_t(value >> 8);
    data[3] = uint8_t(value);
}
inline uint16_t Crc16(const uint8_t* data, size_t length) {
    uint16_t crc = 0xffffU;
    for (size_t i = 0; i < length; ++i) {
        crc ^= uint16_t(data[i]) << 8;
        for (uint8_t bit = 0; bit < 8; ++bit)
            crc = uint16_t((crc << 1) ^ ((crc & 0x8000U) ? 0x1021U : 0));
    }
    return crc;
}
inline bool ValidShape(uint8_t kind, size_t length) {
    if (length > MAX_PAYLOAD) return false;
    switch (kind) {
        case SNAPSHOT: return length == SLOT_COUNT * SNAPSHOT_RECORD_SIZE;
        case DEVICES: return length == SLOT_COUNT * DEVICE_RECORD_SIZE;
        case EVENTS: return length != 0 && length % EVENT_RECORD_SIZE == 0;
        case ACK: return length != 0 && length % ACK_RECORD_SIZE == 0 && length <= SLOT_COUNT * ACK_RECORD_SIZE;
        default: return false;
    }
}
inline bool ValidSnapshot(const SnapshotSlot& record) {
    return record.slotId < SLOT_COUNT && (record.flags & ~0x0fU) == 0 &&
           (record.eventFlags & ~uint16_t(EVENT_FLAG_TRICK)) == 0 &&
           record.accelX >= -512 && record.accelX <= 511 &&
           record.accelY >= -512 && record.accelY <= 511 &&
           record.accelZ >= -512 && record.accelZ <= 511;
}
inline SnapshotSlot ReadSnapshot(const uint8_t* data) {
    SnapshotSlot record;
    record.slotId = data[0]; record.flags = data[1]; record.buttons = Read16(data + 2);
    record.accelX = ReadSigned16(data + 4); record.accelY = ReadSigned16(data + 6);
    record.accelZ = ReadSigned16(data + 8); record.sampleAgeMs = Read16(data + 10);
    record.sampleSequence = Read32(data + 12); record.lastEventSequence = Read32(data + 16);
    record.eventFlags = Read16(data + 20);
    return record;
}
inline DeviceRecord ReadDevice(const uint8_t* data) {
    DeviceRecord record;
    record.slotId = data[0]; record.flags = data[1];
    for (size_t i = 0; i < 6; ++i) record.mac[i] = data[2 + i];
    return record;
}
inline InputEvent ReadEvent(const uint8_t* data) {
    InputEvent record;
    record.slotId = data[0]; record.eventKind = data[1]; record.value = Read16(data + 2);
    record.eventSequence = Read32(data + 4); record.sampleSequence = Read32(data + 8);
    record.sampleTimeMs = Read32(data + 12);
    return record;
}
inline EventAck ReadAck(const uint8_t* data) {
    EventAck record;
    record.slotId = data[0]; record.ackedEventSequence = Read32(data + 4);
    return record;
}
inline bool ValidPayload(const FrameView& frame) {
    if (!ValidShape(frame.header.kind, frame.header.payloadLength) || !frame.payload) return false;
    uint8_t slots = 0;
    size_t stride = frame.header.kind == SNAPSHOT ? SNAPSHOT_RECORD_SIZE :
                    frame.header.kind == EVENTS ? EVENT_RECORD_SIZE : DEVICE_RECORD_SIZE;
    for (size_t offset = 0; offset < frame.header.payloadLength; offset += stride) {
        const uint8_t* data = frame.payload + offset;
        if (data[0] >= SLOT_COUNT) return false;
        const uint8_t mask = uint8_t(1U << data[0]);
        if (frame.header.kind != EVENTS) {
            if (slots & mask) return false;
            slots |= mask;
        }
        switch (frame.header.kind) {
            case SNAPSHOT:
                if (!ValidSnapshot(ReadSnapshot(data)) || Read16(data + 22)) return false;
                break;
            case DEVICES:
                if (data[1] & ~uint8_t(DEVICE_PRESENT)) return false;
                break;
            case EVENTS:
                if (data[1] != BUTTONS && data[1] != TRICK) return false;
                break;
            case ACK:
                if (data[1] || Read16(data + 2)) return false;
                break;
        }
    }
    return (frame.header.kind != SNAPSHOT && frame.header.kind != DEVICES) || slots == 0x0f;
}
inline bool DecodeFrame(const uint8_t* data, size_t length, FrameView& frame) {
    if (!data || length < HEADER_SIZE + CRC_SIZE || data[0] != 'W' || data[1] != '3' || data[2] != VERSION)
        return false;
    FrameView candidate;
    candidate.header.kind = data[3]; candidate.header.payloadLength = Read16(data + 4);
    candidate.header.bootSession = Read32(data + 6); candidate.header.transportSequence = Read32(data + 10);
    candidate.header.senderTimeMs = Read32(data + 14); candidate.payload = data + HEADER_SIZE;
    if (!ValidShape(candidate.header.kind, candidate.header.payloadLength) ||
        length != size_t(HEADER_SIZE) + candidate.header.payloadLength + CRC_SIZE ||
        Crc16(data, length - CRC_SIZE) != Read16(data + length - CRC_SIZE) || !ValidPayload(candidate))
        return false;
    frame = candidate;
    return true;
}
inline size_t FinishFrame(uint8_t* output, size_t capacity, uint8_t kind, uint16_t payloadLength,
                          uint32_t bootSession, uint32_t transportSequence, uint32_t senderTimeMs) {
    const size_t length = HEADER_SIZE + payloadLength + CRC_SIZE;
    if (!output || capacity < length || !ValidShape(kind, payloadLength)) return 0;
    output[0] = 'W'; output[1] = '3'; output[2] = VERSION; output[3] = kind;
    Write16(output + 4, payloadLength); Write32(output + 6, bootSession);
    Write32(output + 10, transportSequence); Write32(output + 14, senderTimeMs);
    Write16(output + length - CRC_SIZE, Crc16(output, length - CRC_SIZE));
    return length;
}
inline size_t EncodeSnapshot(uint8_t* output, size_t capacity, uint32_t bootSession,
                             uint32_t transportSequence, uint32_t senderTimeMs,
                             const SnapshotSlot* records, size_t count) {
    const size_t payloadLength = SLOT_COUNT * SNAPSHOT_RECORD_SIZE;
    if (!output || !records || count != SLOT_COUNT || capacity < HEADER_SIZE + payloadLength + CRC_SIZE) return 0;
    uint8_t slots = 0;
    for (size_t i = 0; i < count; ++i) {
        const SnapshotSlot& record = records[i];
        if (!ValidSnapshot(record) || (slots & (1U << record.slotId))) return 0;
        slots |= uint8_t(1U << record.slotId);
    }
    for (size_t i = 0; i < count; ++i) {
        const SnapshotSlot& record = records[i];
        uint8_t* data = output + HEADER_SIZE + i * SNAPSHOT_RECORD_SIZE;
        data[0] = record.slotId; data[1] = record.flags; Write16(data + 2, record.buttons);
        Write16(data + 4, uint16_t(record.accelX)); Write16(data + 6, uint16_t(record.accelY));
        Write16(data + 8, uint16_t(record.accelZ)); Write16(data + 10, record.sampleAgeMs);
        Write32(data + 12, record.sampleSequence); Write32(data + 16, record.lastEventSequence);
        Write16(data + 20, record.eventFlags); Write16(data + 22, 0);
    }
    return FinishFrame(output, capacity, SNAPSHOT, uint16_t(payloadLength), bootSession, transportSequence, senderTimeMs);
}
inline size_t EncodeDevices(uint8_t* output, size_t capacity, uint32_t bootSession,
                            uint32_t transportSequence, uint32_t senderTimeMs,
                            const DeviceRecord* records, size_t count) {
    const size_t payloadLength = SLOT_COUNT * DEVICE_RECORD_SIZE;
    if (!output || !records || count != SLOT_COUNT || capacity < HEADER_SIZE + payloadLength + CRC_SIZE) return 0;
    uint8_t slots = 0;
    for (size_t i = 0; i < count; ++i) {
        if (records[i].slotId >= SLOT_COUNT || records[i].flags & ~uint8_t(DEVICE_PRESENT) || (slots & (1U << records[i].slotId))) return 0;
        slots |= uint8_t(1U << records[i].slotId);
    }
    for (size_t i = 0; i < count; ++i) {
        uint8_t* data = output + HEADER_SIZE + i * DEVICE_RECORD_SIZE;
        data[0] = records[i].slotId; data[1] = records[i].flags;
        for (size_t j = 0; j < 6; ++j) data[2 + j] = records[i].mac[j];
    }
    return FinishFrame(output, capacity, DEVICES, uint16_t(payloadLength), bootSession, transportSequence, senderTimeMs);
}
inline size_t EncodeEvents(uint8_t* output, size_t capacity, uint32_t bootSession,
                           uint32_t transportSequence, uint32_t senderTimeMs,
                           const InputEvent* records, size_t count) {
    if (!output || !records || !count || count > MAX_PAYLOAD / EVENT_RECORD_SIZE) return 0;
    const size_t payloadLength = count * EVENT_RECORD_SIZE;
    if (capacity < HEADER_SIZE + payloadLength + CRC_SIZE) return 0;
    for (size_t i = 0; i < count; ++i)
        if (records[i].slotId >= SLOT_COUNT || (records[i].eventKind != BUTTONS && records[i].eventKind != TRICK)) return 0;
    for (size_t i = 0; i < count; ++i) {
        const InputEvent& record = records[i];
        uint8_t* data = output + HEADER_SIZE + i * EVENT_RECORD_SIZE;
        data[0] = record.slotId; data[1] = record.eventKind; Write16(data + 2, record.value);
        Write32(data + 4, record.eventSequence); Write32(data + 8, record.sampleSequence); Write32(data + 12, record.sampleTimeMs);
    }
    return FinishFrame(output, capacity, EVENTS, uint16_t(payloadLength), bootSession, transportSequence, senderTimeMs);
}
inline size_t EncodeAck(uint8_t* output, size_t capacity, uint32_t bootSession,
                        uint32_t transportSequence, uint32_t senderTimeMs,
                        const EventAck* records, size_t count) {
    if (!output || !records || !count || count > SLOT_COUNT) return 0;
    const size_t payloadLength = count * ACK_RECORD_SIZE;
    if (capacity < HEADER_SIZE + payloadLength + CRC_SIZE) return 0;
    uint8_t slots = 0;
    for (size_t i = 0; i < count; ++i) {
        if (records[i].slotId >= SLOT_COUNT || (slots & (1U << records[i].slotId))) return 0;
        slots |= uint8_t(1U << records[i].slotId);
    }
    for (size_t i = 0; i < count; ++i) {
        uint8_t* data = output + HEADER_SIZE + i * ACK_RECORD_SIZE;
        data[0] = records[i].slotId; data[1] = 0; Write16(data + 2, 0); Write32(data + 4, records[i].ackedEventSequence);
    }
    return FinishFrame(output, capacity, ACK, uint16_t(payloadLength), bootSession, transportSequence, senderTimeMs);
}
inline bool DecodeSnapshot(const FrameView& frame, SnapshotSlot* records, size_t capacity, size_t& count) {
    count = 0;
    if (frame.header.kind != SNAPSHOT || !records || capacity < SLOT_COUNT || !ValidPayload(frame)) return false;
    for (size_t i = 0; i < SLOT_COUNT; ++i) records[i] = ReadSnapshot(frame.payload + i * SNAPSHOT_RECORD_SIZE);
    count = SLOT_COUNT;
    return true;
}
inline bool DecodeDevices(const FrameView& frame, DeviceRecord* records, size_t capacity, size_t& count) {
    count = 0;
    if (frame.header.kind != DEVICES || !records || capacity < SLOT_COUNT || !ValidPayload(frame)) return false;
    for (size_t i = 0; i < SLOT_COUNT; ++i) records[i] = ReadDevice(frame.payload + i * DEVICE_RECORD_SIZE);
    count = SLOT_COUNT;
    return true;
}
inline bool DecodeEvents(const FrameView& frame, InputEvent* records, size_t capacity, size_t& count) {
    count = 0;
    const size_t needed = frame.header.payloadLength / EVENT_RECORD_SIZE;
    if (frame.header.kind != EVENTS || !records || capacity < needed || !ValidPayload(frame)) return false;
    for (size_t i = 0; i < needed; ++i) records[i] = ReadEvent(frame.payload + i * EVENT_RECORD_SIZE);
    count = needed;
    return true;
}
inline bool DecodeAck(const FrameView& frame, EventAck* records, size_t capacity, size_t& count) {
    count = 0;
    const size_t needed = frame.header.payloadLength / ACK_RECORD_SIZE;
    if (frame.header.kind != ACK || !records || capacity < needed || !ValidPayload(frame)) return false;
    for (size_t i = 0; i < needed; ++i) records[i] = ReadAck(frame.payload + i * ACK_RECORD_SIZE);
    count = needed;
    return true;
}
inline bool DecodeW2(const uint8_t* data, size_t length, LegacySnapshot& result) {
    if (!data || length != LEGACY_SIZE || data[0] != 'W' || data[1] != '2' || data[2] & 0xf0U) return false;
    uint8_t checksum = data[2];
    for (size_t i = 4; i < length; ++i) checksum ^= data[i];
    if (checksum != data[3]) return false;
    LegacySnapshot candidate;
    candidate.connectedMask = data[2];
    for (size_t i = 0; i < SLOT_COUNT; ++i) {
        const uint8_t* source = data + 4 + i * 7;
        LegacySlot& slot = candidate.slots[i];
        slot.slotId = uint8_t(i); slot.connected = (data[2] & (1U << i)) != 0;
        slot.calibrated = (source[5] & 0x80U) != 0;
        slot.buttons = Read16(source); slot.sequence = source[6]; slot.trick = (source[5] & 0x40U) != 0;
        int16_t axes[3];
        for (size_t axis = 0; axis < 3; ++axis) {
            const uint16_t value = uint16_t(source[2 + axis] | (((source[5] >> (axis * 2)) & 3U) << 8));
            axes[axis] = int16_t((value & 512U) ? int32_t(value) - 1024 : int32_t(value));
        }
        slot.accelX = axes[0]; slot.accelY = axes[1]; slot.accelZ = axes[2];
    }
    result = candidate;
    return true;
}

}  // namespace WiiBridgeProtocol
#endif
