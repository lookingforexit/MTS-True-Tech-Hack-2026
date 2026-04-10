FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY services/llm/pyproject.toml ./

RUN uv sync --no-dev

# Copy proto files (both llm and lua_validator for stubs)
COPY proto ./proto

# Copy service source
COPY services/llm ./services/llm

WORKDIR /app

# Generate LLM gRPC stubs
RUN uv run python -m grpc_tools.protoc \
    -I ./proto \
    --python_out=./services/llm \
    --grpc_python_out=./services/llm \
    ./proto/api/llm/v1/llm.proto

# Generate Lua Validator stubs (for the client)
RUN uv run python -m grpc_tools.protoc \
    -I ./proto \
    --python_out=./services/llm \
    --grpc_python_out=./services/llm \
    ./proto/api/lua_validator/v1/validator.proto

# Move LLM stubs to service root and fix imports
RUN mv ./services/llm/api/llm/v1/llm_pb2.py ./services/llm/ && \
    mv ./services/llm/api/llm/v1/llm_pb2_grpc.py ./services/llm/ && \
    sed -i 's|from api.llm.v1 import llm_pb2|import llm_pb2|' ./services/llm/llm_pb2_grpc.py

# Move Lua Validator stubs to service root and fix imports
RUN mv ./services/llm/api/lua_validator/v1/validator_pb2.py ./services/llm/ && \
    mv ./services/llm/api/lua_validator/v1/validator_pb2_grpc.py ./services/llm/ && \
    sed -i 's|from api.lua_validator.v1 import validator_pb2|import validator_pb2|' ./services/llm/validator_pb2_grpc.py

# Clean up generated tree
RUN rm -rf ./services/llm/api

WORKDIR /app/services/llm

EXPOSE 50051

CMD ["uv", "run", "python", "main.py"]
