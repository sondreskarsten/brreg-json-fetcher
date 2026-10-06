"""Local collection, exports, and release checkpoint recovery."""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .client import Client, SourceError
from .collector import collect
from .export import export_release, restore_checkpoint
from .state import State

log = logging.getLogger(__name__)


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect BRREG accounts and build GitHub data releases"
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("collect", help="Collect signals and fetch queued account responses")
    run.add_argument("--state", default="data/checkpoint.sqlite3")
    run.add_argument(
        "--entity-snapshot",
        type=Path,
        default=Path("data/enheter.json.gz"),
        help="Retain the downloaded Enhetsregisteret bulk copy here",
    )
    run.add_argument(
        "--date", type=date.fromisoformat, default=datetime.now(ZoneInfo("Europe/Oslo")).date()
    )
    run.add_argument("--lookback", type=nonnegative, default=7, help="Announcement overlap in days")
    run.add_argument("--workers", type=int, choices=range(1, 21), default=4)
    run.add_argument("--max-entities", type=nonnegative, default=0, help="0 means no count limit")
    run.add_argument(
        "--max-seconds",
        type=nonnegative,
        default=0,
        help="Stop between request batches; 0 is unlimited",
    )
    run.add_argument(
        "--reconcile",
        action="store_true",
        help="Refetch every eligible entity on the next new load",
    )
    run.add_argument("--report", type=Path, help="Write a machine-readable run summary")
    export = commands.add_parser(
        "export", help="Create data assets, checkpoint, manifest and checksums"
    )
    export.add_argument("--state", default="data/checkpoint.sqlite3")
    export.add_argument("--output", type=Path, required=True)
    status = commands.add_parser("status", help="Show checkpoint counts")
    status.add_argument("--state", default="data/checkpoint.sqlite3")
    restore = commands.add_parser("restore", help="Verify and restore a release checkpoint")
    restore.add_argument("--from", dest="source", type=Path, required=True)
    restore.add_argument("--state", default="data/checkpoint.sqlite3")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = None
    try:
        if args.command == "restore":
            restore_checkpoint(args.source, args.state)
            return 0
        if args.command != "collect" and not Path(args.state).is_file():
            raise SourceError(f"Checkpoint does not exist: {args.state}")
        state = State(args.state)
        if args.command == "collect":
            report = collect(
                state,
                Client(snapshot_path=args.entity_snapshot),
                args.date,
                lookback=args.lookback,
                workers=args.workers,
                max_entities=args.max_entities,
                max_seconds=args.max_seconds,
                reconcile=args.reconcile,
            )
            print(json.dumps(report, indent=2))
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, indent=2) + "\n")
            return 2 if report["errors"] else 0
        if args.command == "export":
            print(json.dumps(export_release(state, args.output), indent=2))
        elif args.command == "status":
            print(json.dumps(state.summary(), indent=2))
        return 0
    except (SourceError, OSError, ValueError, sqlite3.Error) as exc:
        log.error("%s", exc)
        if args.command == "collect" and state is not None:
            report = {
                **state.summary(),
                "complete": False,
                "errors": 1,
                "fatal_error": str(exc),
                "date": args.date.isoformat(),
            }
            with state.db:
                state.set("last_run", json.dumps(report, sort_keys=True))
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, indent=2) + "\n")
        return 1
    finally:
        if state:
            state.close()


if __name__ == "__main__":
    sys.exit(main())
