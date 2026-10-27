"""Month-over-month change log of filings and lookup status, shaped like an update feed."""

import csv
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .attribution import NOTICE, data_provenance
from .client import SourceError
from .export import DEFAULT_ASSET_BYTES, flatten, sha256_file, write_csv

SCHEMA = "regnskap-changelog-csv/v1"
COLUMNS = [
    "event_id",
    "release",
    "orgnr",
    "regnskapstype",
    "fiscal_year",
    "endringstype",
    "journalnr_old",
    "journalnr_new",
    "id_old",
    "id_new",
    "op",
    "path",
    "old_value",
    "new_value",
]
STATUS_FIELDS = [
    "outcome",
    "http_status",
    "message",
    "organisasjonsform",
    "latest_filing_year",
    "register_status",
    "register_deleted_date",
]
IDENTITY = {"id", "journalnr"}
WINDOW_YEARS = 3

csv.field_size_limit(sys.maxsize)


def text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def read_manifest(directory):
    path = Path(directory) / "manifest.json"
    if not path.is_file():
        raise SourceError(f"Release directory has no manifest: {directory}")
    manifest = json.loads(path.read_text())
    if manifest.get("format_version") != 1:
        raise SourceError("Unsupported release format")
    return manifest


def release_files(directory, manifest, table):
    """Resolve and checksum-verify one dataset table's CSV files from a release manifest."""
    directory = Path(directory)
    dataset = manifest.get("dataset") or {}
    names = (dataset.get(table) or {}).get("files") or []
    paths = []
    for name in names:
        if Path(name).name != name:
            raise SourceError("Unsafe release asset filename")
        path = directory / name
        asset = (manifest.get("assets") or {}).get(name)
        if asset and sha256_file(path) != asset["sha256"]:
            raise SourceError(f"Checksum mismatch: {name}")
        paths.append(path)
    return paths


def load_release(db, side, directory, skip_identical_to=None):
    """Load one release; JSON of filings identical to the other side is not kept."""
    manifest = read_manifest(directory)
    other = None
    if skip_identical_to:
        other = {
            (row[0], row[1], row[2], row[3]): (row[4], row[5])
            for row in db.execute(
                f"SELECT orgnr, regnskapstype, fiscal_year, fra_dato, id, sha256 "
                f"FROM {skip_identical_to}_filings"
            )
        }
    db.execute(
        f"""
        CREATE TABLE {side}_filings (
            orgnr TEXT NOT NULL, regnskapstype TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
            fra_dato TEXT NOT NULL, id INTEGER NOT NULL, journalnr TEXT NOT NULL,
            sha256 TEXT NOT NULL, json TEXT NOT NULL,
            PRIMARY KEY (orgnr, regnskapstype, fiscal_year, fra_dato)
        )
        """
    )
    db.execute(
        f"""
        CREATE TABLE {side}_obs (
            orgnr TEXT PRIMARY KEY, outcome TEXT, http_status TEXT, message TEXT,
            organisasjonsform TEXT, latest_filing_year TEXT, register_status TEXT,
            register_deleted_date TEXT
        )
        """
    )
    # Status columns introduced after a release was published are not changes.
    db.execute(f"CREATE TABLE {side}_columns (name TEXT PRIMARY KEY)")
    try:
        with db:
            _load_tables(db, side, directory, manifest, other)
    except sqlite3.IntegrityError as exc:
        raise SourceError(f"Duplicate filing key in {directory}: {exc}") from exc
    return manifest


def _load_tables(db, side, directory, manifest, other):
    for path in release_files(directory, manifest, "accounts"):
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                filing = json.loads(row["_meta.filing_json"])
                key = (
                    row["_meta.orgnr"],
                    filing["regnskapstype"],
                    int(row["_meta.fiscal_year"]),
                    filing["regnskapsperiode"]["fraDato"],
                )
                identity = (filing["id"], row["_meta.filing_sha256"])
                body = "" if other is not None and other.get(key) == identity else None
                db.execute(
                    f"INSERT INTO {side}_filings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        *key,
                        filing["id"],
                        str(filing.get("journalnr", "")),
                        row["_meta.filing_sha256"],
                        row["_meta.filing_json"] if body is None else body,
                    ),
                )
    for path in release_files(directory, manifest, "observations"):
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            db.executemany(
                f"INSERT OR IGNORE INTO {side}_columns VALUES (?)",
                [(name,) for name in reader.fieldnames if name in STATUS_FIELDS],
            )
            for row in reader:
                db.execute(
                    f"INSERT INTO {side}_obs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (row["orgnr"], *[row.get(field) or "" for field in STATUS_FIELDS]),
                )


