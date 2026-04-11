"""gRPC service that validates Lua code by actually running it."""

import logging
import os
import subprocess
import tempfile
import time
from concurrent import futures

import grpc

import validator_pb2
import validator_pb2_grpc

logger = logging.getLogger(__name__)

LUA_INTERPRETER = os.environ.get("LUA_INTERPRETER", "lua5.4")
DEFAULT_TIMEOUT_MS = 5000


class LuaValidatorServicer(validator_pb2_grpc.LuaValidatorServiceServicer):
    """Runs Lua code in a sandboxed subprocess and returns execution results."""

    def Validate(self, request, context):
        timeout_ms = request.timeout_ms if request.HasField("timeout_ms") else DEFAULT_TIMEOUT_MS
        timeout_sec = timeout_ms / 1000.0

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".lua", delete=False
            ) as f:
                f.write(request.code)
                script_path = f.name

            start = time.monotonic()

            proc = subprocess.run(
                [LUA_INTERPRETER, script_path],
                input=request.stdin if request.HasField("stdin") else "",
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )

            exec_time_ms = int((time.monotonic() - start) * 1000)

            return validator_pb2.ValidateResponse(
                success=proc.returncode == 0,
                output=proc.stdout,
                error=proc.stderr,
                exit_code=proc.returncode,
                exec_time_ms=exec_time_ms,
            )

        except subprocess.TimeoutExpired:
            return validator_pb2.ValidateResponse(
                success=False,
                output="",
                error=f"Execution timed out after {timeout_ms}ms",
                exit_code=-1,
                exec_time_ms=timeout_ms,
            )
        except FileNotFoundError:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(
                f"Lua interpreter '{LUA_INTERPRETER}' not found. "
                "Install lua5.4 or set LUA_INTERPRETER env var."
            )
            return validator_pb2.ValidateResponse()
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return validator_pb2.ValidateResponse()
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    validator_pb2_grpc.add_LuaValidatorServiceServicer_to_server(
        LuaValidatorServicer(), server
    )
    server.add_insecure_port("[::]:50052")
    logger.info("Starting Lua Validator gRPC server on [::]:50052")
    server.start()
    logger.info("Lua Validator gRPC server started")
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
