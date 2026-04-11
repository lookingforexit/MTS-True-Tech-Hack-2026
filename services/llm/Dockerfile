# Build from repository root: docker compose build llm
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/llm/requirements.txt ./requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY proto ./proto
COPY services/llm ./services/llm

WORKDIR /app

RUN python -m grpc_tools.protoc \
    -I ./proto \
    --python_out=./services/llm \
    --grpc_python_out=./services/llm \
    ./proto/api/llm/v1/llm.proto \
    && python -m grpc_tools.protoc \
    -I ./proto \
    --python_out=./services/llm \
    --grpc_python_out=./services/llm \
    ./proto/api/lua_validator/v1/validator.proto

RUN mv ./services/llm/api/llm/v1/llm_pb2.py ./services/llm/ && \
    mv ./services/llm/api/llm/v1/llm_pb2_grpc.py ./services/llm/ && \
    sed -i 's|from api.llm.v1 import llm_pb2|import llm_pb2|' ./services/llm/llm_pb2_grpc.py

RUN mv ./services/llm/api/lua_validator/v1/validator_pb2.py ./services/llm/ && \
    mv ./services/llm/api/lua_validator/v1/validator_pb2_grpc.py ./services/llm/ && \
    sed -i 's|from api.lua_validator.v1 import validator_pb2|import validator_pb2|' ./services/llm/validator_pb2_grpc.py

RUN rm -rf ./services/llm/api

WORKDIR /app/services/llm

EXPOSE 50051

CMD ["python", "main.py"]
