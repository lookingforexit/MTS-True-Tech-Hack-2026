FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

COPY tests/pyproject.toml ./tests/pyproject.toml

RUN uv pip install --no-cache-dir ./tests

# Copy pre-generated gRPC stubs (nested package structure)
COPY tests/generated ./tests/generated

COPY proto/ ./proto/
COPY tests/ ./tests/

ENV PYTHONPATH=/app/tests/generated:/app/tests

WORKDIR /app/tests

CMD ["pytest", "-v", "test_local_script.py", "--html=reports/report.html", "--self-contained-html"]
