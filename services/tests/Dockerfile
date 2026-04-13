FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

COPY services/tests/requirements.txt ./services/tests/requirements.txt

RUN uv pip install --no-cache-dir -r services/tests/requirements.txt

COPY proto/ ./proto/
COPY services/tests/ ./tests/

RUN mkdir -p /app/tests/generated && \
    touch /app/tests/generated/__init__.py && \
    python -m grpc_tools.protoc -I=/app/proto \
        --python_out=/app/tests/generated \
        --grpc_python_out=/app/tests/generated \
        /app/proto/api/llm/v1/llm.proto \
        /app/proto/api/lua_validator/v1/validator.proto

ENV PYTHONPATH=/app/tests/generated:/app/tests

WORKDIR /app/tests

CMD ["pytest", "-v", "test_local_script.py", "--html=reports/report.html", "--self-contained-html"]