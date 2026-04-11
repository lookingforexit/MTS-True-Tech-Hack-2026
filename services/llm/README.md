# LLM Service (LangGraph — Multi-Agent Pipeline)

Stateful multi-agent LLM pipeline for reliable Lua code generation built on **LangGraph**.

## Architecture

```
User Request
   ↓
┌─ Multi-Agent LangGraph Workflow ──────────────────────────────────────┐
│                                                                        │
│  START → spec → clarifier ──ambiguous?──→ CLARIFY                     │
│                     │                      ↑                          │
│                     │ approved               │ answer                  │
│                     ↓                      │                          │
│                   test → generate → validate ──fail?──→ repair ─┐     │
│                     │            │              │               │     │
│                     │            │           success            │     │
│                     │            ↓              ↓               │     │
│                     │          ranker ←────────┘               │     │
│                     │            │                              │     │
│                     │            ↓                              │     │
│                     │           DONE                            │     │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
   ↓
Final Code (or clarification question, or error)
```

### Pipeline Stages

| # | Agent | Responsibility |
|---|-------|---------------|
| 1 | **Spec-agent** | Normalizes user request into a structured JSON spec (`task_type`, `goal`, `input`, `output`, `constraints`, `assumptions`, `missing_critical_fields`) |
| 2 | **Clarifier-agent** | Reviews the spec — either approves it or asks **one** specific clarification question about a missing critical field |
| 3 | **Test-agent** | Generates a minimal but comprehensive test suite from the spec (happy-path + edge cases) |
| 4 | **Generator-agent** | Produces **N** independent Lua candidates (default: 3) from the spec only — no raw user text |
| 5 | **Validator stack** | Runs each candidate against all tests via the Lua Validator gRPC service (syntax + runtime + semantic) |
| 6 | **Repair-agent** | Fixes failing candidates using test failure details (expected vs actual output, tracebacks) and the original spec |
| 7 | **Ranker** | Selects the best candidate: all-passing → shortest → simplest. Falls back to most-passing if none pass all |

### Why This Design

- **Spec-driven**: Generator and Repair work from a JSON spec, not raw user text — eliminates drift and hallucination.
- **Test-first**: Tests are derived from the spec before any code is generated, ensuring validation matches intent.
- **Multi-candidate**: Generating 2-4 candidates and ranking them gives the pipeline options to choose the best.
- **Repair with context**: Repair-agent sees the failing test details (not just "an error"), enabling targeted fixes.
- **Deterministic**: All LLM calls use temperature=0 (or 0.2 for generation variety), ensuring reproducibility.

### State Persistence

Each session has a `session_id`. If the pipeline stops at clarification, the state is saved.
The client can later call `AnswerClarification` with the user's answer and the pipeline resumes from where it left off.

### Repair Loop

If validation fails, the graph routes to `repair` → back to `validate`.
Max repair iterations controlled by `MAX_REPAIRS` env var (default: 2).

## Model

- **Model**: `qwen2.5-coder:1.5b-instruct-q4_K_M`
- Pulled from Ollama on first use (в `docker-compose` — сервис `ollama-pull`)

## gRPC Service

Port **50051**. Proto: [`proto/api/llm/v1/llm.proto`](../../proto/api/llm/v1/llm.proto)

### RPCs

| Method | Description |
|---|---|
| `StartOrContinue` | Start a new pipeline or continue an existing session |
| `AnswerClarification` | Answer the clarification question and resume |
| `GetSessionState` | Get current state of a session |

### Example (Go)

```go
conn, _ := grpc.Dial("llm:50051", grpc.WithTransportCredentials(insecure.NewCredentials()))
client := llmv1.NewLLMServiceClient(conn)

// Start
resp, _ := client.StartOrContinue(ctx, &llmv1.SessionRequest{
    SessionId: "my-session-1",
    Request:   "Write a Lua script that reads numbers from stdin and prints their sum",
})

if resp.Phase == llmv1.SessionPhase_CLARIFICATION_NEEDED {
    // Show question to user, then answer:
    resp, _ = client.AnswerClarification(ctx, &llmv1.AnswerRequest{
        SessionId: "my-session-1",
        Answer:    "One number per line, empty line means end of input",
    })
}

fmt.Println(resp.GetCode())
```

## Environment Variables

| Var | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama endpoint |
| `LLM_MODEL` | `qwen2.5-coder:1.5b-instruct-q4_K_M` | Model name |
| `LUA_VALIDATOR_HOST` | `lua-validator` | Lua validator gRPC host |
| `LUA_VALIDATOR_PORT` | `50052` | Lua validator gRPC port |
| `MAX_REPAIRS` | `2` | Max repair iterations |
| `CANDIDATE_COUNT` | `3` | Number of candidates to generate |

## Running

```bash
docker compose up llm
```
