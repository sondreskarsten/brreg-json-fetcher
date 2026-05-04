FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    aiohttp \
    google-cloud-storage \
    google-auth \
    pyarrow

COPY runner.py /app/runner.py
COPY parser.py /app/parser.py

ENTRYPOINT ["python"]
CMD ["/app/runner.py"]
