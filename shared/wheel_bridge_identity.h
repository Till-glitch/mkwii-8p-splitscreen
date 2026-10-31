#ifndef SS8_WHEEL_BRIDGE_IDENTITY_H
#define SS8_WHEEL_BRIDGE_IDENTITY_H
#include "wii_bridge_protocol.h"

namespace WiiBridgeIdentity {
using namespace WiiBridgeProtocol;

// Private registration IDs never enter native UI/speaker channel decoders.
inline uint32_t SlotId(unsigned int slot) {
    return slot < 4 ? 0x53530001U + slot : 0;
}
inline bool IsPrivateId(uint32_t id) {
    return id >= SlotId(0) && id <= SlotId(3);
}
inline uint32_t DisplayId(uint32_t id) {
    return IsPrivateId(id) ? ((id - SlotId(0) + 1) << 8) | 0x11U : id;
}
inline bool FillProxyParams(uint8_t* params, unsigned int slot) {
    if (slot >= 4) return false;
    Write32(params, 0); // ControllerType WHEEL.
    // Locally administered logical identity. This is not a physical MAC; the
    // host owns physical device -> P5..P8 reservations. Never borrow a native
    // Wii channel's MAC through WPADProbe/GetDevAddr.
    const uint8_t prefix[5] = {0x02, 0x53, 0x53, 0x38, 0x00};
    for (unsigned int i = 0; i < 5; ++i) params[4 + i] = prefix[i];
    params[9] = uint8_t(slot + 1);
    params[10] = params[11] = 0;
    Write32(params + 12, slot); // Presentation only, always within native width.
    return true;
}
}
#endif
