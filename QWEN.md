# Ocean Cucumber — AI Lua Code Generator

## Project Overview

**Ocean Cucumber** is a multi-agent AI system that generates validated Lua scripts from natural language descriptions. It uses a LangGraph-based pipeline with specialized agents (Spec, Clarifier, Generator) backed by Ollama (Qwen 2.5 Coder), and validates generated code by executing it in a Lua sandbox.

### Architecture

The system is composed of five services, orchestrated via Docker Compose:

```
User → Streamlit Frontend (:8501)
         ↓
      Go Backend / Gin (:8080)
         ↓
    ┌────┴────┐
    ↓         ↓
LLM gRPC   Lua Validator gRPC
(:50051)   (:50052)
    ↓
  Ollama (:11434)
```

| Service | Tech | Port | Description |
|---|---|---|---|
| **Frontend** | Python / Streamlit | 8501 | Chat UI for submitting Lua generation requests |
| **Backend** | Go / Gin | 8080 | REST API that proxies to the LLM gRPC service |
| **LLM Service** | Python / LangGraph / gRPC | 50051 | Multi-agent pipeline (Spec → Clarifier → Generator → Validator) |
| **Lua Validator** | Python / gRPC | 50052 | Executes Lua code in a sandboxed subprocess (lua5.4) |
| **Ollama** | ollama/ollama | 11434 | Local LLM inference server (model: `qwen2.5-coder:7b-instruct-q4_K_M`) |

### Pipeline Flow

1. **Extract Context** — passes raw JSON context through (no introspection)
2. **Spec Agent** — normalizes user request + context into a JSON specification
3. **Clarifier Agent** — reviews the spec; approves or asks one clarification question
4. **Generator Agent** — produces Lua code from the spec
5. **Validator** — runs the code via the Lua Validator gRPC service
6. **Repair Loop** — if validation fails, the generator retries (up to `MAX_REPAIRS=2`) with error feedback

### gRPC Contracts

Two protobuf services are defined in `proto/api/`:

- **`llm.v1.LLMService`** — `StartOrContinue`, `AnswerClarification`, `GetSessionState`
- **`lua_validator.v1.LuaValidatorService`** — `Validate`

Generated Python/Go code lives in `services/*/generated/`.

## Building and Running

### Prerequisites

- Docker & Docker Compose
- NVIDIA Container Toolkit (optional, for GPU-accelerated Ollama)

### Start All Services

```bash
# CPU mode
docker compose up --build

# GPU mode (requires NVIDIA GPU + toolkit)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

### Run Tests

```bash
docker compose --profile tests up
```

Test reports are written to `tests/reports/`.

### Local Development (outside Docker)

**Frontend:**
```bash
cd services/frontend
BACKEND_URL=http://localhost:8080 streamlit run app.py
```

**Backend (Go):**
```bash
cd services/backend
make run
```

**LLM Service:**
```bash
cd services/llm
OLLAMA_HOST=http://localhost:11434 LUA_VALIDATOR_HOST=localhost python main.py
```

**Lua Validator:**
```bash
cd services/lua-validator
LUA_INTERPRETER=lua5.4 python main.py
```

## Key Configuration

| Env Var | Service | Description |
|---|---|---|
| `OLLAMA_HOST` | LLM | Ollama server URL |
| `LUA_VALIDATOR_HOST` | LLM | Lua validator hostname |
| `LUA_VALIDATOR_PORT` | LLM | Lua validator port |
| `LUA_INTERPRETER` | Lua Validator | Path/command for Lua interpreter (default: `lua5.4`) |
| `BACKEND_URL` | Frontend | Backend API URL |
| `GIN_MODE` | Backend | Gin framework mode (`release` / `debug`) |
| `LLM_ADDR` | Backend | LLM gRPC address (e.g., `llm:50051`) |

## Development Conventions

- **Python services** use `uv` for dependency management (`pyproject.toml` + `uv.lock`). Run `uv lock` to update dependencies.
- **Backend** is a Go module using Gin + gRPC. Generated protobuf code is committed under `services/backend/internal/gen/` or `generated/`.
- **Proto files** are the source of truth. Regenerate code after modifying `.proto` files.
- **Logging**: The LLM service uses verbose debug logging for agent inputs/outputs (surrounded by `═══` separators).
- **Session management**: The LLM service uses in-memory session storage with thread-safe access (`_sessions` dict + `Lock`).

## Testing

Tests are Python-based (pytest) and live in `tests/`. They test both the LLM gRPC service and the Lua Validator gRPC service. The test Dockerfile builds from the `tests/` directory and runs against the compose services.

```bash
# Run tests via compose
docker compose --profile tests up

# Or directly with pytest (when services are running locally)
cd tests
pytest --html=reports/report.html
```