def field_changes(old, new):
    before = {k: v for k, v in flatten(old).items() if k not in IDENTITY}
    after = {k: v for k, v in flatten(new).items() if k not in IDENTITY}
    for path in sorted(set(before) | set(after)):
        if path not in before:
            yield "add", path, None, after[path]
        elif path not in after:
            yield "remove", path, before[path], None
        elif before[path] != after[path]:
            yield "replace", path, before[path], after[path]


class Events:
    """Numbers transitions and counts them; rows are handed to the caller one by one."""

    def __init__(self, release, first_id):
        self.release = release
        self.next_id = first_id
        self.rows = []
        self.counts = {}

    def drain(self):
        rows, self.rows = self.rows, []
        return rows

    def event(self, orgnr, endringstype, operations, *, key=None, old=None, new=None):
        event_id = self.next_id
        self.next_id += 1
        self.counts[endringstype] = self.counts.get(endringstype, 0) + 1
        regnskapstype, fiscal_year = key or ("", "")
        base = {
            "event_id": event_id,
            "release": self.release,
            "orgnr": orgnr,
            "regnskapstype": regnskapstype,
            "fiscal_year": fiscal_year,
            "endringstype": endringstype,
            "journalnr_old": old["journalnr"] if old else "",
            "journalnr_new": new["journalnr"] if new else "",
            "id_old": old["id"] if old else "",
            "id_new": new["id"] if new else "",
        }
        if not operations:
            operations = [("", "", None, None)]
        for op, path, old_value, new_value in operations:
            self.rows.append(
                {
                    **base,
                    "op": op,
                    "path": path,
                    "old_value": text(old_value),
                    "new_value": text(new_value),
                }
            )


def status_events(events, orgnr, prior, current, fields=STATUS_FIELDS):
    if prior is None and current is None:
        return
    if prior is None:
        operations = [("add", f, None, current[f]) for f in fields if current[f]]
    elif current is None:
        operations = [("remove", f, prior[f], None) for f in fields if prior[f]]
    else:
        operations = [
            ("replace", f, prior[f], current[f]) for f in fields if prior[f] != current[f]
        ]
    if operations:
        events.event(orgnr, "Status", operations)


def filing_events(events, orgnr, prior, current):
    """Match filings of one organisation across releases and emit transitions."""
    prior_only = {k: v for k, v in prior.items() if k not in current}
    current_only = {k: v for k, v in current.items() if k not in prior}
    for key in sorted(prior_only):
        old = prior_only[key]
        moved = next(
            (
                k
                for k in sorted(current_only)
                if k[0] == key[0] and current_only[k]["journalnr"] == old["journalnr"]
            ),
            None,
        )
        if moved is None:
            continue
        new = current_only.pop(moved)
        del prior_only[key]
        events.event(
            orgnr,
            "KeyChanged",
            list(field_changes(old["filing"], new["filing"])),
            key=moved[:2],
            old=old,
            new=new,
        )
    for key in sorted(set(prior) & set(current)):
        old, new = prior[key], current[key]
        if old["sha256"] == new["sha256"] and old["id"] == new["id"]:
            continue
        if old["journalnr"] != new["journalnr"] or old["id"] != new["id"]:
            kind = "Resubmitted"
        else:
            kind = "Revised"
        operations = list(field_changes(old["filing"], new["filing"]))
        events.event(orgnr, kind, operations, key=key[:2], old=old, new=new)
    newest = {}
    for key in current:
        newest[key[0]] = max(newest.get(key[0], 0), key[1])
    for key in sorted(prior_only):
        old = prior_only[key]
        aged = key[0] in newest and key[1] < newest[key[0]] - (WINDOW_YEARS - 1)
        events.event(
            orgnr,
            "AgedOut" if aged else "Sletting",
            [("remove", "", old["sha256"], None)],
            key=key[:2],
            old=old,
        )
    for key in sorted(current_only):
        new = current_only[key]
        events.event(orgnr, "Ny", [("add", "", None, new["sha256"])], key=key[:2], new=new)


def filings_of(db, side, orgnr):
    out = {}
    for row in db.execute(
        f"SELECT * FROM {side}_filings WHERE orgnr=? ORDER BY regnskapstype, fiscal_year, fra_dato",
        (orgnr,),
    ):
        out[(row["regnskapstype"], row["fiscal_year"], row["fra_dato"])] = {
            "id": row["id"],
            "journalnr": row["journalnr"],
            "sha256": row["sha256"],
            "filing": json.loads(row["json"]) if row["json"] else None,
        }
    return out


def observation_of(db, side, orgnr):
    row = db.execute(f"SELECT * FROM {side}_obs WHERE orgnr=?", (orgnr,)).fetchone()
    return dict(row) if row else None


def status_fields(db):
    present = [
        {row[0] for row in db.execute(f"SELECT name FROM {side}_columns")}
        for side in ("prior", "current")
    ]
    return [f for f in STATUS_FIELDS if f in present[0] and f in present[1]]


