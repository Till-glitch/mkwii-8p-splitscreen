// GPL-3.0-or-later. C ABI around the real CodeWarrior-compiled Wheel port.
#include <SplitScreen8/WheelNative.cpp>
#include <wheel_bridge_identity.h>

extern "C" u32 ss8_wheel_size() { return sizeof(SplitScreen8::WheelNativeState); }
extern "C" u32 ss8_action_size() { return sizeof(SplitScreen8::WheelActionState); }
extern "C" void ss8_wheel_reset(SplitScreen8::WheelNativeState* state) {
    SplitScreen8::ResetWheelNative(*state);
}
extern "C" void ss8_action_reset(SplitScreen8::WheelActionState* state) {
    SplitScreen8::ResetWheelActions(*state);
}
extern "C" u32 ss8_quantise(u32 bits) {
    union { u32 bits; f32 value; } input;
    input.bits = bits;
    return SplitScreen8::QuantiseWheelNativeSteering(input.value);
}
extern "C" void ss8_wheel_step(SplitScreen8::WheelNativeState* state,
    const WiiBridgeProtocol::SnapshotSlot* sensor, u32 buttons, u32 autoDrift,
    u32 flick, Input::State* output) {
    SplitScreen8::StepWheelNative(*state, *sensor, buttons, autoDrift != 0, flick, *output);
}
extern "C" void ss8_action_step(SplitScreen8::WheelActionState* state,
    u32 buttons, u32 autoDrift, Input::State* output) {
    SplitScreen8::ApplyWheelActions(*state, buttons, autoDrift != 0, *output);
}
extern "C" u32 ss8_identity_slot_id(u32 slot) {
    return WiiBridgeIdentity::SlotId(slot);
}
extern "C" u32 ss8_identity_display_id(u32 id) {
    return WiiBridgeIdentity::DisplayId(id);
}
extern "C" u32 ss8_identity_fill(u8* params, u32 slot) {
    return WiiBridgeIdentity::FillProxyParams(params, slot) ? 1 : 0;
}
