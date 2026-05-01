#!/usr/bin/env python3
"""Build the work list of orgnrs from the manifest.

Reads gs://brreg-regnskap/manifest.parquet and writes the unique orgnrs as
a JSON array to gs://sondre_brreg_data/raw/brreg_regnskap_json/work_list.json.
"""
import io
import json
import os

import pyarrow.parquet as pq
from google.cloud import storage as gcs_storage
from google.oauth2 import service_account

KEY = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS',
                     '/mnt/project/sondreskarsten-d7d14-8486be2d085b.json')
PROJECT = 'sondreskarsten-d7d14'
SOURCE_BUCKET = 'brreg-regnskap'
SOURCE_BLOB = 'manifest.parquet'
OUT_BUCKET = 'sondre_brreg_data'
OUT_BLOB = 'raw/brreg_regnskap_json/work_list.json'


def main():
    creds = service_account.Credentials.from_service_account_file(KEY)
    client = gcs_storage.Client(project=PROJECT, credentials=creds)

    print(f'Reading gs://{SOURCE_BUCKET}/{SOURCE_BLOB}...')
    raw = client.bucket(SOURCE_BUCKET).blob(SOURCE_BLOB).download_as_bytes()
    table = pq.read_table(io.BytesIO(raw), columns=['orgnr'])
    df = table.to_pandas()
    unique = sorted(df['orgnr'].dropna().unique().tolist())
    print(f'Unique orgnrs: {len(unique):,}')

    payload = json.dumps(unique)
    client.bucket(OUT_BUCKET).blob(OUT_BLOB).upload_from_string(
        payload, content_type='application/json')
    print(f'Wrote gs://{OUT_BUCKET}/{OUT_BLOB} ({len(payload):,} bytes)')


if __name__ == '__main__':
    main()
