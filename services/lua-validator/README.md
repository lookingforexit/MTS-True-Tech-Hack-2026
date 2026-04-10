# Lua Validator Service

gRPC service that **actually runs** Lua code and returns execution results.

## How It Works

1. Receives Lua code via gRPC
2. Writes it to a temp file
3. Executes with `lua5.4` interpreter (sandboxed subprocess)
4. Returns stdout, stderr, exit code, and execution time

## gRPC Service

Port **50052**. Proto: [`proto/api/lua_validator/v1/validator.proto`](../../proto/api/lua_validator/v1/validator.proto)

### RPCs

| Method | Description |
|---|---|
| `Validate` | Run Lua code and return execution result |

### Example (Go)

```go
conn, _ := grpc.Dial("lua-validator:50052", grpc.WithTransportCredentials(insecure.NewCredentials()))
client := luavalidatorv1.NewLuaValidatorServiceClient(conn)

resp, _ := client.Validate(ctx, &luavalidatorv1.ValidateRequest{
    Code:      `print("hello")`,
    TimeoutMs: 5000,
})

if resp.Success {
    fmt.Println("Output:", resp.Output)
} else {
    fmt.Println("Error:", resp.Error)
}
```

## Environment Variables

| Var | Default | Description |
|---|---|---|
| `LUA_INTERPRETER` | `lua5.4` | Path to Lua binary |

## Running

```bash
docker compose up lua-validator
```
