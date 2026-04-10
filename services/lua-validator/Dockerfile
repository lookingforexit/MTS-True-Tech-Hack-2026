FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends lua5.4 && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

WORKDIR /app

COPY services/lua-validator/pyproject.toml ./

RUN uv sync --no-dev

# Copy proto
COPY proto ./proto

# Copy service source
COPY services/lua-validator ./services/lua-validator

WORKDIR /app

# Generate Python gRPC stubs
RUN uv run python -m grpc_tools.protoc \
    -I ./proto \
    --python_out=./services/lua-validator \
    --grpc_python_out=./services/lua-validator \
    ./proto/api/lua_validator/v1/validator.proto

# Move generated stubs to service root and fix imports
RUN mv ./services/lua-validator/api/lua_validator/v1/validator_pb2.py ./services/lua-validator/ && \
    mv ./services/lua-validator/api/lua_validator/v1/validator_pb2_grpc.py ./services/lua-validator/ && \
    rm -rf ./services/lua-validator/api && \
    sed -i 's|from api.lua_validator.v1 import validator_pb2|import validator_pb2|' ./services/lua-validator/validator_pb2_grpc.py

WORKDIR /app/services/lua-validator

EXPOSE 50052

CMD ["uv", "run", "python", "main.py"]
