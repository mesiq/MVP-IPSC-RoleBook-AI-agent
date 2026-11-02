FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

# Editable install keeps config.ROOT = /app, so ./source_data, ./data and ./.env are found there
RUN pip install --no-cache-dir -e .

ENV IPSC_HOST=0.0.0.0 \
    IPSC_PORT=8000 \
    IPSC_TRUST_PROXY=1 \
    FASTEMBED_CACHE_PATH=/app/cache \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["ipsc-web"]
