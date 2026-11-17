"""Ask the by-id endpoint for rows that a change log reports as aged out or resubmitted."""

import argparse
import collections
import csv
import random
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap"
csv.field_size_limit(sys.maxsize)


def sample(changelog, per_group, seed):
    events = {}
    with Path(changelog).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["endringstype"] in ("AgedOut", "Resubmitted") and row["id_old"]:
                events[row["event_id"]] = row
    groups = collections.defaultdict(list)
    for row in events.values():
        groups[(row["endringstype"], row["regnskapstype"], row["fiscal_year"])].append(row)
    rng = random.Random(seed)
    picked = []
    for _, rows in sorted(groups.items()):
        rows.sort(key=lambda r: r["event_id"])
        picked += rng.sample(rows, min(len(rows), per_group))
    return picked


def probe(session, row, pause):
    response = session.get(f"{ACCOUNTS}/{row['orgnr']}/{row['id_old']}", timeout=60)
    found = response.json() if response.status_code == 200 else {}
    time.sleep(pause)
    return {
        "endringstype": row["endringstype"],
        "regnskapstype": row["regnskapstype"],
        "fiscal_year": row["fiscal_year"],
        "orgnr": row["orgnr"],
        "id_old": row["id_old"],
        "journalnr_old": row["journalnr_old"],
        "http_status": response.status_code,
        "id": found.get("id", ""),
        "journalnr": found.get("journalnr", ""),
        "til_dato": found.get("regnskapsperiode", {}).get("tilDato", ""),
    }


def run(changelog, out=HERE / "probes.csv", per_group=25, seed=20261117, pause=0.25):
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    rows = [probe(session, row, pause) for row in sample(changelog, per_group, seed)]
    with Path(out).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = collections.Counter(
        (r["endringstype"], r["regnskapstype"], r["fiscal_year"], r["http_status"]) for r in rows
    )
    for key, count in sorted(counts.items()):
        print(*key, count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("changelog", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "probes.csv")
    parser.add_argument("--per-group", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--pause", type=float, default=0.25)
    args = parser.parse_args()
    run(args.changelog, args.out, args.per_group, args.seed, args.pause)
