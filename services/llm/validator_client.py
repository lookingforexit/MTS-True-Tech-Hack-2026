"""gRPC client for the Lua Validator service."""

import grpc

import validator_pb2
import validator_pb2_grpc


class LuaValidatorClient:
    """Thin wrapper around the Lua Validator gRPC stub."""

    def __init__(self, host: str = "lua-validator", port: int = 50052):
        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = validator_pb2_grpc.LuaValidatorServiceStub(self.channel)

    def validate(self, code: str, stdin: str = "", timeout_ms: int = 5000) -> validator_pb2.ValidateResponse:
        """Run Lua code and return validation result."""
        req = validator_pb2.ValidateRequest(
            code=code,
            stdin=stdin if stdin else None,
            timeout_ms=timeout_ms,
        )
        return self.stub.Validate(req)
