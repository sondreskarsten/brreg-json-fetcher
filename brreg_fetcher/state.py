"""Frozen monthly seeds, resumable queues, and lossless response history."""

import gzip
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .client import SourceError, decode_filings, unsupported_plan

SCHEMA_VERSION = "3"
UNIVERSE_VERSION = "as-asa-filed-v1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class State:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entities (
                orgnr TEXT PRIMARY KEY, year INTEGER, active INTEGER NOT NULL,
                observed_on TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS work (
                orgnr TEXT PRIMARY KEY, generation TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, error TEXT
            );
            CREATE TABLE IF NOT EXISTS responses (
                sha256 TEXT PRIMARY KEY, body_gzip BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                seq INTEGER PRIMARY KEY, orgnr TEXT NOT NULL, observed_at TEXT NOT NULL,
                generation TEXT NOT NULL, status INTEGER NOT NULL, sha256 TEXT NOT NULL,
                message TEXT NOT NULL, new_ids INTEGER NOT NULL, changed_ids INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS observations_org ON observations(orgnr);
            CREATE TABLE IF NOT EXISTS filings (
                orgnr TEXT NOT NULL, id INTEGER NOT NULL, regnskapstype TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                json TEXT NOT NULL, sha256 TEXT NOT NULL,
                PRIMARY KEY(orgnr, id)
            );
            CREATE TABLE IF NOT EXISTS current_filings (
                orgnr TEXT NOT NULL, id INTEGER NOT NULL, PRIMARY KEY(orgnr, id)
            );
        """)
        existing = self.get("schema_version")
        if existing not in (None, "1", "2", SCHEMA_VERSION):
            raise SourceError(f"Unsupported checkpoint schema {existing}")
        with self.db:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(entities)")}
            if "organisasjonsform" not in columns:
                self.db.execute("ALTER TABLE entities ADD COLUMN organisasjonsform TEXT")
                # Old checkpoints did not capture legal form; refresh before fetching.
                self.db.execute("DELETE FROM meta WHERE key='entities_date'")
            if existing in ("1", "2"):
                self.db.execute("DROP TABLE IF EXISTS signals")
                self.db.execute("DROP TABLE IF EXISTS loads")
                self.db.execute("DELETE FROM work")
                self.db.execute(
                    "DELETE FROM meta WHERE key IN ('entities_date', 'announcements_through', 'generation')"
                )
            self.set("schema_version", SCHEMA_VERSION)

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    def sync_entities(self, records, day, cycle=None):
        """Commit a new entity snapshot only after the entire download parses."""
        self.db.execute("DROP TABLE IF EXISTS temp.incoming")
        self.db.execute(
            "CREATE TEMP TABLE incoming (orgnr TEXT PRIMARY KEY, year INTEGER, organisasjonsform TEXT)"
        )
        count = 0
        try:
            with self.db:
                for entity in records:
                    orgnr = str(entity.get("organisasjonsnummer", ""))
                    year = str(entity.get("sisteInnsendteAarsregnskap") or "").strip()
                    # The public JSON property is camelCase; accept the source note's
                    # lowercase spelling for supplied historical snapshots too.
                    if "sisteInnsendteAarsregnskap" not in entity:
                        year = str(entity.get("sisteinnsendteaarsregnskap") or "").strip()
                    if year.upper() in ("NA", "N/A", "NULL", "NAN"):
                        year = ""
                    form = (entity.get("organisasjonsform") or {}).get("kode")
                    if not re.fullmatch(r"\d{9}", orgnr):
                        raise SourceError("Entity snapshot contains an invalid orgnr")
                    if year and not re.fullmatch(r"[1-9]\d{3}", year):
                        raise SourceError(f"Invalid latest filing year for {orgnr}")
                    self.db.execute(
                        "INSERT INTO incoming VALUES (?, ?, ?)",
                        (orgnr, int(year) if year else None, form),
                    )
                    count += 1
                if count == 0:
                    raise SourceError("Refusing an empty entity snapshot")
                self.db.execute("UPDATE entities SET active=0")
                self.db.execute(
                    """
                    INSERT INTO entities(orgnr, year, active, observed_on, organisasjonsform)
                    SELECT orgnr, year,
                        year IS NOT NULL AND coalesce(organisasjonsform IN ('AS', 'ASA'), 0),
                        ?, organisasjonsform FROM incoming WHERE 1
                    ON CONFLICT(orgnr) DO UPDATE SET year=excluded.year, active=excluded.active,
                        observed_on=excluded.observed_on, organisasjonsform=excluded.organisasjonsform
                """,
                    (day,),
                )
                self.db.execute(
                    "DELETE FROM work WHERE orgnr NOT IN (SELECT orgnr FROM entities WHERE active=1)"
                )
                self.db.execute(
                    "DELETE FROM current_filings WHERE orgnr NOT IN (SELECT orgnr FROM entities WHERE active=1)"
                )
                self.set("entities_date", day)
                self.set("universe_version", UNIVERSE_VERSION)
                if cycle:
                    eligible = self.db.execute(
                        "SELECT count(*) FROM entities WHERE active=1"
                    ).fetchone()[0]
                    if not eligible:
                        raise SourceError("Refusing to start a month with an empty AS/ASA seed")
                    self.db.execute("DELETE FROM work")
                    self.db.execute("DELETE FROM current_filings")
                    self.db.execute(
                        "INSERT INTO work(orgnr, generation) SELECT orgnr, ? FROM entities WHERE active=1",
                        (cycle,),
                    )
                    self.db.execute(
                        "DELETE FROM meta WHERE key IN ('cycle_completed_at', 'cycle_published', 'seed_release_tag', 'seed_sha256')"
                    )
                    self.set("cycle", cycle)
                    self.set("cycle_started_at", day)
                    self.set("generation", cycle)
        except (sqlite3.IntegrityError, AttributeError) as exc:
            raise SourceError("Invalid or duplicate entity in bulk download") from exc
        return count

    def start_cycle(self, records, day):
        cycle = day[:7]
        previous = self.get("cycle")
        if previous:
            if cycle <= previous:
                raise SourceError("A month can only be seeded once; resume its existing queue")
            if not self.get("cycle_completed_at") or self.summary()["queued_entities"]:
                raise SourceError("Finish the active month before downloading a new seed")
        return self.sync_entities(records, day, cycle=cycle)

    def todo(self):
        return self.db.execute("SELECT orgnr, generation FROM work ORDER BY attempts, orgnr")

    def record(self, orgnr, generation, response, now):
        filings = decode_filings(response.body, orgnr) if response.status == 200 else []
        digest = hashlib.sha256(response.body).hexdigest()
        new_ids = changed_ids = 0
        unsupported = unsupported_plan(response.status, response.message)
        terminal = response.status in (200, 404) or unsupported
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO responses VALUES (?, ?)",
                (digest, gzip.compress(response.body, mtime=0)),
            )
            if response.status in (200, 404):
                self.db.execute("DELETE FROM current_filings WHERE orgnr=?", (orgnr,))
            for filing in filings:
                payload = canonical(filing)
                sha = hashlib.sha256(payload.encode()).hexdigest()
                old = self.db.execute(
                    "SELECT sha256 FROM filings WHERE orgnr=? AND id=?", (orgnr, filing["id"])
                ).fetchone()
                new_ids += old is None
                changed_ids += old is not None and old[0] != sha
                self.db.execute(
                    """
                    INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(orgnr, id) DO UPDATE SET last_seen=excluded.last_seen,
                        json=excluded.json, sha256=excluded.sha256
                """,
                    (
                        orgnr,
                        filing["id"],
                        filing["regnskapstype"],
                        int(filing["regnskapsperiode"]["tilDato"][:4]),
                        now,
                        now,
                        payload,
                        sha,
                    ),
                )
                self.db.execute("INSERT INTO current_filings VALUES (?, ?)", (orgnr, filing["id"]))
            self.db.execute(
                """
                INSERT INTO observations(orgnr, observed_at, generation, status, sha256, message, new_ids, changed_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    orgnr,
                    now,
                    generation,
                    response.status,
                    digest,
                    response.message,
                    new_ids,
                    changed_ids,
                ),
            )
            if terminal:
                self.db.execute("DELETE FROM work WHERE orgnr=?", (orgnr,))
            else:
                self.db.execute(
                    "UPDATE work SET attempts=attempts+1, error=? WHERE orgnr=?",
                    (response.message, orgnr),
                )
        return {
            "new_ids": new_ids,
            "changed_ids": changed_ids,
            "retry": not terminal,
            "unsupported": unsupported,
        }

    def failure(self, orgnr, message):
        with self.db:
            self.db.execute(
                "UPDATE work SET attempts=attempts+1, error=? WHERE orgnr=?",
                (message[:2000], orgnr),
            )

    def summary(self):
        queries = {
            "eligible_entities": "SELECT count(*) FROM entities WHERE active=1",
            "queued_entities": "SELECT count(*) FROM work",
            "historical_filings": "SELECT count(*) FROM filings",
            "current_filings": "SELECT count(*) FROM current_filings",
            "observations": "SELECT count(*) FROM observations",
        }
        return {k: self.db.execute(q).fetchone()[0] for k, q in queries.items()}

    def backup(self, destination):
        # SQLite backup includes committed WAL content; copying the .sqlite file does not.
        with sqlite3.connect(destination) as target:
            self.db.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
