#!/usr/bin/env python3
"""Synthetic P5 binding smoke; no physical Wheel or character-transition acceptance."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.wiimote_bridge.runner import RunnerError, common_parser, run_synthetic_smoke
from tools.wiimote_bridge.mailbox import MailboxError


def main() -> int:
    args = common_parser(__doc__, timeout=160).parse_args()
    try:
        return run_synthetic_smoke(args, count=1)
    except KeyboardInterrupt:
        return 130
    except (RunnerError, MailboxError, OSError, ValueError) as error:
        print(f"Synthetic smoke failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
