// SPDX-License-Identifier: GPL-3.0-or-later
// Portable model checks: compile/run with a native C++ compiler when available.
#include <assert.h>
#include "../include/wii_input_model.h"

using namespace WiiBridgeFirmware;
namespace Protocol = WiiBridgeProtocol;

int main() {
    const uint8_t calibration[] = {128, 128, 128, 0, 154, 154, 154, 0, 0, 163};
    int zero[] = {1, 2, 3}, span[] = {4, 5, 6};
    assert(ReadCalibration(calibration, zero, span));
    for (int i = 0; i < 3; ++i) { assert(zero[i] == 512); assert(span[i] == 104); }
    uint8_t damaged[10];
    memcpy(damaged, calibration, 10);
    damaged[9] ^= 1;
    assert(!ReadCalibration(damaged, zero, span));
    assert(zero[0] == 512 && span[0] == 104);
    assert(NormaliseSensor(512, 512, 104) == 0);
    assert(NormaliseSensor(616, 512, 104) == 128);
    assert(NormaliseSensor(408, 512, 104) == -128);
    assert(NormaliseSensor(1023, 512, 104) == 511);
    assert(NormaliseSensor(0, 512, 104) == -512);

    RemoteSample sample = {};
    sample.ResetInput();
    sample.calibrated = true;
    uint8_t report[] = {0x31, 0, 1, 128, 128, 128};
    sample.ReadReport(0, report, 100);
    sample.ReadReport(0, report, 105);
    assert(sample.sampleSequence == 2 && sample.events.count == 1);
    assert(sample.events.records[0].value == 0x100);
    report[2] = 0;
    sample.ReadReport(0, report, 110);
    report[2] = 1;
    sample.ReadReport(0, report, 115);
    assert(sample.events.count == 3);
    assert(sample.events.records[1].value == 0 && sample.events.records[2].value == 0x100);
    sample.Acknowledge(sample.lastEventSequence + 1);
    assert(sample.events.count == 3);
    sample.Acknowledge(2);
    assert(sample.events.count == 1);
    sample.Acknowledge(3);
    assert(sample.events.count == 0);

    Protocol::SnapshotSlot snapshot = sample.Snapshot(0, true, 120);
    assert(snapshot.flags == 7 && snapshot.buttons == 0x100 && snapshot.sampleAgeMs == 5);
    assert(snapshot.accelX == 0 && snapshot.accelY == 0 && snapshot.accelZ == 0);
    snapshot = sample.Snapshot(0, true, 366);
    assert(!(snapshot.flags & Protocol::FLAG_SAMPLE_VALID) && snapshot.buttons == 0);

    // Source freshness, not transport polling, owns sampleSequence.
    for (int i = 0; i < 20; ++i) sample.Snapshot(0, true, 120);
    assert(sample.sampleSequence == 4);

    // Bounded storage cannot replay an incomplete button burst after overflow.
    for (size_t i = 0; i <= kEventCapacity; ++i) sample.PushEvent(0, Protocol::BUTTONS, 1, 200);
    assert(sample.eventOverflow && sample.events.count == 0);
    assert(!(sample.Snapshot(0, true, 200).flags & Protocol::FLAG_SAMPLE_VALID));
    sample.Acknowledge(sample.lastEventSequence);
    assert(sample.eventOverflow);  // a held physical button cannot arm recovery
    sample.buttons = 0;
    sample.Acknowledge(sample.lastEventSequence);
    assert(!sample.eventOverflow && !sample.hasButtonBaseline);

    // A report after an input timeout starts a new edge baseline.
    report[2] = 1;
    sample.ReadReport(0, report, 300);
    sample.ServiceTrick(0, 551);
    assert(sample.events.count == 0 && !sample.hasButtonBaseline);
    sample.ReadReport(0, report, 552);
    assert(sample.events.count == 1 && sample.events.records[sample.events.head].value == 0x100);

    // A live source with an unacknowledged old event also fails neutral.
    sample.ReadReport(0, report, 800);
    sample.ServiceTrick(0, 803);
    assert(sample.eventOverflow && sample.events.count == 0);

    sample.ResetInput();
    sample.valid = sample.calibrated = true;
    sample.receivedAt = 0xfffffff0u;
    assert(sample.Fresh(0x10));
    sample.lastEventSequence = 0xfffffffeu;
    sample.PushEvent(0, Protocol::BUTTONS, 0, 0x10);
    sample.PushEvent(0, Protocol::BUTTONS, 0, 0x11);
    assert(sample.lastEventSequence == 0 && sample.events.count == 2);
    sample.Acknowledge(0);
    assert(sample.events.count == 0);
    const uint32_t previousSequence = sample.sampleSequence;
    sample.ResetInput();
    assert(sample.sampleSequence == previousSequence && sample.lastEventSequence == 0);
    return 0;
}
