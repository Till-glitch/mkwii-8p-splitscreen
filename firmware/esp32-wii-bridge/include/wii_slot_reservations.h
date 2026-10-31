// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef SS8_WII_SLOT_RESERVATIONS_H
#define SS8_WII_SLOT_RESERVATIONS_H

// Keep allocation independent of Arduino/Bluepad/NVS for target-code tests.
namespace WiiBridgeFirmware {

enum { kReservationSlots = 4, kReservationAddressSize = 6 };

inline bool ValidReservationAddress(const unsigned char* address) {
    if (!address) return false;
    unsigned char any = 0, all = 0xff;
    for (unsigned int i = 0; i < kReservationAddressSize; ++i) {
        any |= address[i];
        all &= address[i];
    }
    return any != 0 && all != 0xff;
}

inline bool SameReservationAddress(const unsigned char* first, const unsigned char* second) {
    for (unsigned int i = 0; i < kReservationAddressSize; ++i)
        if (first[i] != second[i]) return false;
    return true;
}

// Known remotes reclaim their own slot. Unknown remotes may take a vacant
// reservation only during deliberate pairing; an active player is never evicted.
inline int SelectReservationSlot(const unsigned char addresses[kReservationSlots][kReservationAddressSize],
                                 const bool active[kReservationSlots], const unsigned char* address,
                                 bool pairing) {
    if (!ValidReservationAddress(address)) return -1;
    for (unsigned int i = 0; i < kReservationSlots; ++i)
        if (SameReservationAddress(addresses[i], address)) return active[i] ? -1 : int(i);
    if (!pairing) return -1;
    for (unsigned int i = 0; i < kReservationSlots; ++i)
        if (!active[i] && !ValidReservationAddress(addresses[i])) return int(i);
    for (unsigned int i = 0; i < kReservationSlots; ++i)
        if (!active[i]) return int(i);
    return -1;
}

typedef bool (*ReservationWriter)(const unsigned char* data, unsigned int size);

// Commit the full table as one NVS value before changing live metadata. A failed
// persistence operation leaves the old table (and its allowlist) untouched.
inline bool CommitReservation(unsigned char addresses[kReservationSlots][kReservationAddressSize],
                              unsigned int slot, const unsigned char* address,
                              ReservationWriter writer) {
    if (slot >= kReservationSlots || !ValidReservationAddress(address) || !writer) return false;
    if (SameReservationAddress(addresses[slot], address)) return true;
    unsigned char candidate[kReservationSlots][kReservationAddressSize];
    for (unsigned int i = 0; i < kReservationSlots; ++i)
        for (unsigned int byte = 0; byte < kReservationAddressSize; ++byte)
            candidate[i][byte] = i == slot ? address[byte] : addresses[i][byte];
    if (!writer(&candidate[0][0], sizeof(candidate))) return false;
    for (unsigned int i = 0; i < kReservationSlots; ++i)
        for (unsigned int byte = 0; byte < kReservationAddressSize; ++byte)
            addresses[i][byte] = candidate[i][byte];
    return true;
}

}  // namespace WiiBridgeFirmware
#endif
