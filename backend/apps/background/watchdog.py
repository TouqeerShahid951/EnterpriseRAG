"""Heartbeat used by scheduled background-process healthchecks."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HEARTBEAT_PATH = Path("/tmp/agenticrag-background-heartbeat")


def heartbeat(path: Path = HEARTBEAT_PATH) -> None:
    path.touch()


def is_fresh(path: Path, max_age_seconds: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime <= max_age_seconds
    except FileNotFoundError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the background-process heartbeat.")
    parser.add_argument("max_age_seconds", type=int)
    args = parser.parse_args()
    if args.max_age_seconds < 1:
        parser.error("max_age_seconds must be positive")
    if is_fresh(HEARTBEAT_PATH, args.max_age_seconds):
        return 0
    print("background-process heartbeat is missing or stale", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
