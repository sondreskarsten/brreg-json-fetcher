"""Self-contained release assets and checksum-verified checkpoint restoration."""

import base64
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import __version__
from .client import SourceError
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


def parquet_record(row):
    result = flatten(row["filing"])
    result.update({f"_meta.{k}": v for k, v in row.items() if k != "filing"})
    result["_meta.filing_json"] = canonical(row["filing"])
    return result


def kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and -(2**63) <= value < 2**63:
        return "int"
    if isinstance(value, float):
        return "float"
    return "string"


def write_parquet(state, path):
    # Two streaming passes prevent Arrow from inferring field names only from
    # the first row and silently dropping leaves found in subsequent rows.
    kinds = {}
    for row in rows(state, current_only=True):
        for key, value in parquet_record(row).items():
            kinds.setdefault(key, set()).add(kind(value))
    if not kinds:
        kinds = {"_meta.orgnr": {"string"}, "_meta.filing_json": {"string"}}
    types = {}
    for key, options in sorted(kinds.items()):
        options = options - {"null"}
        if options == {"int"}:
            types[key] = pa.int64()
        elif options and options <= {"int", "float"}:
            types[key] = pa.float64()
        elif options == {"bool"}:
            types[key] = pa.bool_()
        else:
            types[key] = pa.string()
    schema = pa.schema(list(types.items()))
    with pq.ParquetWriter(path, schema, compression="snappy") as writer:
        batch = []
        for row in rows(state, current_only=True):
            rec = parquet_record(row)
            for key, typ in types.items():
                value = rec.get(key)
                if value is not None and pa.types.is_string(typ) and not isinstance(value, str):
                    rec[key] = canonical(value)
            batch.append(rec)
            if len(batch) == 2048:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch = []
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))


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

    if not checkpoint_only:
        for filename, current_only in [
            ("accounts.jsonl.gz", True),
            ("filings-history.jsonl.gz", False),
        ]:
            with gzip.open(destination / filename, "wt", encoding="utf-8") as out:
                for row in rows(state, current_only):
                    out.write(canonical(row) + "\n")
        write_parquet(state, destination / "accounts.parquet")
        for table in ("entities", "observations", "work"):
            with gzip.open(destination / f"{table}.jsonl.gz", "wt", encoding="utf-8") as out:
                for row in state.db.execute(f"SELECT * FROM {table}"):
                    out.write(canonical(dict(row)) + "\n")
        with gzip.open(destination / "seed.jsonl.gz", "wt", encoding="utf-8") as out:
            for row in state.db.execute(
                "SELECT orgnr, year, organisasjonsform FROM entities WHERE active=1 ORDER BY orgnr"
            ):
                out.write(canonical(dict(row)) + "\n")
        with gzip.open(destination / "responses.jsonl.gz", "wt", encoding="utf-8") as out:
            for row in state.db.execute("SELECT * FROM responses ORDER BY sha256"):
                out.write(
                    canonical(
                        {
                            "sha256": row["sha256"],
                            "body_base64": base64.b64encode(
                                gzip.decompress(row["body_gzip"])
                            ).decode("ascii"),
                        }
                    )
                    + "\n"
                )

    if snapshot_path:
        if state.get("seed_sha256") and sha256_file(snapshot_path) != state.get("seed_sha256"):
            raise SourceError("Entity download does not match this month's seed checksum")
        shutil.copyfile(snapshot_path, destination / "enheter.json.gz")

    report = json.loads(state.get("last_run", "{}"))
    manifest = {
        "format_version": 1,
        "software_version": __version__,
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
