"""Month-over-month change log of regnskap and lookup status, shaped like an update feed."""

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

SCHEMA = "regnskap-changelog-csv/v2"
COLUMNS = [
    "event_id",
    "release",
    "orgnr",
    "fiscal_year",
    "endringstype",
    "journalnr_old",
    "journalnr_new",
    "konsern_old",
    "konsern_new",
    "regnskapstype",
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


def organisation_table(manifest):
    """Releases before 0.8.0 call the per-organisation table `observations`."""
    dataset = manifest.get("dataset") or {}
    return "organisations" if "organisations" in dataset else "observations"


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
    for path in release_files(directory, manifest, organisation_table(manifest)):
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            db.executemany(
                f"INSERT OR IGNORE INTO {side}_columns VALUES (?)",
                [(name,) for name in reader.fieldnames if name in STATUS_FIELDS],
            )
            for row in reader:
                # Organisations whose accounts were not requested have no lookup to compare.
                if row.get("accounts_requested") == "false":
                    continue
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
        self.leftover_konsern = 0

    def drain(self):
        rows, self.rows = self.rows, []
        return rows

    def event(self, orgnr, endringstype, parts, *, fiscal_year="", old=None, new=None):
        event_id = self.next_id
        self.next_id += 1
        self.counts[endringstype] = self.counts.get(endringstype, 0) + 1
        base = {
            "event_id": event_id,
            "release": self.release,
            "orgnr": orgnr,
            "fiscal_year": fiscal_year,
            "endringstype": endringstype,
            "journalnr_old": old["journalnr"] if old else "",
            "journalnr_new": new["journalnr"] if new else "",
            "konsern_old": text(old["konsern"] is not None) if old else "",
            "konsern_new": text(new["konsern"] is not None) if new else "",
        }
        for regnskapstype, before, after, operations in parts:
            for op, path, old_value, new_value in operations or [("", "", None, None)]:
                self.rows.append(
                    {
                        **base,
                        "regnskapstype": regnskapstype,
                        "id_old": before["id"] if before else "",
                        "id_new": after["id"] if after else "",
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
        events.event(orgnr, "Status", [("", None, None, operations)])


def regnskap_of(filings):
    """One regnskap per SELSKAP row, with the KONSERN row submitted on the same journalnr.

    A KONSERN row on any other journalnr belongs to an earlier submission of that year and is
    returned separately.
    """
    selskap = {key[1:]: row for key, row in filings.items() if key[0] == "SELSKAP"}
    journalnr = {row["journalnr"] for row in selskap.values()}
    konsern = {row["journalnr"]: row for key, row in filings.items() if key[0] == "KONSERN"}
    regnskap = {
        key: {**row, "konsern": konsern.get(row["journalnr"])} for key, row in selskap.items()
    }
    return regnskap, [row for nr, row in konsern.items() if nr not in journalnr]


def parts_of(old, new):
    """Field operations for the SELSKAP part and the KONSERN part of one regnskap."""
    parts = []
    pairs = (
        ("SELSKAP", old, new),
        ("KONSERN", old and old["konsern"], new and new["konsern"]),
    )
    for regnskapstype, before, after in pairs:
        if before is None and after is None:
            continue
        if before is None:
            operations = [("add", "", None, after["sha256"])]
        elif after is None:
            operations = [("remove", "", before["sha256"], None)]
        elif before["sha256"] == after["sha256"]:
            operations = []
        else:
            operations = list(field_changes(before["filing"], after["filing"]))
        parts.append((regnskapstype, before, after, operations))
    return parts


def identity(regnskap):
    konsern = regnskap["konsern"]
    return (
        regnskap["journalnr"],
        regnskap["id"],
        regnskap["sha256"],
        konsern and (konsern["id"], konsern["sha256"]),
    )


def resubmitted(old, new):
    ids = lambda r: (r["journalnr"], r["id"], r["konsern"] and r["konsern"]["id"])
    return ids(old) != ids(new)


def filing_events(events, orgnr, prior, current):
    """Match the regnskap of one organisation across releases and emit transitions."""
    prior, _ = regnskap_of(prior)
    current, leftover = regnskap_of(current)
    events.leftover_konsern += len(leftover)
    prior_only = {k: v for k, v in prior.items() if k not in current}
    current_only = {k: v for k, v in current.items() if k not in prior}
    for key in sorted(prior_only):
        old = prior_only[key]
        moved = next(
            (k for k in sorted(current_only) if current_only[k]["journalnr"] == old["journalnr"]),
            None,
        )
        if moved is None:
            continue
        new = current_only.pop(moved)
        del prior_only[key]
        events.event(
            orgnr, "KeyChanged", parts_of(old, new), fiscal_year=moved[0], old=old, new=new
        )
    # A resubmission that corrects the period start keeps its fiscal year but not its full
    # key; pair it instead of reporting a deletion and a new regnskap.
    for key in sorted(prior_only):
        same_year = [k for k in sorted(current_only) if k[0] == key[0]]
        if len(same_year) != 1 or sum(k[0] == key[0] for k in prior_only) != 1:
            continue
        old, new = prior_only.pop(key), current_only.pop(same_year[0])
        events.event(
            orgnr,
            "Resubmitted" if resubmitted(old, new) else "Revised",
            parts_of(old, new),
            fiscal_year=key[0],
            old=old,
            new=new,
        )
    for key in sorted(set(prior) & set(current)):
        old, new = prior[key], current[key]
        if identity(old) == identity(new):
            continue
        events.event(
            orgnr,
            "Resubmitted" if resubmitted(old, new) else "Revised",
            parts_of(old, new),
            fiscal_year=key[0],
            old=old,
            new=new,
        )
    # The API returns the latest three fiscal years, so the oldest regnskap leaves when a
    # newer year arrives.
    newest = max((key[0] for key in current), default=None)
    for key in sorted(prior_only):
        old = prior_only[key]
        aged = newest is not None and key[0] < newest - (WINDOW_YEARS - 1)
        events.event(
            orgnr,
            "AgedOut" if aged else "Sletting",
            parts_of(old, None),
            fiscal_year=key[0],
            old=old,
        )
    for key in sorted(current_only):
        new = current_only[key]
        events.event(orgnr, "Ny", parts_of(None, new), fiscal_year=key[0], new=new)
    konsern_ended(events, orgnr, prior, current)


def konsern_ended(events, orgnr, prior, current):
    """A company that filed consolidated accounts for one year and none for the next.

    Logged when the later year first appears. A konsernregnskap that leaves an existing year
    is a resubmission and is logged there, with `konsern_old` true and `konsern_new` false.
    """
    konsern = {key[0] for side in (prior, current) for key, r in side.items() if r["konsern"]}
    prior_years = {key[0] for key in prior}
    for key in sorted(current):
        year, new = key[0], current[key]
        if new["konsern"] or year in prior_years or year - 1 not in konsern:
            continue
        parent = ((new["filing"] or {}).get("virksomhet") or {}).get("morselskap")
        operations = [
            ("replace", "konsernregnskap.last_fiscal_year", year - 1, None),
            ("replace", "virksomhet.morselskap", None, parent),
        ]
        events.event(
            orgnr,
            "KonsernEnded",
            [("SELSKAP", None, new, operations)],
            fiscal_year=year,
            new=new,
        )


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
    if (manifest.get("dataset") or {}).get("schema_version") != SCHEMA:
        raise SourceError(
            "Previous change log has another layout; rebuild it from the data releases"
        )
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
        "konsern_rows_from_earlier_submissions": events.leftover_konsern,
        "dataset": {
            "schema_version": SCHEMA,
            "format": "csv",
            "encoding": "utf-8",
            "delimiter": ",",
            "grain": "one row per field operation; rows of one transition share event_id",
            "unit": "one regnskap: an organisation and fiscal year, identified by the "
            "journalnr of its SELSKAP row, with the KONSERN row on the same journalnr",
            "columns": COLUMNS,
            "endringstyper": [
                "Ny",
                "Resubmitted",
                "Revised",
                "KeyChanged",
                "AgedOut",
                "Sletting",
                "KonsernEnded",
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
