#!/bin/bash
set -e

MODEL="qwen2.5-coder:7b-instruct-q4_K_M"
OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"

echo "=== LLM Service Startup ==="
echo "Model: ${MODEL}"
echo "Ollama host: ${OLLAMA_HOST}"

# ── Wait for Ollama to be ready ──────────────────────────────────
echo "Waiting for Ollama to be ready at ${OLLAMA_HOST}..."
MAX_RETRIES=60
RETRY_INTERVAL=3
retries=0

until curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; do
    retries=$((retries + 1))
    if [ "$retries" -ge "$MAX_RETRIES" ]; then
        echo "ERROR: Ollama did not become ready after $((MAX_RETRIES * RETRY_INTERVAL))s"
        exit 1
    fi
    echo "  Ollama not ready yet (attempt ${retries}/${MAX_RETRIES}), retrying in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done

echo "Ollama is ready."

# ── Ensure model is available ────────────────────────────────────
echo "Checking for model ${MODEL}..."
if curl -sf "${OLLAMA_HOST}/api/tags" | grep -q "\"${MODEL}\""; then
    echo "Model ${MODEL} is already available."
else
    echo "Model ${MODEL} not found. Pulling (this may take a while)..."
    curl -s -X POST "${OLLAMA_HOST}/api/pull" -d "{\"name\": \"${MODEL}\"}" | while IFS= read -r line; do
        # Show progress periodically
        echo "$line" | grep -o '"completed":[0-9]*' | head -1 || true
    done
    echo "Model ${MODEL} pulled successfully."
fi

# ── Start the LLM gRPC service ───────────────────────────────────
echo "Starting LLM gRPC service..."
exec python main.py
