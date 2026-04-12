# Build from repository root: docker compose build lua-validator
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    lua5.4 \
    lua5.4-dev \
    luarocks \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && luarocks --lua-version=5.4 install dkjson

WORKDIR /app

COPY services/lua-validator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY proto ./proto
COPY services/lua-validator ./services/lua-validator

WORKDIR /app

RUN python -m grpc_tools.protoc \
    -I ./proto \
    --python_out=./services/lua-validator \
    --grpc_python_out=./services/lua-validator \
    ./proto/api/lua_validator/v1/validator.proto

RUN mv ./services/lua-validator/api/lua_validator/v1/validator_pb2.py ./services/lua-validator/ && \
    mv ./services/lua-validator/api/lua_validator/v1/validator_pb2_grpc.py ./services/lua-validator/ && \
    rm -rf ./services/lua-validator/api && \
    sed -i 's|from api.lua_validator.v1 import validator_pb2|import validator_pb2|' ./services/lua-validator/validator_pb2_grpc.py

WORKDIR /app/services/lua-validator

EXPOSE 50052

CMD ["python", "main.py"]
