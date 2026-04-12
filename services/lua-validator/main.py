"""gRPC service that validates Lua code by actually running it."""

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

from generated.api.lua_validator.v1 import validator_pb2
from generated.api.lua_validator.v1 import validator_pb2_grpc

logger = logging.getLogger(__name__)

LUA_INTERPRETER = os.environ.get("LUA_INTERPRETER", "lua5.4")
DEFAULT_TIMEOUT_MS = 5000

# Lua sandbox template - wraps user code with environment setup
LUA_SANDBOX_TEMPLATE = """
-- 1. ЧИТАЕМ КОНТЕКСТ ИЗ ПЕРЕМЕННОЙ ОКРУЖЕНИЯ
local dkjson = require("dkjson")
local context_json = os.getenv("CONTEXT_JSON")
if not context_json then
    print("ERROR: CONTEXT_JSON environment variable not set")
    os.exit(1)
end

local context = dkjson.decode(context_json)
local wf_data = context.wf or {{vars = {{}}, initVariables = {{}}}}

-- 2. МОКИРУЕМ СРЕДУ (wf и _utils)
wf = wf_data
wf.get = function(self, key)
    return (self.vars and self.vars[key]) or (self.initVariables and self.initVariables[key])
end
package.loaded.wf = wf

_utils = {{
    array = {{ new = function() return {{}} end, markAsArray = function(arr) return arr end }}
}}

-- 3. СЕРИАЛИЗАТОР (Чтобы Python понял ответ)
local function to_json(v)
    local t = type(v)
    if t == "nil" then return "null"
    elseif t == "boolean" or t == "number" then return tostring(v)
    elseif t == "string" then
        local s = string.format("%q", v):gsub("\\\n", "\\n")
        return s
    elseif t == "table" then
        local is_arr, max = true, 0
        for k, _ in pairs(v) do
            if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then is_arr = false break end
            if k > max then max = k end
        end
        local res = {{}}
        if is_arr then
            for i=1, max do table.insert(res, to_json(v[i])) end
            return "[" .. table.concat(res, ",") .. "]"
        else
            for k, val in pairs(v) do table.insert(res, to_json(tostring(k))..":"..to_json(val)) end
            return "{{" .. table.concat(res, ",") .. "}}"
        end
    end
    return '"' .. tostring(v) .. '"'
end

-- 4. ВЫПОЛНЯЕМ КОД МОДЕЛИ И ПЕРЕХВАТЫВАЕМ РЕЗУЛЬТАТ
local function run_llm_code()
{user_code}
end

local success, result = pcall(run_llm_code)
if not success then
    print("RUNTIME_ERROR: " .. tostring(result))
    os.exit(1)
end

-- Выводим результат в консоль (stdout) с секретным маркером
print("___RESULT___=" .. to_json(result))
"""


class LuaValidatorServicer(validator_pb2_grpc.LuaValidatorServiceServicer):
    """Runs Lua code in a sandboxed subprocess and returns execution results."""

    def Validate(self, request, context):
        timeout_ms = request.timeout_ms if request.HasField("timeout_ms") else DEFAULT_TIMEOUT_MS
        timeout_sec = timeout_ms / 1000.0

        # Parse environment variables from JSON (required field)
        try:
            env_vars = json.loads(request.env_vars)
            if not isinstance(env_vars, dict):
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("env_vars must be a JSON object")
                return validator_pb2.ValidateResponse()
        except json.JSONDecodeError as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid JSON in env_vars: {str(e)}")
            return validator_pb2.ValidateResponse()

        try:
            # Clean markdown code blocks if present
            clean_code = re.sub(
                r"^(?:```lua|lua\{)\n?|\n?(?:```|\}lua)$",
                "",
                request.code,
                flags=re.IGNORECASE
            ).strip()

            # Wrap user code in sandbox template
            sandbox_code = LUA_SANDBOX_TEMPLATE.format(user_code=clean_code)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".lua", delete=False
            ) as f:
                f.write(sandbox_code)
                script_path = f.name

            start = time.monotonic()

            # Prepare environment for the subprocess
            proc_env = os.environ.copy()
            proc_env.update(env_vars)

            proc = subprocess.run(
                [LUA_INTERPRETER, script_path],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=proc_env,
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
    
    # Enable reflection for grpcurl
    SERVICE_NAME = 'lua_validator.v1.LuaValidatorService'
    reflection.enable_server_reflection(
        (SERVICE_NAME, reflection.SERVICE_NAME),
        server
    )
    
    server.add_insecure_port("[::]:50052")
    logger.info("Starting Lua Validator gRPC server on [::]:50052")
    server.start()
    logger.info("Lua Validator gRPC server started")
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
