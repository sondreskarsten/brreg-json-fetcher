#!/usr/bin/env python3
"""Create or update the Cloud Run Job and (optionally) execute it.

Usage:
    python scripts/deploy.py                 # update job spec only
    python scripts/deploy.py --run            # update + execute
    python scripts/deploy.py --tag v20260501  # use a specific image tag
"""
import argparse
import os
import sys
import time

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

KEY = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS',
                     '/mnt/project/sondreskarsten-d7d14-8486be2d085b.json')
PROJECT = 'sondreskarsten-d7d14'
REGION = 'europe-north1'
JOB_NAME = 'brreg-json-fetcher'
SA = f's1sfreracct@{PROJECT}.iam.gserviceaccount.com'


def deploy(tag='latest', run=False, task_count=8, max_concurrent=15, skip_exists_check=True):
    image = f'{REGION}-docker.pkg.dev/{PROJECT}/r-images/brreg-json-fetcher:{tag}'

    creds = service_account.Credentials.from_service_account_file(
        KEY, scopes=['https://www.googleapis.com/auth/cloud-platform'])
    creds.refresh(Request())
    auth = {'Authorization': f'Bearer {creds.token}', 'Content-Type': 'application/json'}
    base = f'https://{REGION}-run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs'

    job_spec = {
        'template': {
            'taskCount': task_count,
            'parallelism': task_count,
            'template': {
                'maxRetries': 2,
                'timeout': '7200s',
                'serviceAccount': SA,
                'containers': [{
                    'image': image,
                    'resources': {'limits': {'cpu': '1', 'memory': '2Gi'}},
                    'env': [
                        {'name': 'WORK_LIST_BLOB', 'value': 'sondre_brreg_data/raw/brreg_regnskap_json/work_list.json'},
                        {'name': 'OUT_PREFIX', 'value': 'sondre_brreg_data/raw/brreg_regnskap_json'},
                        {'name': 'MAX_CONCURRENT', 'value': str(max_concurrent)},
                        {'name': 'CHECKPOINT_EVERY', 'value': '500'},
                        {'name': 'SKIP_EXISTS_CHECK', 'value': '1' if skip_exists_check else '0'},
                    ],
                }],
            },
        },
    }

    r = requests.get(f'{base}/{JOB_NAME}', headers=auth)
    if r.status_code == 200:
        print(f'Updating job {JOB_NAME} to image: {image}')
        r = requests.patch(f'{base}/{JOB_NAME}', headers=auth, json=job_spec)
    else:
        print(f'Creating job {JOB_NAME} with image: {image}')
        r = requests.post(f'{base}?jobId={JOB_NAME}', headers=auth, json=job_spec)
    print(f'  status: {r.status_code}')
    if r.status_code not in (200, 201):
        print(r.text[:1500])
        sys.exit(1)

    op_name = r.json().get('name', '')
    op_url = f'https://{REGION}-run.googleapis.com/v2/{op_name}'
    for _ in range(60):
        time.sleep(2)
        r = requests.get(op_url, headers=auth)
        if r.json().get('done'):
            print('Job ready')
            break

    if not run:
        return

    time.sleep(2)
    r = requests.post(f'{base}/{JOB_NAME}:run', headers=auth, json={})
    print(f'Execute: {r.status_code}')
    if r.status_code == 200:
        exec_id = r.json().get('metadata', {}).get('name', '').split('/')[-1]
        print(f'Execution: {exec_id}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--tag', default='latest')
    p.add_argument('--run', action='store_true')
    p.add_argument('--task-count', type=int, default=8)
    p.add_argument('--max-concurrent', type=int, default=15)
    p.add_argument('--skip-exists-check', action='store_true', default=True)
    p.add_argument('--no-skip-exists-check', dest='skip_exists_check', action='store_false')
    args = p.parse_args()
    deploy(tag=args.tag, run=args.run, task_count=args.task_count,
           max_concurrent=args.max_concurrent, skip_exists_check=args.skip_exists_check)
