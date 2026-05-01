"""Cloud Run Job: fetch live BRREG regnskap JSON for all orgnrs in manifest.

Stores raw response bytes (full BRREG array) at:
  gs://sondre_brreg_data/raw/brreg_regnskap_json/dt={YYYY-MM-DD}/{orgnr}.json

Sharding: each task processes work_list[task_index::task_count].
"""
import asyncio
import aiohttp
import json
import os
import sys
import time
from datetime import datetime, timezone

import google.auth
from google.cloud import storage as gcs_storage

PROJECT_ID = 'sondreskarsten-d7d14'
BASE_URL = 'https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}'
RATE_LIMIT_MARKER = 'Too many requests'

WORK_LIST_BLOB = os.environ.get('WORK_LIST_BLOB',
                                'sondre_brreg_data/raw/brreg_regnskap_json/work_list.json')
OUT_PREFIX = os.environ.get('OUT_PREFIX',
                            'sondre_brreg_data/raw/brreg_regnskap_json')
MAX_CONCURRENT = int(os.environ.get('MAX_CONCURRENT', '20'))
CHECKPOINT_EVERY = int(os.environ.get('CHECKPOINT_EVERY', '500'))
TASK_INDEX = int(os.environ.get('CLOUD_RUN_TASK_INDEX', '0'))
TASK_COUNT = int(os.environ.get('CLOUD_RUN_TASK_COUNT', '1'))
SKIP_EXISTS_CHECK = os.environ.get('SKIP_EXISTS_CHECK', '0') == '1'

DT = datetime.now(timezone.utc).strftime('%Y-%m-%d')


def log(msg):
    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    print(f'[task{TASK_INDEX} {ts}] {msg}', flush=True)


def parse_gs(p):
    if p.startswith('gs://'):
        p = p[5:]
    bucket, _, path = p.partition('/')
    return bucket, path


async def worker(queue, session, out_bucket, out_path_template, state, state_lock):
    while True:
        orgnr = await queue.get()
        if orgnr is None:
            queue.task_done()
            return

        out_path = out_path_template.format(orgnr=orgnr)
        out_blob = out_bucket.blob(out_path)

        if not SKIP_EXISTS_CHECK:
            exists = await asyncio.to_thread(out_blob.exists)
            if exists:
                async with state_lock:
                    state['skip'] += 1
                    state['done'] += 1
                queue.task_done()
                continue

        backoff = 1.0
        result = None
        for attempt in range(4):
            try:
                async with session.get(BASE_URL.format(orgnr=orgnr),
                                       headers={'Accept': 'application/json'},
                                       timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status == 404:
                        result = ('404', None)
                        break
                    if r.status != 200:
                        if attempt < 3:
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue
                        result = ('fail', None)
                        break
                    raw = await r.read()
                    if RATE_LIMIT_MARKER.encode() in raw[:300]:
                        await asyncio.sleep(backoff + 1)
                        backoff *= 2
                        continue
                    result = ('ok', raw)
                    break
            except Exception:
                if attempt < 3:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                result = ('fail', None)
                break

        if result is None:
            result = ('fail', None)

        status, raw = result
        if status == 'ok':
            try:
                await asyncio.to_thread(
                    out_blob.upload_from_string, raw, content_type='application/json')
                async with state_lock:
                    state['ok'] += 1
                    state['bytes_written'] += len(raw)
            except Exception:
                async with state_lock:
                    state['fail'] += 1
        elif status == '404':
            async with state_lock:
                state['not_found'] += 1
        else:
            async with state_lock:
                state['fail'] += 1

        async with state_lock:
            state['done'] += 1
        queue.task_done()


async def main():
    log(f'starting: task={TASK_INDEX}/{TASK_COUNT} sem={MAX_CONCURRENT} dt={DT} '
        f'skip_exists={SKIP_EXISTS_CHECK}')

    creds, _ = google.auth.default()
    client = gcs_storage.Client(project=PROJECT_ID, credentials=creds)

    work_bkt, work_path = parse_gs(WORK_LIST_BLOB)
    full_list = json.loads(client.bucket(work_bkt).blob(work_path).download_as_text())
    my_shard = full_list[TASK_INDEX::TASK_COUNT]
    log(f'loaded {len(full_list)} total, my shard: {len(my_shard)}')

    out_bkt_name, out_prefix = parse_gs(OUT_PREFIX)
    out_bucket = client.bucket(out_bkt_name)
    out_path_template = f'{out_prefix}/dt={DT}/{{orgnr}}.json'

    state_path = f'{out_prefix}/state/dt={DT}/state_task{TASK_INDEX:03d}.json'
    state = {
        'task_index': TASK_INDEX, 'task_count': TASK_COUNT,
        'shard_size': len(my_shard),
        'started': datetime.now(timezone.utc).isoformat(),
        'ok': 0, 'skip': 0, 'not_found': 0, 'fail': 0, 'done': 0,
        'bytes_written': 0,
    }

    def save_state_sync():
        s = dict(state)
        s['last_update'] = datetime.now(timezone.utc).isoformat()
        out_bucket.blob(state_path).upload_from_string(
            json.dumps(s, indent=2), content_type='application/json')

    save_state_sync()

    queue = asyncio.Queue(maxsize=MAX_CONCURRENT * 2)
    state_lock = asyncio.Lock()

    timeout = aiohttp.ClientTimeout(total=60)
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT * 2)

    t0 = time.time()
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        workers = [
            asyncio.create_task(
                worker(queue, session, out_bucket, out_path_template, state, state_lock))
            for _ in range(MAX_CONCURRENT)
        ]

        async def producer():
            for orgnr in my_shard:
                await queue.put(orgnr)
            for _ in workers:
                await queue.put(None)

        async def status_logger():
            last_logged = 0
            try:
                while True:
                    await asyncio.sleep(10)
                    async with state_lock:
                        done = state['done']
                        snapshot = dict(state)
                    if done - last_logged >= CHECKPOINT_EVERY or done >= len(my_shard):
                        last_logged = done
                        elapsed = time.time() - t0
                        rate = done / elapsed if elapsed else 0
                        eta = (len(my_shard) - done) / rate / 60 if rate > 0 else 0
                        log(f"  {done:>6}/{len(my_shard)} ({100*done/len(my_shard):.1f}%) "
                            f"ok={snapshot['ok']} skip={snapshot['skip']} "
                            f"404={snapshot['not_found']} fail={snapshot['fail']} "
                            f"rate={rate:.1f}/s ETA={eta:.0f}m")
                        await asyncio.to_thread(save_state_sync)
                    if done >= len(my_shard):
                        return
            except asyncio.CancelledError:
                return

        prod_task = asyncio.create_task(producer())
        log_task = asyncio.create_task(status_logger())

        await prod_task
        await asyncio.gather(*workers)
        log_task.cancel()
        try:
            await log_task
        except asyncio.CancelledError:
            pass

    state['finished'] = True
    state['elapsed_sec'] = time.time() - t0
    save_state_sync()

    log(f'DONE in {(time.time()-t0)/60:.1f}m  ok={state["ok"]} skip={state["skip"]} '
        f'404={state["not_found"]} fail={state["fail"]}  bytes={state["bytes_written"]:,}')


if __name__ == '__main__':
    asyncio.run(main())
