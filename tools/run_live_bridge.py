#!/usr/bin/env python3
"""Launch one isolated Dolphin profile and its explicitly verified live bridge."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.wiimote_bridge.runner import (DolphinRun, RunnerError, check_timeout,
                                        common_parser, run_serial_child)
from tools.wiimote_bridge.mailbox import MailboxError
from tools.wiimote_bridge.ports import PortSelectionError


def main() -> int:
    parser = common_parser(__doc__, timeout=60)
    parser.add_argument("--port", help="Explicit ESP32 port; auto-select only one known UART candidate")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seconds", type=float, default=0, help="Serial duration; zero until Ctrl+C")
    parser.add_argument("--config", type=Path, default=ROOT / "build/wiimote-bridge/config.json")
    parser.add_argument("--manual-mapping", action="store_true",
                        help="Use saved MAC reservations; default assigns connected remotes automatically")
    args = parser.parse_args()
    try:
        check_timeout(args.timeout)
        with DolphinRun(args.root, args.manifest, executable=args.dolphin_exe, leave_running=args.leave_running) as run:
            run.connect(args.timeout, gameplay=True)
            return run_serial_child(run, port=args.port, baud=args.baud, seconds=args.seconds,
                                    config=args.config, manual_mapping=args.manual_mapping)
    except KeyboardInterrupt:
        return 130
    except (RunnerError, MailboxError, PortSelectionError, OSError, ValueError) as error:
        print(f"Live bridge stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
