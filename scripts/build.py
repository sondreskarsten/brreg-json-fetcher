#!/usr/bin/env python3
"""Build container via Cloud Build REST API and push to Artifact Registry."""
import io
import json
import os
import sys
import tarfile
import time

import requests
from google.cloud import storage as gcs_storage
from google.oauth2 import service_account
from google.auth.transport.requests import Request

KEY = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS',
                     '/mnt/project/sondreskarsten-d7d14-8486be2d085b.json')
PROJECT = 'sondreskarsten-d7d14'
REGION = 'europe-north1'
IMAGE_NAME = f'{REGION}-docker.pkg.dev/{PROJECT}/r-images/brreg-json-fetcher'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build():
    tag = f'v{time.strftime("%Y%m%d-%H%M%S")}'

    creds = service_account.Credentials.from_service_account_file(
        KEY, scopes=['https://www.googleapis.com/auth/cloud-platform'])
    creds.refresh(Request())
    client = gcs_storage.Client(project=PROJECT, credentials=creds)

    print(f'Building tarball from {REPO_ROOT}...')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        tar.add(os.path.join(REPO_ROOT, 'Dockerfile'), arcname='Dockerfile')
        tar.add(os.path.join(REPO_ROOT, 'runner.py'), arcname='runner.py')
        tar.add(os.path.join(REPO_ROOT, 'parser.py'), arcname='parser.py')

    buf.seek(0)
    context_bucket = f'{PROJECT}_cloudbuild'
    context_path = f'brreg-json-fetcher/context-{tag}.tar.gz'
    client.bucket(context_bucket).blob(context_path).upload_from_file(
        buf, content_type='application/gzip')
    print(f'Uploaded: gs://{context_bucket}/{context_path}')

    build_config = {
        'source': {'storageSource': {'bucket': context_bucket, 'object': context_path}},
        'steps': [{
            'name': 'gcr.io/cloud-builders/docker',
            'args': ['build', '-t', f'{IMAGE_NAME}:{tag}', '-t', f'{IMAGE_NAME}:latest', '.'],
        }],
        'images': [f'{IMAGE_NAME}:{tag}', f'{IMAGE_NAME}:latest'],
        'logsBucket': f'gs://{PROJECT}_cloudbuild_logs',
        'options': {'machineType': 'E2_HIGHCPU_8'},
        'timeout': '600s',
    }

    url = f'https://cloudbuild.googleapis.com/v1/projects/{PROJECT}/locations/global/builds'
    r = requests.post(url, headers={
        'Authorization': f'Bearer {creds.token}',
        'Content-Type': 'application/json',
    }, json=build_config)
    r.raise_for_status()
    build_id = r.json()['metadata']['build']['id']
    print(f'Build started: {build_id}')

    status_url = f'https://cloudbuild.googleapis.com/v1/projects/{PROJECT}/locations/global/builds/{build_id}'
    t0 = time.time()
    while True:
        time.sleep(8)
        creds.refresh(Request())
        r = requests.get(status_url, headers={'Authorization': f'Bearer {creds.token}'})
        status = r.json().get('status', '?')
        print(f'  [{time.time()-t0:.0f}s] {status}')
        if status in ('SUCCESS', 'FAILURE', 'INTERNAL_ERROR', 'TIMEOUT', 'CANCELLED', 'EXPIRED'):
            break

    if status == 'SUCCESS':
        print(f'\nImage: {IMAGE_NAME}:{tag}')
        print(f'       {IMAGE_NAME}:latest')
        return tag

    log_blob = client.bucket(f'{PROJECT}_cloudbuild_logs').blob(f'log-{build_id}.txt')
    if log_blob.exists():
        print(log_blob.download_as_text()[-3000:])
    sys.exit(1)


if __name__ == '__main__':
    build()
