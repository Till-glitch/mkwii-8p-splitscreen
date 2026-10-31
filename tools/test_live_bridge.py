#!/usr/bin/env python3
"""Explicit live descriptor/status smoke; optional serial transfer, no hardware-count claim."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.wiimote_bridge.runner import (DolphinRun, RunnerError, check_timeout,
                                        common_parser, run_serial_child)
from tools.wiimote_bridge.mailbox import MailboxError
from tools.wiimote_bridge.ports import PortSelectionError


def main() -> int:
    parser = common_parser(__doc__)
    parser.add_argument("--bridge", action="store_true", help="Also run a bounded live serial transfer")
    parser.add_argument("--port", help="ESP32 port; otherwise require one unambiguous UART candidate")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--bridge-seconds", type=float, default=10)
    parser.add_argument("--config", type=Path, default=ROOT / "build/wiimote-bridge/config.json")
    args = parser.parse_args()
    try:
        check_timeout(args.timeout)
        if args.bridge:
            check_timeout(args.bridge_seconds)
        with DolphinRun(args.root, args.manifest, executable=args.dolphin_exe, leave_running=args.leave_running) as run:
            mailbox = run.connect(args.timeout)
            before = mailbox.read_status()
            if args.bridge:
                result = run_serial_child(run, port=args.port, baud=args.baud, seconds=args.bridge_seconds, config=args.config)
                if result:
                    raise RunnerError(f"Serial service exited with {result}")
            after = mailbox.read_status()
            delta = (after.accepted_count - before.accepted_count) & 0xFFFFFFFF
            if args.bridge and not 0 < delta < 0x80000000:
                raise RunnerError("Serial process completed without a demonstrated accepted guest publication")
            run.report("live-bridge-report.json", {
                "verified": True, "descriptor_and_status_verified": True,
                "serial_publications_observed": bool(args.bridge and delta),
                "accepted_publications_delta": delta, "physical_wheels_verified": False,
                "screenshots": [run.screenshot("live-bridge-observation")],
                "status": after.__dict__})
            print("PASS: current build/session descriptor and status verified." +
                  (" Serial publication observed." if args.bridge else " No serial data path was exercised.") +
                  " Physical controller count, driving, animations and FPS were not automatically assessed.")
            return 0
    except KeyboardInterrupt:
        return 130
    except (RunnerError, MailboxError, PortSelectionError, OSError, ValueError) as error:
        print(f"Live smoke failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
