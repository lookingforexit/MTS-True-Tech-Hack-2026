FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /bin/uv
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

COPY services/tests/pyproject.toml ./services/tests/pyproject.toml

RUN uv pip install --no-cache-dir ./services/tests

COPY proto/ ./proto/
COPY services/tests/ ./tests/

RUN mkdir -p /app/tests/gen && \
    touch /app/tests/gen/__init__.py && \
    python -m grpc_tools.protoc -I=/app/proto \
        --python_out=/app/tests/gen \
        --grpc_python_out=/app/tests/gen \
        /app/proto/api/llm/v1/llm.proto \
        /app/proto/api/lua_validator/v1/validator.proto

ENV PYTHONPATH=/app/tests/gen:/app/tests

WORKDIR /app/tests

CMD ["sh", "-c", "rm -f reports/report.html && pytest -v test_local_script.py --html=reports/report.html --self-contained-html"]
