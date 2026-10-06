"""Transactional checkpoints, pending signals, and lossless response history."""

import gzip
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .client import SourceError, decode_filings

SCHEMA_VERSION = "1"


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
            CREATE TABLE IF NOT EXISTS signals (
                kind TEXT NOT NULL, source_key TEXT NOT NULL, orgnr TEXT NOT NULL,
                signal_date TEXT NOT NULL, answered_by INTEGER,
                PRIMARY KEY(kind, source_key)
            );
            CREATE INDEX IF NOT EXISTS signals_org ON signals(orgnr, answered_by);
            CREATE TABLE IF NOT EXISTS loads (name TEXT PRIMARY KEY);
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
        if existing not in (None, SCHEMA_VERSION):
            raise SourceError(f"Unsupported checkpoint schema {existing}")
        with self.db:
            self.set("schema_version", SCHEMA_VERSION)

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    def sync_entities(self, records, day):
        """Commit a new entity snapshot only after the entire download parses."""
        self.db.execute("DROP TABLE IF EXISTS temp.incoming")
        self.db.execute("CREATE TEMP TABLE incoming (orgnr TEXT PRIMARY KEY, year INTEGER)")
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
                    if not re.fullmatch(r"\d{9}", orgnr):
                        raise SourceError("Entity snapshot contains an invalid orgnr")
                    if year and not re.fullmatch(r"[1-9]\d{3}", year):
                        raise SourceError(f"Invalid latest filing year for {orgnr}")
                    self.db.execute(
                        "INSERT INTO incoming VALUES (?, ?)", (orgnr, int(year) if year else None)
                    )
                    count += 1
                if count == 0:
                    raise SourceError("Refusing an empty entity snapshot")
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO signals(kind, source_key, orgnr, signal_date)
                    SELECT 'entity_year', i.orgnr || ':' || ? || ':' || i.year, i.orgnr, ?
                    FROM incoming i LEFT JOIN entities e USING(orgnr)
                    WHERE i.year IS NOT NULL AND (e.year IS NULL OR e.year != i.year)
                """,
                    (day, day),
                )
                self.db.execute("UPDATE entities SET active=0")
                self.db.execute(
                    """
                    INSERT INTO entities SELECT orgnr, year, year IS NOT NULL, ? FROM incoming WHERE 1
                    ON CONFLICT(orgnr) DO UPDATE SET year=excluded.year, active=excluded.active,
                        observed_on=excluded.observed_on
                """,
                    (day,),
                )
                self.db.execute(
                    "DELETE FROM work WHERE orgnr NOT IN (SELECT orgnr FROM entities WHERE active=1)"
                )
                self.set("entities_date", day)
        except (sqlite3.IntegrityError, AttributeError) as exc:
            raise SourceError("Invalid or duplicate entity in bulk download") from exc
        return count

    def add_announcements(self, announcements, day):
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO signals(kind, source_key, orgnr, signal_date) VALUES ('announcement_70', ?, ?, ?)",
                ((a.kid, a.orgnr, day) for a in announcements),
            )
            self.set("announcements_through", day)

    def answer_signals(self, orgnr=None):
        # A newly observed id can precede the signal by seven days, or arrive
        # later without a hard expiry. Same-id content updates do not answer it.
        sql = """
            UPDATE signals SET answered_by=(
                SELECT f.id FROM filings f WHERE f.orgnr=signals.orgnr
                  AND date(f.first_seen) >= date(signals.signal_date, '-7 days')
                ORDER BY f.first_seen, f.id LIMIT 1
            ) WHERE answered_by IS NULL
        """
        self.db.execute(sql + (" AND orgnr=?" if orgnr else ""), (orgnr,) if orgnr else ())

    def schedule(self, loads, reconcile=False):
        known = {r[0] for r in self.db.execute("SELECT name FROM loads")}
        new = loads - known
        with self.db:
            self.answer_signals()
            if not new:
                return 0
            generation = hashlib.sha256(canonical(sorted(loads)).encode()).hexdigest()
            where = (
                ""
                if reconcile
                else """
                AND (NOT EXISTS (SELECT 1 FROM observations o WHERE o.orgnr=e.orgnr)
                  OR EXISTS (SELECT 1 FROM signals s WHERE s.orgnr=e.orgnr AND s.answered_by IS NULL))
            """
            )
            self.db.execute(
                f"""
                INSERT INTO work(orgnr, generation)
                SELECT orgnr, ? FROM entities e WHERE active=1 {where}
                ON CONFLICT(orgnr) DO UPDATE SET generation=excluded.generation
            """,
                (generation,),
            )
            self.db.executemany(
                "INSERT OR IGNORE INTO loads VALUES (?)", ((name,) for name in loads)
            )
            self.set("generation", generation)
        return len(new)

    def todo(self):
        return self.db.execute("SELECT orgnr, generation FROM work ORDER BY attempts, orgnr")

    def record(self, orgnr, generation, response, now):
        filings = decode_filings(response.body, orgnr) if response.status == 200 else []
        digest = hashlib.sha256(response.body).hexdigest()
        new_ids = changed_ids = 0
        unsupported = (
            response.status == 500 and "oppstillingsplan som ikke er støttet" in response.message
        )
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
            self.answer_signals(orgnr)
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
            "pending_signals": "SELECT count(*) FROM signals WHERE answered_by IS NULL",
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
