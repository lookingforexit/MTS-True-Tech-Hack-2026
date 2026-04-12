#!/bin/bash
set -e

MODEL="qwen2.5-coder:7b-instruct-q4_K_M"
OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"

echo "Checking if model ${MODEL} is available in Ollama..."

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready at ${OLLAMA_HOST}..."
until curl -sf ${OLLAMA_HOST}/api/tags > /dev/null 2>&1; do
    echo "Ollama not ready yet, retrying in 2 seconds..."
    sleep 2
done

echo "Ollama is ready. Checking for model..."

# Check if model exists
if curl -sf ${OLLAMA_HOST}/api/tags | grep -q "${MODEL}"; then
    echo "Model ${MODEL} already exists in Ollama."
else
    echo "Model ${MODEL} not found. Pulling..."
    curl -X POST ${OLLAMA_HOST}/api/pull -d "{\"name\": \"${MODEL}\"}"
    echo "Model ${MODEL} pulled successfully."
fi

echo "Starting LLM service..."
exec python main.py
