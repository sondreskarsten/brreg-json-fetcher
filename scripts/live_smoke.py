"""Download the real seed and retain a bounded AS/ASA accounts API sample."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from brreg_fetcher.client import ACCOUNTS_URL, ENTITIES_URL, Client, decode_filings
from brreg_fetcher.export import export_release, sha256_file
from brreg_fetcher.state import State


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-form", type=int, choices=range(1, 21), default=5)
    parser.add_argument("--output", type=Path, default=Path("data/live"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot = args.output.parent / "enheter.json.gz"
    state_path = args.output.parent / "live-checkpoint.sqlite3"
    if state_path.exists():
        raise RuntimeError("Use a fresh live-test state to make sample coverage explicit")
    client = Client(snapshot_path=snapshot)
    state = State(state_path)
    day = datetime.now(ZoneInfo("Europe/Oslo")).date().isoformat()
    try:
        print("Downloading the full Enhetsregisteret main-entity snapshot...", flush=True)
        total = state.start_cycle(client.entities(), day)
        counts = dict(
            state.db.execute(
                "SELECT organisasjonsform, count(*) FROM entities WHERE active=1 GROUP BY organisasjonsform"
            )
        )
        print(json.dumps({"downloaded_entities": total, "seed_by_form": counts}), flush=True)
        raw_dir = args.output / "responses"
        raw_dir.mkdir()
        samples = []
        successes = {"AS": 0, "ASA": 0}
        for form in successes:
            selected = list(
                state.db.execute(
                    "SELECT orgnr, year FROM entities WHERE active=1 AND organisasjonsform=? ORDER BY year DESC, orgnr LIMIT ?",
                    (form, args.per_form),
                )
            )
            if not selected:
                raise RuntimeError(f"No {form} entities with filed accounts in the downloaded seed")
            for row in selected:
                orgnr = row["orgnr"]
                response = client.accounts(orgnr)
                (raw_dir / f"{orgnr}.json").write_bytes(response.body)
                observed_at = datetime.now(UTC).isoformat()
                outcome = state.record(orgnr, state.get("generation"), response, observed_at)
                filings = decode_filings(response.body, orgnr) if response.status == 200 else []
                successes[form] += bool(filings)
                sample = {
                    "orgnr": orgnr,
                    "organisasjonsform": form,
                    "latest_filed_year": row["year"],
                    "url": f"{ACCOUNTS_URL}/{orgnr}",
                    "http_status": response.status,
                    "observed_at": observed_at,
                    "message": response.message,
                    "filings": [
                        {
                            "id": f["id"],
                            "journalnr": f.get("journalnr"),
                            "regnskapstype": f["regnskapstype"],
                            "period": f["regnskapsperiode"],
                            "valuta": f.get("valuta"),
                        }
                        for f in filings
                    ],
                    "outcome": outcome,
                }
                samples.append(sample)
                print(json.dumps(sample, ensure_ascii=False), flush=True)
        report = {
            "date": day,
            "scope": "bounded live API sample, not a full collection",
            "complete": False,
            "source": ENTITIES_URL,
            "downloaded_entities": total,
            "snapshot_bytes": snapshot.stat().st_size,
            "snapshot_sha256": sha256_file(snapshot),
            "seed_by_form": counts,
            "successful_entities": successes,
            "sampled_entities": len(samples),
            "returned_filings": sum(len(s["filings"]) for s in samples),
            "samples": samples,
            **state.summary(),
        }
        with state.db:
            state.set("last_run", json.dumps({k: v for k, v in report.items() if k != "samples"}))
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
        export_release(state, args.output / "exports")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                summary.write(
                    f"Downloaded **{total:,}** entities. Seed: **{counts.get('AS', 0):,} AS** and "
                    f"**{counts.get('ASA', 0):,} ASA** with a filed-account year.\n\n"
                    f"Sampled **{len(samples)}** entities; returned **{report['returned_filings']}** filings. "
                    "See the artifact for exact JSON responses, the seed, and CSV.\n"
                )
        if not all(successes.values()):
            raise RuntimeError(
                "Live test requires a nonempty HTTP-200 filing response for both AS and ASA"
            )
    finally:
        state.close()


if __name__ == "__main__":
    main()
