FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    aiohttp \
    google-cloud-storage \
    google-auth

COPY runner.py /app/runner.py

ENTRYPOINT ["python", "/app/runner.py"]
