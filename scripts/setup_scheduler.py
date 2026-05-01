#!/usr/bin/env python3
"""Set up Cloud Scheduler to run the brreg-json-fetcher Cloud Run Job daily.

The schedule fires at 03:00 Europe/Oslo every day. Each run produces a fresh
dt={YYYY-MM-DD} partition on GCS — daily snapshot, no overwrite of prior days.

Authentication: schedule uses the same service account as the job. The
scheduler service account must have run.invoker on the job.
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
PROJECT_NUMBER = '331757836174'
REGION = 'europe-north1'
JOB_NAME = 'brreg-json-fetcher'
SCHEDULER_NAME = f'{JOB_NAME}-daily'
SA = f's1sfreracct@{PROJECT}.iam.gserviceaccount.com'

DEFAULT_CRON = '0 3 * * *'  # 03:00 daily, Europe/Oslo
DEFAULT_TZ = 'Europe/Oslo'


def configure(cron=DEFAULT_CRON, tz=DEFAULT_TZ):
    creds = service_account.Credentials.from_service_account_file(
        KEY, scopes=['https://www.googleapis.com/auth/cloud-platform'])
    creds.refresh(Request())
    auth = {'Authorization': f'Bearer {creds.token}', 'Content-Type': 'application/json'}

    job_uri = (f'https://{REGION}-run.googleapis.com/apis/run.googleapis.com/v1/'
               f'namespaces/{PROJECT}/jobs/{JOB_NAME}:run')

    sched_spec = {
        'description': f'Daily snapshot of BRREG regnskap JSON for all orgnrs in manifest',
        'schedule': cron,
        'timeZone': tz,
        'httpTarget': {
            'uri': job_uri,
            'httpMethod': 'POST',
            'oauthToken': {
                'serviceAccountEmail': SA,
                'scope': 'https://www.googleapis.com/auth/cloud-platform',
            },
            'body': '',
        },
        'retryConfig': {
            'retryCount': 1,
        },
    }

    base = f'https://cloudscheduler.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/jobs'

    r = requests.get(f'{base}/{SCHEDULER_NAME}', headers=auth)
    if r.status_code == 200:
        print(f'Updating schedule {SCHEDULER_NAME}: {cron} {tz}')
        update_mask = 'description,schedule,timeZone,httpTarget,retryConfig'
        r = requests.patch(f'{base}/{SCHEDULER_NAME}?updateMask={update_mask}',
                            headers=auth, json=sched_spec)
    else:
        print(f'Creating schedule {SCHEDULER_NAME}: {cron} {tz}')
        sched_spec['name'] = f'projects/{PROJECT}/locations/{REGION}/jobs/{SCHEDULER_NAME}'
        r = requests.post(base, headers=auth, json=sched_spec)

    print(f'  status: {r.status_code}')
    if r.status_code not in (200, 201):
        print(r.text[:1500])
        sys.exit(1)
    print(f'OK. Next run will trigger at {cron} {tz}.')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--cron', default=DEFAULT_CRON)
    p.add_argument('--tz', default=DEFAULT_TZ)
    args = p.parse_args()
    configure(cron=args.cron, tz=args.tz)
