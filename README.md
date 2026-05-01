# brreg-json-fetcher

Cloud Run Job that fetches BRREG regnskap JSON for all orgnrs from the manifest of known orgnrs and stores them as a daily-partitioned immutable ledger on GCS.

## What it does

For each orgnr in the work list, calls
```
GET https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}
Accept: application/json
```
and stores the **full raw response array** at
```
gs://sondre_brreg_data/raw/brreg_regnskap_json/dt={YYYY-MM-DD}/{orgnr}.json
```

Each file preserves every submission (multiple `journalnr` per orgnr possible) and every year BRREG returned at fetch time. Daily snapshots — re-running on a new date produces a parallel `dt=` partition, no overwriting.

## Architecture

- **Worker-pool pattern**: 15 async workers per Cloud Run task pulling from an `asyncio.Queue`
- **Sync GCS calls wrapped in `asyncio.to_thread()`** so they don't block the event loop
- 8 Cloud Run tasks × 15 workers = **120 concurrent** at peak
- Sustained ~1,300 orgnrs/sec aggregate

### Why the `to_thread` wrapping matters

The first runner version had `out_blob.exists()` and `out_blob.upload_from_string()` called directly inside async coroutines. These are sync HTTP calls — they blocked the event loop while in flight. With 120 coroutines, only one could run at a time → effective parallelism collapsed to ~1 op/sec.

Wrapping with `asyncio.to_thread()` runs sync calls in the default thread pool executor, freeing the event loop to schedule other coroutines. This recovered the expected 1,300 ops/sec.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WORK_LIST_BLOB` | `sondre_brreg_data/raw/brreg_regnskap_json/work_list.json` | GCS path to JSON list of orgnrs |
| `OUT_PREFIX` | `sondre_brreg_data/raw/brreg_regnskap_json` | GCS prefix for output and state |
| `MAX_CONCURRENT` | `15` | async workers per task |
| `CHECKPOINT_EVERY` | `500` | log/state-save cadence |
| `SKIP_EXISTS_CHECK` | `0` | set `1` on first run to skip per-blob HEAD calls |
| `CLOUD_RUN_TASK_INDEX`, `CLOUD_RUN_TASK_COUNT` | (auto) | sharding |

## Storage layout

```
gs://sondre_brreg_data/raw/brreg_regnskap_json/
├── work_list.json                        # input: array of orgnrs
├── run_summary_{dt}.json                 # human-readable summary per run
├── state/dt={dt}/
│   └── state_task{NNN}.json              # per-task progress
└── dt={dt}/
    └── {orgnr}.json                       # raw BRREG response (per orgnr)
```

## First run results

| Metric | Value |
|---|---|
| Wall time | ~7 minutes |
| Orgnrs attempted | 510,513 |
| 200 OK | 471,962 (92.4%) |
| 404 | 37,318 (7.3%) |
| Fail (transient) | 1,233 (0.24%) |
| Total bytes | 620 MB |

The 7.3% with 404 status are orgnrs in the manifest that BRREG no longer recognises as having any registered regnskap (deletions, never-filed, etc.).

## Deployment

```bash
# Build the container
./scripts/build.py

# Create / update the Cloud Run Job
./scripts/deploy.py

# Execute
gcloud run jobs execute brreg-json-fetcher --region=europe-north1 --project=sondreskarsten-d7d14
```

## License

MIT
