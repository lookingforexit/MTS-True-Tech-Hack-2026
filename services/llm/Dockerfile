FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    make \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY proto ./proto
COPY services/llm/pyproject.toml ./services/llm/pyproject.toml

RUN uv pip install --system ./services/llm

COPY services/llm ./services/llm

RUN cd services/llm && make generate-python PROTO_ROOT=/app/proto

RUN chmod +x ./services/llm/startup.sh

WORKDIR /app/services/llm

ENV PYTHONPATH=/app/services/llm/gen:/app/services/llm

EXPOSE 50051

CMD ["./startup.sh"]
