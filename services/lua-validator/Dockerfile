FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    lua5.4 \
    lua5.4-dev \
    luarocks \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && luarocks --lua-version=5.4 install dkjson \
    && pip install --no-cache-dir uv

WORKDIR /app

COPY services/lua-validator/pyproject.toml ./services/lua-validator/pyproject.toml

RUN uv pip install --system ./services/lua-validator

# Copy pre-generated gRPC stubs (nested package structure)
COPY services/lua-validator/generated ./services/lua-validator/generated

# Copy service source
COPY services/lua-validator/main.py ./services/lua-validator/main.py

WORKDIR /app/services/lua-validator

ENV PYTHONPATH=/app/services/lua-validator/generated:/app/services/lua-validator

EXPOSE 50052

CMD ["python", "main.py"]
