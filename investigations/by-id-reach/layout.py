"""Probe the ids around sampled rows of a data release to see how ids are laid out."""

import argparse
import collections
import csv
import json
import random
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap"
OFFSETS = range(-2, 4)
csv.field_size_limit(sys.maxsize)


def sample(release, count, seed):
    by_journalnr = collections.defaultdict(dict)
    for path in sorted(Path(release).glob("accounts-*.csv")):
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                by_journalnr[row["journalnr"]][row["regnskapstype"]] = (
                    row["_meta.orgnr"],
                    int(row["id"]),
                )
    solo = sorted(v["SELSKAP"] for v in by_journalnr.values() if set(v) == {"SELSKAP"})
    pair = sorted(v["SELSKAP"] for v in by_journalnr.values() if len(v) == 2)
    rng = random.Random(seed)
    return [("selskap_only", *r) for r in rng.sample(solo, count)] + [
        ("selskap_and_konsern", *r) for r in rng.sample(pair, count)
    ]


def fetch(session, orgnr, row_id, pause):
    response = session.get(f"{ACCOUNTS}/{orgnr}/{row_id}", timeout=60)
    time.sleep(pause)
    if response.status_code != 200:
        return str(response.status_code), None, None
    row = response.json()
    row.pop("id")
    return row["regnskapstype"], row["journalnr"], json.dumps(row, sort_keys=True)


def probe(session, kind, orgnr, row_id, pause):
    found = {k: fetch(session, orgnr, row_id + k, pause) for k in OFFSETS}
    journalnr = found[0][1]
    record = {"submission": kind, "orgnr": orgnr, "listed_selskap_id": row_id}
    for k in OFFSETS:
        label, other, _ = found[k]
        record[f"offset_{k:+d}"] = label if other in (None, journalnr) else "other_journalnr"
    record["selskap_copy_identical"] = found[-1][2] == found[0][2]
    record["konsern_copy_identical"] = found[1][2] == found[2][2] if found[2][2] else ""
    return record


def run(release, out=HERE / "layout.csv", count=30, seed=7, pause=0.15):
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    rows = [probe(session, *case, pause) for case in sample(release, count, seed)]
    with Path(out).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    pattern = collections.Counter(
        (r["submission"], *(r[f"offset_{k:+d}"] for k in OFFSETS)) for r in rows
    )
    for key, n in sorted(pattern.items()):
        print(*key, n)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path, help="Directory with accounts-*.csv")
    parser.add_argument("--out", type=Path, default=HERE / "layout.csv")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--pause", type=float, default=0.15)
    args = parser.parse_args()
    run(args.release, args.out, args.count, args.seed, args.pause)
