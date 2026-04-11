# LLM Service (LangGraph)

Stateful deterministic LLM pipeline for Lua code generation built on **LangGraph**.

## Architecture

```
User Request
   ↓
┌─ LangGraph Workflow ──────────────────────────────┐
│                                                    │
│  START → clarify ──ambiguous?──→ CLARIFY           │
│              │                      ↑              │
│              │ no                   │ answer       │
│              ↓                      │              │
│          generate ──→ validate ───fail?──→ repair  │
│              │              │              │       │
│              │           success         retry    │
│              ↓              ↓              ↓       │
│             DONE          DONE          validate   │
│                                                    │
└────────────────────────────────────────────────────┘
   ↓
Final Code (or clarification question, or error)
```

### State Persistence

Each session has a `session_id`. If the pipeline stops at clarification, the state is saved.
The client can later call `AnswerClarification` with the user's answer and the pipeline resumes from where it left off.

### Repair Loop

If validation fails, the graph routes to `repair` → back to `validate`.
Max repair iterations controlled by `MAX_REPAIRS` env var (default: 2).

## Model

- **Model**: `qwen2.5-coder:7b-instruct-q5_0`
- Pulled from Ollama on first use

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
    Request:   "Write a Lua script that prints hello",
})

if resp.Phase == llmv1.SessionPhase_CLARIFICATION_NEEDED {
    // Show question to user, then answer:
    resp, _ = client.AnswerClarification(ctx, &llmv1.AnswerRequest{
        SessionId: "my-session-1",
        Answer:    "It should print 'Hello, World!' to stdout",
    })
}

fmt.Println(resp.GetCode())
```

## Environment Variables

| Var | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama endpoint |
| `LLM_MODEL` | `qwen2.5-coder:7b-instruct-q5_0` | Model name |
| `LUA_VALIDATOR_HOST` | `lua-validator` | Lua validator gRPC host |
| `LUA_VALIDATOR_PORT` | `50052` | Lua validator gRPC port |
| `MAX_REPAIRS` | `2` | Max repair iterations |

## Running

```bash
docker compose up llm
```
