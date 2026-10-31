// Compile the production culling helper, without copying its implementation.
#include <SplitScreen8/Culling.cpp>

namespace SplitScreen8 {
u8 raceScreenCount;
u8 raceLocalCount;
}

extern "C" u32 ss8_clip_minimum(const SplitScreen8::Clip* clip, u32 screens) {
    SplitScreen8::raceScreenCount = screens;
    union { float value; u32 bits; } result;
    result.value = SplitScreen8::ClipMinimumDistance(*clip);
    return result.bits;
}

extern "C" float ss8_clip_minimum_float(const SplitScreen8::Clip* clip) {
    return SplitScreen8::ClipMinimumDistance(*clip);
}
