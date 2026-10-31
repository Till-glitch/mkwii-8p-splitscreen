// SPDX-License-Identifier: GPL-3.0-or-later
#include "wii_slot_reservations.h"

using namespace WiiBridgeFirmware;
static bool writeSucceeds;
static unsigned char* persisted;
static unsigned int writes;

static bool Write(const unsigned char* bytes, unsigned int size) {
    ++writes;
    for (unsigned int i = 0; i < size; ++i) persisted[i] = bytes[i];
    return writeSucceeds;
}

extern "C" int ss8_select(const unsigned char addresses[4][6], const bool active[4],
                           const unsigned char* address, unsigned int pairing) {
    return SelectReservationSlot(addresses, active, address, pairing != 0);
}

extern "C" unsigned int ss8_commit(unsigned char addresses[4][6], unsigned int slot,
                                   const unsigned char* address, unsigned char* output,
                                   unsigned int success) {
    writes = 0;
    persisted = output;
    writeSucceeds = success != 0;
    const bool result = CommitReservation(addresses, slot, address, Write);
    return (writes << 1) | static_cast<unsigned int>(result);
}
