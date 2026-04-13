FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY proto ./proto
COPY services/llm/pyproject.toml ./services/llm/pyproject.toml

RUN uv pip install --system ./services/llm

# Copy pre-generated gRPC stubs (nested package structure)
COPY services/llm/generated ./services/llm/generated

# Copy service source
COPY services/llm/main.py \
     services/llm/graph.py \
     services/llm/state.py \
     services/llm/prompts.py \
     services/llm/checker_client.py \
     services/llm/validator_client.py \
     services/llm/context_normalizer.py \
     services/llm/startup.sh \
     ./services/llm/

RUN chmod +x ./services/llm/startup.sh

WORKDIR /app/services/llm

ENV PYTHONPATH=/app/services/llm/generated:/app/services/llm

EXPOSE 50051

CMD ["./startup.sh"]
