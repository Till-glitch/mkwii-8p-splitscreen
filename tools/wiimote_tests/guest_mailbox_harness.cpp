// GPL-3.0-or-later. Test ABI around the actual portable guest receiver.
// No game resources or Nintendo runtime functions are linked.
#include "wheel_bridge_mailbox.h"

using namespace WiiBridgeProtocol;
using WiiBridgeMailbox::Receiver;

// Struct copies may use these helpers in the optimized CodeWarrior output.
extern "C" void* memcpy(void* destination, const void* source, unsigned int length) {
    volatile uint8_t* out = static_cast<volatile uint8_t*>(destination);
    const volatile uint8_t* in = static_cast<const volatile uint8_t*>(source);
    for (unsigned int i = 0; i < length; ++i) out[i] = in[i];
    return destination;
}
extern "C" void* memset(void* destination, int value, unsigned int length) {
    volatile uint8_t* out = static_cast<volatile uint8_t*>(destination);
    for (unsigned int i = 0; i < length; ++i) out[i] = uint8_t(value);
    return destination;
}

extern "C" unsigned int ss8_receiver_size() {
    return sizeof(Receiver);
}
extern "C" void ss8_reset(Receiver* receiver, uint32_t guestSession) {
    receiver->Reset(guestSession);
}
extern "C" void ss8_gameplay(Receiver* receiver, uint32_t enabled) {
    receiver->SetGameplayMode(enabled != 0);
}
extern "C" unsigned int ss8_consume(Receiver* receiver, uint32_t index, uint8_t* output) {
    uint16_t buttons = 0; uint8_t trick = 0;
    const bool fresh = receiver->ConsumeActions(index, buttons, trick);
    Write16(output, buttons); output[2] = trick; output[3] = fresh ? 1 : 0;
    return fresh ? 1 : 0;
}
extern "C" unsigned int ss8_accept(Receiver* receiver, const uint8_t* input, uint32_t nowMs) {
    return receiver->Accept(input, nowMs) ? 1 : 0;
}
extern "C" void ss8_tick(Receiver* receiver, uint32_t nowMs) {
    receiver->Tick(nowMs);
}
extern "C" void ss8_status(const Receiver* receiver, uint8_t* output, uint32_t generation) {
    receiver->WriteStatus(output, generation);
}
extern "C" unsigned int ss8_read_slot(const Receiver* receiver, uint32_t index, uint8_t* output) {
    if (index >= SLOT_COUNT) return 0;
    const SnapshotSlot& slot = receiver->slots[index];
    output[0] = slot.slotId; output[1] = slot.flags;
    Write16(output + 2, slot.buttons);
    Write16(output + 4, uint16_t(slot.accelX));
    Write16(output + 6, uint16_t(slot.accelY));
    Write16(output + 8, uint16_t(slot.accelZ));
    Write16(output + 10, slot.sampleAgeMs);
    Write32(output + 12, slot.sampleSequence);
    Write32(output + 16, slot.lastEventSequence);
    Write16(output + 20, slot.eventFlags);
    Write16(output + 22, 0);
    return SNAPSHOT_RECORD_SIZE;
}
