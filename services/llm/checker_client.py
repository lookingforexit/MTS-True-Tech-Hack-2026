"""gRPC client for the Lua Checker service."""

import grpc

from gen.api.lua_checker.v1 import checker_pb2
from gen.api.lua_checker.v1 import checker_pb2_grpc


class LuaCheckerClient:
    """Thin wrapper around the Lua Checker gRPC stub."""

    def __init__(self, host: str = "lua-checker", port: int = 50053, rpc_timeout_s: float = 5.0):
        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = checker_pb2_grpc.LuaCheckerStub(self.channel)
        self.rpc_timeout_s = rpc_timeout_s

    def check(self, code: str) -> checker_pb2.CheckResponse:
        """Run static Lua checks for the provided source code."""
        req = checker_pb2.CheckRequest(script=code)
        return self.stub.Check(req, timeout=self.rpc_timeout_s)
