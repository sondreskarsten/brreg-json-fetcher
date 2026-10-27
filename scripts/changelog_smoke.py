"""Collect a small sample against the live API and log its changes since the prior release."""

import argparse
import csv
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from brreg_fetcher.changelog import build_changelog, read_manifest, release_files
from brreg_fetcher.client import Client
from brreg_fetcher.collector import collect
from brreg_fetcher.export import export_release
from brreg_fetcher.state import State
from scripts.release import download_release, previous_release, published_releases

csv.field_size_limit(sys.maxsize)


class SeedClient:
    """Serve the sampled organisations as this run's entity register."""

    def __init__(self, records, live):
        self.records = records
        self.live = live

    def entities(self):
        return list(self.records)

    def entity(self, orgnr):
        return self.live.entity(orgnr)


def sample_records(prior_dir, orgnrs=None, count=0, seed=0):
    rows = []
    for path in release_files(prior_dir, read_manifest(prior_dir), "observations"):
        with path.open(newline="", encoding="utf-8") as stream:
            rows.extend(csv.DictReader(stream))
    if orgnrs:
        wanted = set(orgnrs)
        rows = [r for r in rows if r["orgnr"] in wanted]
        missing = wanted - {r["orgnr"] for r in rows}
        rows += [{"orgnr": o, "organisasjonsform": "AS", "latest_filing_year": ""} for o in missing]
    elif count:
        rows = random.Random(seed).sample(rows, min(count, len(rows)))
    return [
        {
            "organisasjonsnummer": r["orgnr"],
            "sisteInnsendteAarsregnskap": r.get("latest_filing_year") or None,
            "organisasjonsform": {"kode": r.get("organisasjonsform") or "AS"},
        }
        for r in rows
    ]


def run(repo, output, *, prior_tag=None, orgnrs=None, count=500, seed=0, workers=4, day=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    day = day or datetime.now(ZoneInfo("Europe/Oslo")).date()
    if prior_tag is None:
        prior_tag = previous_release(published_releases(repo), "data", day.strftime("%Y-%m"))
        if prior_tag is None:
            prior_tag = previous_release(published_releases(repo), "data", "9999-99")
    if prior_tag is None:
        raise RuntimeError("No published data release to compare with")
    prior_dir = download_release(
        repo, prior_tag, output / prior_tag, "manifest.json", "accounts*.csv", "observations*.csv"
    )
    records = sample_records(prior_dir, orgnrs=orgnrs, count=count, seed=seed)
    state_path = output / "sample-checkpoint.sqlite3"
    if state_path.exists():
        raise RuntimeError("Use a fresh output directory for each smoke run")
    state = State(state_path)
    try:
        client = SeedClient(records, Client())
        report = collect(state, client, day, workers=workers)
        current_dir = output / "current"
        export_release(state, current_dir)
    finally:
        state.close()
    manifest = build_changelog(prior_dir, current_dir, output / "changelog", sample=True)
    summary = {
        "prior_release": prior_tag,
        "sampled": len(records),
        "collection": {
            k: report[k] for k in ("attempted", "ok", "not_found", "unsupported", "errors")
        },
        "events": manifest["events"],
        "delta_rows": manifest["dataset"]["delta"]["rows"],
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", type=Path, default=Path("data/changelog-smoke"))
    parser.add_argument("--prior-tag", help="Defaults to the newest published data release")
    parser.add_argument("--orgnrs", type=Path, help="File with one orgnr per line")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, choices=range(1, 21), default=4)
    args = parser.parse_args()
    orgnrs = args.orgnrs.read_text().split() if args.orgnrs else None
    run(
        args.repo,
        args.output,
        prior_tag=args.prior_tag,
        orgnrs=orgnrs,
        count=args.count,
        seed=args.seed,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