def diff_releases(db, events, sample=False):
    """Yield change rows organisation by organisation; `events` keeps the counts."""
    fields = status_fields(db)
    if sample:
        # A sample compares only what it fetched; an unfinished lookup has nothing to say.
        query = "SELECT orgnr FROM current_obs WHERE outcome != 'pending' ORDER BY orgnr"
    else:
        query = """
            SELECT orgnr FROM prior_obs UNION SELECT orgnr FROM current_obs
            UNION SELECT orgnr FROM prior_filings UNION SELECT orgnr FROM current_filings
            ORDER BY orgnr
        """
    for (orgnr,) in db.execute(query).fetchall():
        status_events(
            events,
            orgnr,
            observation_of(db, "prior", orgnr),
            observation_of(db, "current", orgnr),
            fields,
        )
        filing_events(
            events, orgnr, filings_of(db, "prior", orgnr), filings_of(db, "current", orgnr)
        )
        yield from events.drain()


def read_rows(directory, manifest, table):
    for path in release_files(directory, manifest, table):
        with path.open(newline="", encoding="utf-8") as stream:
            yield from csv.DictReader(stream)


def previous_cumulative(directory, prior_cycle):
    """The previous change log's manifest and highest event id, read without buffering rows."""
    if directory is None:
        return None, 0
    manifest = read_manifest(directory)
    if manifest.get("kind") != "changelog":
        raise SourceError("Previous changelog release has the wrong kind")
    if manifest.get("cycle") != prior_cycle:
        raise SourceError(
            f"Previous change log covers {manifest.get('cycle')}, not {prior_cycle}; "
            "the cumulative log would have a gap"
        )
    last = 0
    for row in read_rows(directory, manifest, "cumulative"):
        last = max(last, int(row["event_id"]))
    return manifest, last


def build_changelog(
    prior_dir,
    current_dir,
    destination,
    *,
    previous_changelog=None,
    sample=False,
    max_asset_bytes=DEFAULT_ASSET_BYTES,
):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise SourceError("Changelog output directory must be empty to avoid mixing runs")
    with tempfile.TemporaryDirectory(prefix="brreg-changelog-") as tmp:
        db = sqlite3.connect(Path(tmp) / "diff.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            current = load_release(db, "current", current_dir)
            prior = load_release(db, "prior", prior_dir, skip_identical_to="current")
            if prior.get("kind") != "data" or current.get("kind") != "data":
                raise SourceError("Change logs compare two data releases")
            if not current.get("cycle") or not prior.get("cycle"):
                raise SourceError("Both releases need a cycle")
            if prior["cycle"] > current["cycle"] or (
                prior["cycle"] == current["cycle"] and not sample
            ):
                raise SourceError("The prior release must be an earlier cycle")
            cycle = current["cycle"]
            history, last_id = previous_cumulative(previous_changelog, prior["cycle"])
            events = Events(cycle, last_id + 1)
            delta = write_csv(
                diff_releases(db, events, sample=sample),
                COLUMNS,
                destination,
                f"changes-{cycle}",
                max_asset_bytes,
            )
        finally:
            db.close()
    delta_manifest = {"dataset": {"delta": delta}, "assets": {}}

    def cumulative_rows():
        if history is not None:
            yield from read_rows(previous_changelog, history, "cumulative")
        yield from read_rows(destination, delta_manifest, "delta")

    cumulative = write_csv(cumulative_rows(), COLUMNS, destination, "changes", max_asset_bytes)
    (destination / "DATA_NOTICE.md").write_text(NOTICE, encoding="utf-8")
    manifest = {
        "format_version": 1,
        "software_version": __version__,
        "provenance": data_provenance(),
        "created_at": datetime.now(UTC).isoformat(),
        "kind": "changelog",
        "cycle": cycle,
        "prior_cycle": prior["cycle"],
        "sample": sample,
        "complete": not sample,
        "events": events.counts,
        "dataset": {
            "schema_version": SCHEMA,
            "format": "csv",
            "encoding": "utf-8",
            "delimiter": ",",
            "grain": "one row per field operation; rows of one transition share event_id",
            "columns": COLUMNS,
            "endringstyper": [
                "Ny",
                "Resubmitted",
                "Revised",
                "KeyChanged",
                "AgedOut",
                "Sletting",
                "Status",
            ],
            "delta": delta,
            "cumulative": cumulative,
        },
        "assets": {},
    }
    for path in sorted(destination.iterdir()):
        manifest["assets"][path.name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "parts": [
                {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            ],
        }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with (destination / "SHA256SUMS").open("w") as out:
        for path in sorted(destination.iterdir()):
            if path.name != "SHA256SUMS":
                out.write(f"{sha256_file(path)}  {path.name}\n")
    return manifest
