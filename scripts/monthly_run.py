"""Run bounded segments, persist each one, and publish only completed monthly data."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from brreg_fetcher.export import export_release
from brreg_fetcher.state import State
from scripts.release import publish, seed_file


def finish_month(repo, state, snapshot, output, target):
    cycle = state.get("cycle")
    original = seed_file(repo, state, snapshot)
    final_dir = output / f"data-{cycle}"
    export_release(state, final_dir, snapshot_path=original)
    publish(repo, final_dir, f"data-{cycle}", target)
    with state.db:
        state.set("cycle_published", cycle)


def run_segments(
    repo,
    target,
    run_key,
    *,
    segments=3,
    seconds=3600,
    workers=4,
    state_path=Path("data/checkpoint.sqlite3"),
    snapshot=Path("data/enheter.json.gz"),
    output=Path("dist/monthly"),
):
    output.mkdir(parents=True, exist_ok=True)
    result = 0
    for index in range(1, segments + 1):
        if state_path.exists():
            prior = State(state_path)
            try:
                if prior.get("cycle_completed_at") and prior.get("cycle_published") != prior.get(
                    "cycle"
                ):
                    # Recover a crash after the final checkpoint but before release publication,
                    # including when the calendar has advanced to a new month.
                    finish_month(repo, prior, snapshot, output, target)
                    return 0
            finally:
                prior.close()
        report_path = state_path.parent / "run.json"
        report_path.unlink(missing_ok=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "brreg_fetcher.cli",
                "collect",
                "--state",
                str(state_path),
                "--entity-snapshot",
                str(snapshot),
                "--max-seconds",
                str(seconds),
                "--workers",
                str(workers),
                "--report",
                str(report_path),
            ],
            check=False,
        ).returncode
        if not report_path.exists():
            raise RuntimeError(
                "Collector did not produce a run report; preserving the last remote checkpoint"
            )
        report = json.loads(report_path.read_text())
        state = State(state_path)
        try:
            cycle = state.get("cycle")
            tag = f"checkpoint-{cycle or 'initial'}-{run_key}-{index}"
            include_source = None
            if cycle and not state.get("seed_release_tag"):
                # This download is uploaded once and referenced by later checkpoints.
                include_source = seed_file(repo, state, snapshot)
                with state.db:
                    state.set("seed_release_tag", tag)
            checkpoint_dir = output / tag
            export_release(
                state, checkpoint_dir, checkpoint_only=True, snapshot_path=include_source
            )
            publish(repo, checkpoint_dir, tag, target)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                    summary.write(
                        f"Month **{cycle}**, segment {index}: {report.get('attempted', 0):,} "
                        f"attempted; **{state.summary()['queued_entities']:,}** remaining. "
                        f"Saved `{tag}`.\n\n"
                    )
            shutil.rmtree(checkpoint_dir)
            if report.get("complete"):
                finish_month(repo, state, snapshot, output, target)
                return 0
            if result == 1:
                # Source/config errors need diagnosis; don't repeat the same failed setup.
                return result
        finally:
            state.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--workers", type=int, choices=range(1, 21), default=4)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("Segment duration must be between 1 and 3600 seconds")
    return run_segments(
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_SHA"],
        f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}",
        segments=args.segments,
        seconds=args.seconds,
        workers=args.workers,
    )


if __name__ == "__main__":
    sys.exit(main())
