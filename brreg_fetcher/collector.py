"""Start one fresh seed per month and resume it across runs and month boundaries."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from itertools import islice

from .client import Client, SourceError
from .export import sha256_file

log = logging.getLogger(__name__)


def collect(
    state,
    client,
    day,
    *,
    workers=4,
    max_entities=0,
    max_seconds=0,
    account_client_factory=Client,
):
    cycle = state.get("cycle")
    month = day.strftime("%Y-%m")
    if cycle and month < cycle:
        raise SourceError("Cannot run a date earlier than the active collection month")
    if not cycle or (cycle < month and state.get("cycle_completed_at")):
        count = state.start_cycle(client.entities(), day.isoformat())
        snapshot = getattr(client, "snapshot_path", None)
        if snapshot:
            with state.db:
                state.set("seed_sha256", sha256_file(snapshot))
        log.info(
            "New monthly seed: %s entity records, %s eligible",
            count,
            state.summary()["eligible_entities"],
        )
    log.info(
        "Month %s; queued entities: %s", state.get("cycle"), state.summary()["queued_entities"]
    )
    report = {
        "cycle": state.get("cycle"),
        "seed_date": state.get("entities_date"),
        "attempted": 0,
        "ok": 0,
        "not_found": 0,
        "unsupported": 0,
        "errors": 0,
        "new_ids": 0,
        "changed_ids": 0,
    }
    local = threading.local()

    def fetch(row):
        if not hasattr(local, "client"):
            local.client = account_client_factory()
        try:
            return row, local.client.accounts(row["orgnr"]), None
        except (SourceError, OSError, ValueError) as exc:
            return row, None, exc

    # Snapshot this segment's queue: failures are tried once per invocation after HTTP
    # retries, and work beyond the budget survives in SQLite for the next run.
    todo = iter(list(state.todo()))
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            if max_seconds and time.monotonic() - started >= max_seconds:
                break
            remaining = max_entities - report["attempted"] if max_entities else workers
            batch = list(islice(todo, max(0, min(workers, remaining))))
            if not batch:
                break
            for row, response, error in pool.map(fetch, batch):
                orgnr = row["orgnr"]
                report["attempted"] += 1
                try:
                    if error:
                        raise error
                    outcome = state.record(
                        orgnr, row["generation"], response, datetime.now(UTC).isoformat()
                    )
                    report["ok"] += response.status == 200
                    report["not_found"] += response.status == 404
                    for key in ("unsupported", "new_ids", "changed_ids"):
                        report[key] += outcome[key]
                    report["errors"] += outcome["retry"]
                except (SourceError, OSError, ValueError) as exc:
                    state.failure(orgnr, str(exc))
                    report["errors"] += 1
                    log.warning("%s: %s", orgnr, exc)
            log.info("Fetched %s, errors %s", report["attempted"], report["errors"])
    report.update(state.summary())
    report["complete"] = report["queued_entities"] == 0 and report["errors"] == 0
    report["date"] = day.isoformat()
    with state.db:
        import json

        if report["complete"] and not state.get("cycle_completed_at"):
            state.set("cycle_completed_at", datetime.now(UTC).isoformat())
        state.set("last_run", json.dumps(report, sort_keys=True))
    return report
