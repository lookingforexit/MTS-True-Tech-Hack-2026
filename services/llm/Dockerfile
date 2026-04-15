FROM python:3.11-slim

ARG UV_VERSION=0.11.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    make \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==${UV_VERSION}

COPY proto ./proto
COPY services/llm ./services/llm

RUN uv pip install --system ./services/llm

RUN cd services/llm && make generate-python PROTO_ROOT=/app/proto

RUN sed -i 's/\r$//' ./services/llm/startup.sh \
    && chmod +x ./services/llm/startup.sh

WORKDIR /app/services/llm

ENV PYTHONPATH=/app/services/llm/gen:/app/services/llm

EXPOSE 50051

CMD ["sh", "./startup.sh"]
