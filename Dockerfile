FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY brreg_fetcher ./brreg_fetcher
RUN pip install --no-cache-dir uv==0.8.22 && uv sync --frozen --no-dev
ENTRYPOINT ["/app/.venv/bin/brreg-fetch"]
CMD ["--help"]
