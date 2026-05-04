"""Parse all BRREG JSON files for a given dt into a single parquet GT.

Reads:  gs://sondre_brreg_data/raw/brreg_regnskap_json/dt={DT}/{orgnr}.json
Writes: gs://sondre_brreg_data/raw/brreg_regnskap_json/parsed/dt={DT}/parsed_gt.parquet

Each JSON contains an array of submissions for that orgnr. Output is one row per
(orgnr, journalnr) preserving every submission BRREG returned at fetch time.

Single-task job. Uses ThreadPoolExecutor with high concurrency for in-region
GCS reads.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import google.auth
from google.cloud import storage as gcs_storage

PROJECT_ID = 'sondreskarsten-d7d14'
BUCKET = os.environ.get('BUCKET', 'sondre_brreg_data')
PREFIX = os.environ.get('PREFIX', 'raw/brreg_regnskap_json')
DT = os.environ.get('DT', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
THREADS = int(os.environ.get('THREADS', '256'))
LOG_EVERY = int(os.environ.get('LOG_EVERY', '20000'))


def log(msg):
    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


def parse_one(raw, fetch_dt):
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        data = [data]
    out = []
    for item in data:
        eg = item.get('egenkapitalGjeld') or {}
        egen = eg.get('egenkapital') or {}
        gjeld = eg.get('gjeldOversikt') or {}
        eiend = item.get('eiendeler') or {}
        rr = item.get('resultatregnskapResultat') or {}
        drift = rr.get('driftsresultat') or {}
        finr = rr.get('finansresultat') or {}
        rec = {
            'orgnr': (item.get('virksomhet') or {}).get('organisasjonsnummer'),
            'journalnr': item.get('journalnr'),
            'regnskapstype': item.get('regnskapstype'),
            'organisasjonsform': (item.get('virksomhet') or {}).get('organisasjonsform'),
            'morselskap': (item.get('virksomhet') or {}).get('morselskap'),
            'fra_dato': (item.get('regnskapsperiode') or {}).get('fraDato'),
            'til_dato': (item.get('regnskapsperiode') or {}).get('tilDato'),
            'valuta': item.get('valuta'),
            'avviklingsregnskap': item.get('avviklingsregnskap'),
            'oppstillingsplan': item.get('oppstillingsplan'),
            'ikke_revidert': (item.get('revisjon') or {}).get('ikkeRevidertAarsregnskap'),
            'fravalg_revisjon': (item.get('revisjon') or {}).get('fravalgRevisjon'),
            'smaa_foretak': (item.get('regnkapsprinsipper') or {}).get('smaaForetak'),
            'regnskapsregler': (item.get('regnkapsprinsipper') or {}).get('regnskapsregler'),
            'sum_eiendeler': eiend.get('sumEiendeler'),
            'sum_anleggsmidler': (eiend.get('anleggsmidler') or {}).get('sumAnleggsmidler'),
            'sum_omloepsmidler': (eiend.get('omloepsmidler') or {}).get('sumOmloepsmidler'),
            'sum_egenkapital_gjeld': eg.get('sumEgenkapitalGjeld'),
            'sum_egenkapital': egen.get('sumEgenkapital'),
            'sum_innskutt_egenkapital': (egen.get('innskuttEgenkapital') or {}).get('sumInnskuttEgenkaptial'),
            'sum_opptjent_egenkapital': (egen.get('opptjentEgenkapital') or {}).get('sumOpptjentEgenkapital'),
            'sum_gjeld': gjeld.get('sumGjeld'),
            'sum_kortsiktig_gjeld': (gjeld.get('kortsiktigGjeld') or {}).get('sumKortsiktigGjeld'),
            'sum_langsiktig_gjeld': (gjeld.get('langsiktigGjeld') or {}).get('sumLangsiktigGjeld'),
            'aarsresultat': rr.get('aarsresultat'),
            'totalresultat': rr.get('totalresultat'),
            'ordinaert_resultat_for_skattekostnad': rr.get('ordinaertResultatFoerSkattekostnad'),
            'driftsresultat': drift.get('driftsresultat'),
            'sum_driftsinntekter': (drift.get('driftsinntekter') or {}).get('sumDriftsinntekter'),
            'sum_driftskostnad': (drift.get('driftskostnad') or {}).get('sumDriftskostnad'),
            'sum_finansinntekter': (finr.get('finansinntekt') or {}).get('sumFinansinntekter'),
            'sum_finanskostnad': (finr.get('finanskostnad') or {}).get('sumFinanskostnad'),
            'netto_finans': finr.get('nettoFinans'),
            'fetch_dt': fetch_dt,
        }
        out.append(rec)
    return out


def main():
    log(f'starting parser: dt={DT} threads={THREADS}')
    creds, _ = google.auth.default()
    client = gcs_storage.Client(project=PROJECT_ID, credentials=creds)
    bucket = client.bucket(BUCKET)

    in_prefix = f'{PREFIX}/dt={DT}/'
    log(f'listing {BUCKET}/{in_prefix}...')
    t0 = time.time()
    blob_names = []
    for blob in client.list_blobs(BUCKET, prefix=in_prefix):
        blob_names.append(blob.name)
    log(f'listed {len(blob_names):,} blobs in {time.time()-t0:.1f}s')

    if not blob_names:
        log('no blobs found, exiting')
        return

    def fetch(name):
        return bucket.blob(name).download_as_bytes()

    log(f'downloading + parsing with {THREADS} threads...')
    t0 = time.time()
    records = []
    n_blobs = 0
    n_records = 0
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for raw in ex.map(fetch, blob_names):
            n_blobs += 1
            recs = parse_one(raw, DT)
            records.extend(recs)
            n_records += len(recs)
            if n_blobs % LOG_EVERY == 0:
                rate = n_blobs / (time.time() - t0)
                eta = (len(blob_names) - n_blobs) / rate
                log(f'  {n_blobs:,}/{len(blob_names):,} blobs, {n_records:,} records, '
                    f'{rate:.0f} blobs/s ETA={eta:.0f}s')

    log(f'parsed {n_blobs:,} blobs into {n_records:,} records in {time.time()-t0:.0f}s')

    log('writing parquet...')
    t0 = time.time()
    table = pa.Table.from_pylist(records)
    out_path = f'/tmp/parsed_gt_{DT}.parquet'
    pq.write_table(table, out_path, compression='snappy')
    log(f'wrote {out_path} in {time.time()-t0:.1f}s ({os.path.getsize(out_path):,} bytes)')

    out_blob = f'{PREFIX}/parsed/dt={DT}/parsed_gt.parquet'
    bucket.blob(out_blob).upload_from_filename(out_path)
    log(f'uploaded gs://{BUCKET}/{out_blob}')


if __name__ == '__main__':
    main()
