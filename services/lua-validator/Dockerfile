FROM python:3.11-slim

ARG UV_VERSION=0.11.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    lua5.4 \
    lua5.4-dev \
    luarocks \
    ca-certificates \
    make \
    && rm -rf /var/lib/apt/lists/* \
    && luarocks --lua-version=5.4 install dkjson \
    && pip install --no-cache-dir uv==${UV_VERSION}

WORKDIR /app

COPY proto ./proto
COPY services/lua-validator ./services/lua-validator

RUN uv pip install --system ./services/lua-validator

RUN cd services/lua-validator && make generate-python PROTO_ROOT=/app/proto

WORKDIR /app/services/lua-validator

ENV PYTHONPATH=/app/services/lua-validator/gen:/app/services/lua-validator

EXPOSE 50052

CMD ["python", "main.py"]
