"""Self-contained release assets and checksum-verified checkpoint restoration."""

import csv
import gzip
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .attribution import NOTICE, data_provenance
from .client import SourceError, unsupported_plan
from .state import SCHEMA_VERSION, canonical

CHUNK_BYTES = 1024 * 1024
DEFAULT_ASSET_BYTES = 1024 * 1024 * 1024


def flatten(value, prefix=""):
    """Retain every source leaf, including future fields and empty objects."""
    out = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict) and item:
            out.update(flatten(item, name))
        elif isinstance(item, (dict, list)):
            out[name] = canonical(item)
        else:
            out[name] = item
    return out


def rows(state, current_only=False):
    join = "JOIN current_filings c USING(orgnr, id)" if current_only else ""
    query = f"SELECT f.* FROM filings f {join} ORDER BY f.orgnr, f.id"
    for row in state.db.execute(query):
        yield {
            "orgnr": row["orgnr"],
            "fiscal_year": row["fiscal_year"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "filing_sha256": row["sha256"],
            "filing": json.loads(row["json"]),
        }


def csv_record(row):
    result = flatten(row["filing"])
    result.update({f"_meta.{k}": v for k, v in row.items() if k != "filing"})
    result["_meta.filing_json"] = canonical(row["filing"])
    return result


def write_csv(records, columns, destination, stem, max_bytes):
    """Split on record boundaries; every CSV is independently readable."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    header = buffer.getvalue().encode("utf-8")
    if len(header) > max_bytes:
        raise SourceError("CSV asset limit is smaller than its header")
    paths = []
    count = 0
    path = destination / f"{stem}.csv"
    out = path.open("wb")
    paths.append(path)
    out.write(header)
    size = len(header)
    try:
        for row in records:
            buffer.seek(0)
            buffer.truncate()
            writer.writerow(row)
            record = buffer.getvalue().encode("utf-8")
            if len(header) + len(record) > max_bytes:
                raise SourceError("One CSV record exceeds the asset limit")
            if size + len(record) > max_bytes:
                out.close()
                path = destination / f"{stem}-{len(paths) + 1:05d}.csv"
                out = path.open("wb")
                paths.append(path)
                out.write(header)
                size = len(header)
            out.write(record)
            size += len(record)
            count += 1
    finally:
        out.close()
        buffer.close()
    if len(paths) > 1:
        paths[0] = paths[0].rename(destination / f"{stem}-00001.csv")
    return {"rows": count, "columns": columns, "files": [p.name for p in paths]}


def export_csv(state, destination, max_bytes):
    # Discover columns over every current filing, including fields appearing late.
    columns = {"_meta.orgnr", "_meta.fiscal_year", "_meta.snapshot_date", "_meta.filing_json"}
    for row in rows(state, current_only=True):
        columns.update(csv_record(row))

    def records():
        for row in rows(state, current_only=True):
            record = csv_record(row)
            record["_meta.snapshot_date"] = state.get("entities_date", "")
            yield record

    accounts = write_csv(records(), sorted(columns), destination, "accounts", max_bytes)
    # One coverage row per seed entity, including absence, unsupported plans and
    # unfinished local runs. Historical observations never stand in for this month.
    query = """
        SELECT e.orgnr, e.organisasjonsform, e.year AS latest_filing_year,
               o.observed_at, o.status AS http_status, o.sha256 AS response_sha256,
               o.message, w.orgnr AS pending, w.error AS pending_error, r.body_gzip
        FROM entities e
        LEFT JOIN observations o ON o.seq = (
            SELECT max(seq) FROM observations WHERE orgnr=e.orgnr AND generation=?
        )
        LEFT JOIN work w ON w.orgnr=e.orgnr
        LEFT JOIN responses r ON r.sha256=o.sha256
        WHERE e.active=1 ORDER BY e.orgnr
    """

    def observations():
        for row in state.db.execute(query, (state.get("cycle"),)):
            record = dict(row)
            body = record.pop("body_gzip")
            status = record["http_status"]
            pending = record.pop("pending")
            message = record.pop("pending_error") or record["message"]
            record["message"] = message
            record["snapshot_date"] = state.get("entities_date", "")
            record["outcome"] = (
                "pending"
                if pending or status is None
                else "ok"
                if status == 200
                else "not_found"
                if status == 404
                else "unsupported"
                if unsupported_plan(status, message or "")
                else "error"
            )
            record["error_body"] = (
                gzip.decompress(body).decode("utf-8", errors="replace")
                if body is not None and status != 200
                else ""
            )
            yield record

    coverage = write_csv(
        observations(),
        [
            "orgnr",
            "snapshot_date",
            "organisasjonsform",
            "latest_filing_year",
            "observed_at",
            "http_status",
            "response_sha256",
            "outcome",
            "message",
            "error_body",
        ],
        destination,
        "observations",
        max_bytes,
    )
    return {
        "schema_version": "arsregnskap-nokkeltall-monthly-csv/v1",
        "format": "csv",
        "encoding": "utf-8",
        "delimiter": ",",
        "grain": "one row per returned regnskap",
        "snapshot_date": state.get("entities_date"),
        "accounts": accounts,
        "observations": coverage,
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_asset(path, max_bytes):
    if path.stat().st_size <= max_bytes:
        return [path]
    parts = []
    with path.open("rb") as source:
        index = 1
        while True:
            first = source.read(min(CHUNK_BYTES, max_bytes))
            if not first:
                break
            part = path.with_name(f"{path.name}.part{index:04d}")
            with part.open("wb") as dest:
                dest.write(first)
                left = max_bytes - len(first)
                while left:
                    chunk = source.read(min(CHUNK_BYTES, left))
                    if not chunk:
                        break
                    dest.write(chunk)
                    left -= len(chunk)
            parts.append(part)
            index += 1
    path.unlink()
    return parts


def export_release(
    state,
    destination,
    max_asset_bytes=DEFAULT_ASSET_BYTES,
    *,
    checkpoint_only=False,
    snapshot_path=None,
):
    if max_asset_bytes < 1:
        raise ValueError("Asset limit must be positive")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise SourceError("Release output directory must be empty to avoid mixing runs")
    with tempfile.TemporaryDirectory(prefix="brreg-export-") as tmp:
        checkpoint = Path(tmp) / "checkpoint.sqlite3"
        state.backup(checkpoint)
        with (
            checkpoint.open("rb") as source,
            gzip.open(destination / "checkpoint.sqlite3.gz", "wb", compresslevel=1) as out,
        ):
            shutil.copyfileobj(source, out, CHUNK_BYTES)

    dataset = None
    if not checkpoint_only:
        dataset = export_csv(state, destination, max_asset_bytes)

    if snapshot_path:
        if state.get("seed_sha256") and sha256_file(snapshot_path) != state.get("seed_sha256"):
            raise SourceError("Entity download does not match this month's seed checksum")
        shutil.copyfile(snapshot_path, destination / "enheter.json.gz")

    (destination / "DATA_NOTICE.md").write_text(NOTICE, encoding="utf-8")
    report = json.loads(state.get("last_run", "{}"))
    manifest = {
        "format_version": 1,
        "software_version": __version__,
        "provenance": data_provenance(),
        "created_at": datetime.now(UTC).isoformat(),
        "complete": bool(state.get("cycle_completed_at"))
        and state.summary()["queued_entities"] == 0,
        "kind": "checkpoint" if checkpoint_only else "data",
        "cycle": state.get("cycle"),
        "collection_started_at": state.get("cycle_started_at"),
        "collection_finished_at": state.get("cycle_completed_at"),
        "seed_sha256": state.get("seed_sha256"),
        "seed_release_tag": state.get("seed_release_tag"),
        "last_run": report,
        "counts": state.summary(),
        "entities_date": state.get("entities_date"),
        "generation": state.get("generation"),
        "universe": {"organisasjonsform": ["AS", "ASA"], "latest_accounts_year": "non-null"},
        "dataset": dataset,
        "assets": {},
    }
    for path in sorted(destination.iterdir()):
        name = path.name
        size, sha = path.stat().st_size, sha256_file(path)
        parts = split_asset(path, max_asset_bytes)
        manifest["assets"][name] = {
            "bytes": size,
            "sha256": sha,
            "parts": [
                {"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in parts
            ],
        }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with (destination / "SHA256SUMS").open("w") as out:
        for path in sorted(destination.iterdir()):
            if path.name != "SHA256SUMS":
                out.write(f"{sha256_file(path)}  {path.name}\n")
    return manifest


def restore_asset(source, name, destination):
    """Join and verify one logical asset without trusting filenames from a manifest."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise SourceError("Refusing to replace an existing asset")
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("format_version") != 1:
        raise SourceError("Unsupported release format")
    asset = manifest["assets"][name]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".brreg-asset-") as tmp:
        joined = Path(tmp) / "joined"
        with joined.open("wb") as out:
            for part in asset["parts"]:
                filename = part["name"]
                if Path(filename).name != filename or filename in (".", ".."):
                    raise SourceError("Unsafe release asset filename")
                path = source / filename
                if path.stat().st_size != part["bytes"] or sha256_file(path) != part["sha256"]:
                    raise SourceError(f"Checksum mismatch: {filename}")
                with path.open("rb") as stream:
                    shutil.copyfileobj(stream, out, CHUNK_BYTES)
        if joined.stat().st_size != asset["bytes"] or sha256_file(joined) != asset["sha256"]:
            raise SourceError("Asset checksum mismatch after joining parts")
        os.replace(joined, destination)


def restore_checkpoint(source, destination):
    destination = Path(destination)
    if destination.exists():
        raise SourceError("Refusing to replace an existing checkpoint")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".brreg-restore-") as tmp:
        compressed = Path(tmp) / "checkpoint.gz"
        restore_asset(source, "checkpoint.sqlite3.gz", compressed)
        restored = Path(tmp) / "checkpoint.sqlite3"
        with gzip.open(compressed, "rb") as stream, restored.open("wb") as out:
            shutil.copyfileobj(stream, out, CHUNK_BYTES)
        with sqlite3.connect(restored) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SourceError("Checkpoint failed SQLite integrity check")
            row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None or row[0] not in ("1", "2", SCHEMA_VERSION):
                raise SourceError("Unsupported checkpoint schema")
        os.replace(restored, destination)
