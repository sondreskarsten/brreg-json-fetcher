"""Collect signals daily; issue account requests only for queued load work."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from itertools import islice

from .announcements import announcements_for_day
from .client import Client, SourceError

log = logging.getLogger(__name__)


def collect(
    state,
    client,
    day,
    *,
    lookback=7,
    workers=4,
    max_entities=0,
    max_seconds=0,
    reconcile=False,
    account_client_factory=Client,
):
    previous = state.get("entities_date")
    if previous and day.isoformat() < previous:
        raise SourceError("Cannot move the collection date behind the stored entity snapshot")
    if previous != day.isoformat():
        count = state.sync_entities(client.entities(), day.isoformat())
        log.info("Read %s entity records", count)

    last = state.get("announcements_through")
    start = (date.fromisoformat(last) if last else day) - timedelta(days=lookback)
    while start <= day:
        signals = announcements_for_day(client, start)
        state.add_announcements(signals, start.isoformat())
        log.info("%s: %s category-70 announcements", start, len(signals))
        start += timedelta(days=1)

    new_loads = state.schedule(client.loads(), reconcile=reconcile)
    log.info(
        "New load files: %s; queued entities: %s", new_loads, state.summary()["queued_entities"]
    )
    report = {
        "new_loads": new_loads,
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

    # Snapshot this run's queue: failures are tried once per invocation after HTTP
    # retries, and work beyond the budget survives in SQLite for the next run.
    todo = iter(list(state.todo()))
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            if max_seconds and time.monotonic() - started >= max_seconds:
                break
            remaining = max_entities - report["attempted"] if max_entities else workers * 4
            batch = list(islice(todo, max(0, min(workers * 4, remaining))))
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

        state.set("last_run", json.dumps(report, sort_keys=True))
    return report
