"""gRPC client for the Lua Validator service."""

import grpc

import validator_pb2
import validator_pb2_grpc


class LuaValidatorClient:
    """Thin wrapper around the Lua Validator gRPC stub."""

    def __init__(self, host: str = "lua-validator", port: int = 50052):
        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = validator_pb2_grpc.LuaValidatorServiceStub(self.channel)

    def validate(
        self,
        code: str,
        env_vars: str = "{}",
        timeout_ms: int = 5000,
    ) -> validator_pb2.ValidateResponse:
        """Run Lua code and return validation result.

        Args:
            code: Lua source code to execute.
            env_vars: JSON string with environment variables for the sandbox.
            timeout_ms: Max execution time in milliseconds.
        """
        req = validator_pb2.ValidateRequest(
            code=code,
            env_vars=env_vars,
            timeout_ms=timeout_ms,
        )
        return self.stub.Validate(req)
