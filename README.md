# Ocean Cucumber — Local AI Agent for Lua Code Generation

> **Fully local, privacy-preserving, multi-agent system that turns natural-language tasks into working Lua code — powered by a lightweight open-source LLM running on your own infrastructure.**

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [LLM Model & Hardware Requirements](#llm-model--hardware-requirements)
- [Quick Start](#quick-start)
- [Pipeline: How It Works](#pipeline-how-it-works)
- [Clarification & Iteration Flow](#clarification--iteration-flow)
- [Validation System](#validation-system)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Reproducibility Checklist](#reproducibility-checklist)
- [Evaluation Criteria Mapping](#evaluation-criteria-mapping)
- [Troubleshooting](#troubleshooting)

---

## Overview

**Ocean Cucumber** solves a real problem: in many integration and security-sensitive environments, sending data to external AI services is unacceptable — it creates data-leak risks, vendor lock-in, and compliance violations. Meanwhile, large models demand expensive hardware and are impractical for local deployment.

Our solution is a **fully self-contained agent system** that:

1. **Runs entirely on your own infrastructure** — zero external AI API calls at runtime.
2. **Uses a lightweight 7B-parameter quantized model** that fits in **≤ 8 GB VRAM** on a single GPU.
3. **Understands tasks in Russian or English**, generates correct Lua code, asks clarifying questions when needed, and iteratively refines output through a validation-repair loop.
4. **Validates generated code** through both static analysis (AST-based forbidden-function detection) and sandboxed runtime execution.

The system is built with **Python + Go + Docker Compose**, uses **LangGraph** for the multi-agent workflow, and communicates via **gRPC** between services.

---

## Key Features

| Feature | Description |
|---|---|
| **100% Local** | No calls to OpenAI, Anthropic, or any external AI vendor. All inference runs on your hardware via Ollama. |
| **Lightweight Model** | `qwen2.5-coder:7b-instruct-q4_K_M` — 7B parameters, Q4_K_M quantization, fits in 8 GB VRAM. |
| **Multi-Agent Pipeline** | Spec extraction → Clarification → Code Generation → Validation → Repair (up to 2 retries). |
| **Clarification Questions** | The system asks targeted questions when the task is ambiguous (goal, return value, input data path). |
| **Bilingual** | Automatic language detection (Russian / English); prompts and questions adapt accordingly. |
| **Two-Stage Validation** | Static AST analysis (forbidden functions, unsafe patterns) + sandboxed Lua 5.4 execution. |
| **Repair Loop** | On validation failure, the system feeds the error back to the model for self-correction. |
| **Reproducible** | Single `docker compose up` starts the entire stack. All dependencies, models, and steps are documented. |
| **Session Management** | Redis-backed sessions with configurable TTL; supports multi-turn clarification dialogues. |

---

### Service Breakdown

| Service | Language | Role |
|---|---|---|
| `services/llm/` | Python 3.11 | Core LangGraph multi-agent pipeline; gRPC server on port 50051 |
| `services/backend/` | Go 1.26 | REST API (Gin), Redis session store, gRPC client to LLM |
| `services/frontend/` | Python 3.11 | Streamlit web UI for interactive chat |
| `services/lua-validator/` | Python 3.11 | Sandboxed Lua 5.4 execution via subprocess; gRPC on port 50052 |
| `services/lua-checker/` | Go 1.26 | Static AST analysis for forbidden functions and unsafe patterns; gRPC on port 50053 |
| `services/tests/` | Python 3.11 | Integration tests (pytest) with 30+ parametrized test cases |

---

## LLM Model & Hardware Requirements

### Model

```bash
ollama pull qwen2.5-coder:7b-instruct-q4_K_M
```

**Full tag:** `qwen2.5-coder:7b-instruct-q4_K_M`

This is a **Q4_K_M quantized** version of Qwen2.5-Coder 7B Instruct — an open-source model optimized for code generation, small enough to run on a single consumer GPU.

### Ollama Runtime Parameters (Demo / Evaluation)

| Parameter | Value |
|---|---|
| `num_ctx` | 4096 |
| `num_predict` | 256 |
| `batch` | 1 |
| `parallel` | 1 |

These are set in the LangGraph LLM nodes (`graph.py`). Two LLM instances are used:
- **Spec agent** (`_llm_zero`): temperature=0.2
- **Code generator** (`_llm_generate`): temperature=0.3

### Hardware

| Requirement | Detail |
|---|---|
| **GPU** | NVIDIA with ≥ 8 GB VRAM |
| **VRAM budget** | Peak memory ≤ 8.0 GB (measured via `nvidia-smi`) |
| **CPU** | Any modern multi-core (model runs fully on GPU, no CPU offload) |
| **RAM** | ≥ 16 GB system RAM recommended |
| **Storage** | ~5 GB for model weights + Docker images |

### GPU vs CPU Mode

- **Default** (`docker-compose.yml`): Ollama runs in CPU mode.
- **GPU mode** (`docker-compose.gpu.yml`): Adds NVIDIA GPU access to the Ollama container.

```bash
# GPU mode
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

The `docker-compose.gpu.yml` sets `NVIDIA_VISIBLE_DEVICES=all` and uses the `nvidia` runtime.

---

## Quick Start

### Prerequisites

- **Docker** and **Docker Compose** (v2+)
- **NVIDIA GPU** with ≥ 8 GB VRAM (for GPU-accelerated mode)
- **NVIDIA Container Toolkit** (for GPU mode: `sudo apt install nvidia-container-toolkit`)

### Start All Services

```bash
# CPU-only mode
docker compose up --build

# GPU-accelerated mode (recommended)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

This builds and starts all services:
- **Frontend** → `http://localhost:8501`
- **Backend API** → `http://localhost:8080`
- Internal gRPC services (LLM, validator, checker) — not exposed externally

### First Use

1. Open `http://localhost:8501` in your browser.
2. (Optional) Paste a JSON context in the sidebar describing available variables.
3. Type your task in Russian or English, e.g.:

   > *"Создай функцию, которая принимает массив чисел и возвращает новый массив, содержащий только чётные числа"*

   or

   > *"Write a function that takes an array of numbers and returns only the even ones"*

4. The system will process your request. If clarification is needed, you'll see a question — answer it to continue.
5. The generated Lua code appears in the chat, along with validation results.

### Stop Services

```bash
docker compose down
```

---

## Pipeline: How It Works

The core is a **LangGraph state machine** defined in `services/llm/graph.py`. Here's the full flow:

```
START
  │
  ▼
┌─────────────────┐
│ extract_context │  Parse context JSON, build compact schema
└────────┬────────┘  summary of wf.vars and wf.initVariables
         │
         ▼
  ┌──────────────┐
  │ route_entry  │  clarifying=True ? → update_spec
  └──┬───────┬───┘  clarifying=False ? → spec
     │       │
     │       ▼
     │  ┌──────────────┐
     │  │     spec     │  Extract structured JSON spec from
     │  │              │  the user's natural-language request
     │  └──────┬───────┘
     │         │
     │         ▼
     │  ┌──────────────┐
     │  │  clarifier   │  Deterministic policy review:
     │  │              │  → Approve spec → generate
     │  │              │  → Ask question → clarification_needed (terminal)
     │  │              │  → Repeated question → error (terminal)
     │  └──────┬───────┘
     │         │
     ▼         ▼
┌────────┐  ┌──────────────┐
│generate│←─┤  update_spec │  Rebuild spec with clarification
│        │  │              │  history merged into spec_json
│(or     │  └──────┬───────┘
│ repair)│         │
│        │         ▼
│        │  ┌──────────────┐
│        │  │  clarifier   │  Re-review updated spec
│        │  └──────┬───────┘
│        │         │
│        │         ▼
│        │   (route → generate / clarification_needed / error)
│        │
└───┬────┘
    │
    ▼
┌──────────┐
│ validate │  1. Static analysis (lua-checker)
│          │  2. Runtime execution (lua-validator)
└────┬─────┘
     │
     ▼
  ┌───────────────────────┐
  │  route_after_validate │
  └──┬──────────┬─────────┘
     │          │
     │ success  │ failure, attempt ≤ MAX_REPAIRS → generate (repair)
     │          │
     ▼          ▼
  ┌──────┐   (loop back)
  │ done │
  └──────┘

Terminal nodes: clarification_needed, done, error
```

### Routing Functions

| Router | Condition | Target |
|---|---|---|
| **route_entry** | `clarifying` is True | → `update_spec` |
| | `clarifying` is False | → `spec` |
| **route_after_clarifier** | `phase == "error"` or `error` is set | → `error` |
| | `is_ambiguous` is True | → `clarification_needed` (terminal) |
| | otherwise (spec approved) | → `generate` |
| **route_after_validate** | `validation_success` is True | → `done` (terminal) |
| | `validation_success` is False, `generation_attempt` ≤ 2 | → `generate` (repair) |
| | `validation_success` is False, `generation_attempt` > 2 | → `error` (terminal) |

### Node Details

| Node | What It Does |
|---|---|
| **extract_context** | Parses the context JSON (if provided), walks `wf.vars` and `wf.initVariables`, builds a compact schema summary for grounding. |
| **spec** | Calls the spec LLM agent to extract a structured JSON spec from the user's natural-language request (first run, no clarification history). |
| **update_spec** | Re-entered when the user answers a clarification question (`clarifying=True`). Re-calls the spec agent with the full clarification history appended, producing an updated spec. |
| **clarifier** | Deterministic policy (`spec_logic.py`) that checks the spec for blockers: missing goal, unclear return value, unresolved input path. Approves the spec, asks **one** question, or blocks with error. |
| **generate** | Generates Lua code from the spec. On repair attempts (attempts 2–3), the prompt also includes the failed code + validation error + stderr for self-correction. |
| **validate** | Runs static analysis (lua-checker) then sandboxed execution (lua-validator). Returns success/failure with diagnostics. |

---

## Clarification & Iteration Flow

### When Does the System Ask Questions?

The clarifier node (`spec_logic.py`) checks for three types of blockers:

| Blocker | When It Triggers | Example Question |
|---|---|---|
| **goal** | The task's purpose is unclear — what should the script accomplish? | *"What is the main goal of the script?"* |
| **return_value** | It's unclear what the script should return. | *"What should the script return as a result?"* |
| **input_path** | The task mentions data that exists in context, but the exact path is ambiguous. | *"Which variable contains the data you want to process?"* |

### Clarification Rules

- **At most one question per request.** The system never bombards the user with multiple questions.
- **Priority order:** goal → return_value → input_path.
- **Never asks about:** edge cases, nil/null handling, fallback behavior, invalid formats, error handling, type checks, helper field names, structure details, style preferences, optimization preferences.
- **Auto-resolution:** Before asking, the system tries to resolve ambiguity from the spec, the request text, the context summary, or prior clarification history.
- **No repeated questions:** If the same question was already asked, the pipeline blocks with an error instead of looping.

### Language Detection

The system automatically detects whether the user's request is in **Russian** or **English** and adapts all clarification questions, prompts, and messages accordingly.

### Multi-Turn Dialogue

After the user answers a clarification question:

1. The backend persists the answer in Redis.
2. The pipeline re-enters through `update_spec_node`, merging the answer into the spec.
3. The clarifier reviews the updated spec.
4. If approved → code generation proceeds. If still blocked → error.

---

## Validation System

Generated Lua code passes through **two validation stages**:

### 1. Static Analysis — `lua-checker` (Go)

Runs AST-based analysis to detect:

| Check | Description |
|---|---|
| **Forbidden functions** | Blocks: `os.execute`, `os.remove`, `io.popen`, `loadfile`, `dofile`, `load`, `loadstring`, `debug.*`, `package.loadlib`, `require` |
| **JsonPath detection** | Flags `$.` pattern usage |
| **Safe `wf` access** | Ensures `wf` is accessed only through `wf.vars` or `wf.initVariables` |
| **Allowed helpers** | Only `_utils.array.new()` and `_utils.array.markAsArray()` are permitted |

**Source:** `services/lua-checker/internal/service/checker.go`

### 2. Runtime Execution — `lua-validator` (Python)

Executes the code in a **sandboxed subprocess**:

| Feature | Detail |
|---|---|
| **Lua version** | 5.4 |
| **Sandbox** | Code is wrapped in a template with `wf` mock, `_utils.array` mock, and `dkjson` JSON parser |
| **Timeout** | Configurable (default 5000 ms) |
| **Result marker** | `___RESULT___=` prefix for test assertions |
| **Returns** | Success/failure, stdout, stderr, exit code, execution time |

**Source:** `services/lua-validator/main.py`

### Sandbox Template

The validator wraps user code in a template that provides:
- A `wf` mock with `vars` and `initVariables` tables.
- An `_utils.array` mock with `new()` and `markAsArray()`.
- A `dkjson` JSON parser/serializer.
- Result serialization via `___RESULT___=` marker.

---

## Configuration

### Environment Variables

#### LLM Service (`services/llm/`)

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama API URL |
| `LUA_CHECKER_HOST` | `lua-checker` | Lua checker hostname |
| `LUA_CHECKER_PORT` | `50053` | Lua checker gRPC port |
| `LUA_VALIDATOR_HOST` | `lua-validator` | Lua validator hostname |
| `LUA_VALIDATOR_PORT` | `50052` | Lua validator gRPC port |

#### Backend (`services/backend/`)

| Variable | Default | Description |
|---|---|---|
| `LLM_ADDR` | `localhost:50051` | LLM gRPC address |
| `REDIS_ADDR` | `localhost:6379` | Redis address |
| `PIPELINE_STATE_TTL` | `24h` | Session TTL in Redis |
| `SESSION_LOCK_TTL` | `20m` | Session lock TTL |
| `LLM_REQUEST_TIMEOUT` | `15m` | LLM request timeout |

#### Frontend (`services/frontend/`)

| Variable | Default | Description |
|---|---|---|
| `BACKEND_URL` | `http://backend:8080` | Backend API URL |

#### Lua Validator (`services/lua-validator/`)

| Variable | Default | Description |
|---|---|---|
| `LUA_INTERPRETER` | `lua5.4` | Lua binary path |

#### Tests (`services/tests/`)

| Variable | Default | Description |
|---|---|---|
| `LLM_TARGET` | `localhost:50051` | LLM gRPC target for tests |
| `VALIDATOR_TARGET` | `localhost:50052` | Validator gRPC target for tests |

### Ollama Server Settings

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Maximum concurrently loaded models |
| `OLLAMA_NUM_PARALLEL` | `1` | Number of parallel request slots |

---

## Running Tests

The project includes **30+ parametrized integration tests** covering math, strings, arrays, objects, nested paths, date conversions, FizzBuzz, and more.

### Run Tests via Docker

```bash
docker compose --profile tests up --build tests
```

### Run Tests Locally

```bash
cd services/tests
uv run pytest -v
```

### Test Cases

Test cases are defined in `services/tests/testcases.json`. Each test case includes:
- A natural-language task description
- Expected input data
- Expected output

Tests run the full pipeline: LLM generation → static analysis → runtime execution → result comparison.

### Interactive Mode

Tests can optionally run in interactive mode, where clarification questions are displayed and answered during the test run:

```bash
uv run pytest -v -k test_pipeline --interactive
```

---

## API Reference

### REST API (Backend, port 8080)

#### `POST /api/v1/pipeline/start`

Starts a new pipeline session.

**Request:**
```json
{
  "request": "Write a function that returns Fibonacci numbers up to n",
  "context": "{\"wf\": {\"vars\": {\"input\": 10}, \"initVariables\": {}}}"
}
```

**Response:**
```json
{
  "session_id": "abc123",
  "phase": "done",
  "code": "-- Lua code here...",
  "clarification_question": null
}
```

#### `POST /api/v1/pipeline/clarify`

Answers a clarification question for an existing session.

**Request:**
```json
{
  "session_id": "abc123",
  "answer": "The goal is to filter even numbers"
}
```

**Response:**
```json
{
  "session_id": "abc123",
  "phase": "done",
  "code": "-- Generated Lua code...",
  "clarification_question": null
}
```

### gRPC Services

| Service | Port | Proto File |
|---|---|---|
| LLM Pipeline | 50051 | `proto/api/llm/v1/llm.proto` |
| Lua Validator | 50052 | `proto/api/lua_validator/v1/validator.proto` |
| Lua Checker | 50053 | `proto/api/lua_checker/v1/checker.proto` |

#### LLM Service RPCs

- **`StartOrContinue`** — Start a new session or continue an existing one.
- **`AnswerClarification`** — Submit an answer to a pending clarification question.

---

## Project Structure

```
.
├── docker-compose.yml              # Main compose file (CPU mode)
├── docker-compose.gpu.yml          # GPU overlay compose file
├── Makefile                        # Top-level build orchestrator
├── README.md                       # This file
├── .dockerignore
│
├── proto/api/
│   ├── llm/v1/llm.proto            # LLM pipeline gRPC definition
│   ├── lua_checker/v1/checker.proto # Static checker gRPC definition
│   └── lua_validator/v1/validator.proto  # Runtime validator gRPC definition
│
├── services/
│   ├── llm/                        # Core multi-agent pipeline
│   │   ├── graph.py                # LangGraph state machine
│   │   ├── prompts.py              # All system prompts + few-shot examples
│   │   ├── spec_logic.py           # Deterministic spec normalization & blocker detection
│   │   ├── state.py                # PipelineState TypedDict
│   │   ├── main.py                 # gRPC server entry point
│   │   ├── context_normalizer.py   # Context JSON parser
│   │   ├── validator_client.py     # gRPC client to lua-validator
│   │   ├── checker_client.py       # gRPC client to lua-checker
│   │   ├── startup.sh              # Ollama wait + model pull + server start
│   │   ├── pyproject.toml          # Python dependencies
│   │   ├── Dockerfile
│   │   └── Makefile                # Proto code generation
│   │
│   ├── backend/                    # REST API + session management
│   │   ├── go.mod
│   │   ├── Dockerfile
│   │   └── Makefile
│   │
│   ├── frontend/                   # Streamlit web UI
│   │   ├── app.py                  # Main Streamlit application
│   │   ├── transport.py            # Transport wrapper parser
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   ├── lua-validator/              # Sandboxed Lua execution
│   │   ├── main.py                 # gRPC server + Lua subprocess wrapper
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── lua-checker/                # Static Lua AST analysis
│   │   ├── internal/service/checker.go
│   │   ├── go.mod
│   │   ├── Dockerfile
│   │   └── Makefile
│   │
│   └── tests/                      # Integration tests
│       ├── test_local_script.py    # Parametrized pytest tests
│       ├── conftest.py             # gRPC stub fixtures
│       ├── testcases.json          # 30+ test cases
│       ├── pyproject.toml
│       └── Dockerfile
```

---

## Reproducibility Checklist

For evaluators and reviewers:

- [x] **Model tag specified:** `qwen2.5-coder:7b-instruct-q4_K_M`
- [x] **Ollama parameters documented:** `num_ctx=4096`, `num_predict=256`, `batch=1`, `parallel=1`
- [x] **GPU requirement:** NVIDIA, ≥ 8 GB VRAM, peak memory ≤ 8.0 GB
- [x] **No external AI APIs:** Zero calls to OpenAI, Anthropic, Google, or any external AI vendor
- [x] **All dependencies in repo:** `pyproject.toml`, `go.mod`, `Dockerfile` for each service
- [x] **Single-command start:** `docker compose up --build`
- [x] **GPU mode available:** `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build`
- [x] **Tests included:** 30+ parametrized test cases in `services/tests/`
- [x] **Proto definitions:** All gRPC contracts in `proto/api/`
- [x] **Startup script auto-pulls model:** `startup.sh` waits for Ollama, checks/pulls the model
- [x] **Local knowledge base:** Few-shot examples embedded in prompts; context schema builder walks provided JSON; no external retrieval
- [x] **Language support:** Russian and English, auto-detected
- [x] **Validation:** Static AST analysis + sandboxed runtime execution
- [x] **Iteration support:** Clarification questions + repair loop (up to 2 retries)

---

## Evaluation Criteria Mapping

### 1. Quality & Correctness of Generated Lua Code (0–50 points)

- The pipeline generates code from a **structured JSON spec** extracted by an LLM agent, ensuring alignment with the task.
- Code is validated through **both static analysis and runtime execution** before being returned.
- A **repair loop** (up to 2 retries) self-corrects validation failures.
- Few-shot examples in prompts cover common patterns: Fibonacci, array operations, CSV filtering, array marking.
- The context schema builder grounds generation in the actual variable structure available to the script.

### 2. Agency & Iteration Quality (0–25 points)

- **Clarification system:** The clarifier node asks targeted questions when the task is ambiguous, with strict rules preventing question spam.
- **Multi-turn dialogue:** User answers are merged into the spec via `update_spec_node`, enabling informed re-generation.
- **Repair loop:** Validation failures trigger self-correction with full error context fed back to the model.
- The pipeline is explicitly designed as a **managed cycle**, not a single-shot generation.

### 3. Locality, Privacy & Reproducibility (0–25 points)

- **Zero external AI calls.** All inference runs on local Ollama.
- **Open-source model:** `qwen2.5-coder:7b-instruct-q4_K_M` — freely available, quantized, fits in 8 GB VRAM.
- **Docker Compose** starts the entire stack with one command.
- **All dependencies, proto files, and startup scripts** are included in the repository.
- **Data never leaves the infrastructure:** context, requests, and generated code are processed entirely within the Docker network.
- **Full reproducibility:** `docker compose up --build` produces an identical environment on any machine with Docker and a compatible GPU.

---

## Troubleshooting

### Ollama Model Not Loading

```bash
# Check if Ollama is running
docker compose ps ollama

# Check Ollama logs
docker compose logs ollama

# Verify model is pulled
docker compose exec ollama ollama list
```

### VRAM Exceeds 8 GB

- Ensure you're using the **Q4_K_M** quantized model, not the full-precision version.
- Check that `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_MAX_LOADED_MODELS=1` are set.
- Close other GPU processes that may be consuming VRAM.

### Services Won't Start

```bash
# View all logs
docker compose logs

# View specific service logs
docker compose logs llm
docker compose logs backend
docker compose logs frontend
```

### Lua Validator Fails

- Ensure `lua5.4` is installed in the container (handled by Dockerfile).
- Check the sandbox template wrapping in `services/lua-validator/main.py`.

### gRPC Connection Errors

- Verify all services are on the same Docker network.
- Check hostname resolution: services use Docker DNS names (`llm`, `lua-validator`, `lua-checker`).

### Frontend Not Responding

- Ensure the backend is running: `curl http://localhost:8080/health`
- Check browser console for CORS or network errors.
- Verify `BACKEND_URL` points to the correct backend address.

---

## License

This project is provided as-is for evaluation and educational purposes.

---

## Authors

Team **Ivanon Ivan** — True Tech Hack 2026
