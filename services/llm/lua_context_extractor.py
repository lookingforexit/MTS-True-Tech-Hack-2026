"""Lua context extractor: runs a Lua script in lua-validator to extract wf structure.

This module sends the JSON context to the lua-validator service via a special
Lua introspection script. The script runs inside the sandboxed Lua environment
(where `wf` is already populated from the context JSON) and serializes the
entire structure back to stdout.

This is required by the hackathon rules: we cannot use the backend JSON directly;
we must extract the data from within the Lua environment itself.
"""

import json
import logging

from validator_client import LuaValidatorClient

logger = logging.getLogger(__name__)

# Lua introspection script that serializes the wf environment back to JSON.
# This script runs INSIDE the lua-validator sandbox where `wf` is already set up.
#
# The sandbox wraps user code and serializes the RETURN VALUE via to_json().
# So we return the wf table directly — the sandbox handles JSON serialization.
LUA_INTROSPECTION_SCRIPT = r"""
-- Build a clean copy of wf without runtime functions (like wf.get),
-- and wrap it under the "wf" key so the LLM sees {"wf": {...}}
local clean_wf = {}
if wf then
    for k, v in pairs(wf) do
        if type(v) ~= "function" then
            clean_wf[k] = v
        end
    end
end
return { wf = clean_wf }
"""


class LuaContextExtractor:
    """Extracts context from the Lua environment via introspection."""

    def __init__(self, validator_client: LuaValidatorClient):
        self._validator = validator_client

    def extract(self, context_json: str | None) -> dict:
        """Run the introspection script and return the extracted structure.

        Args:
            context_json: The JSON context string from the backend (used to set
                         up the Lua environment via env_vars).

        Returns:
            Dict with the extracted wf structure from the Lua environment.
        """
        if not context_json:
            logger.warning("No context provided, returning empty extraction")
            return {"wf": None, "error": "no_context_provided"}

        # Parse the context to validate it
        try:
            context_data = json.loads(context_json)
        except json.JSONDecodeError as e:
            logger.error("Invalid context JSON: %s", e)
            return {"wf": None, "error": f"invalid_context_json: {str(e)}"}

        # The lua-validator sandbox expects CONTEXT_JSON env var
        # We pass the context through env_vars so the sandbox can use it
        env_vars = json.dumps({"CONTEXT_JSON": context_json})

        try:
            response = self._validator.validate(
                code=LUA_INTROSPECTION_SCRIPT,
                env_vars=env_vars,
            )

            if response.success:
                output = (response.output or "").strip()
                logger.debug("Raw introspection output: %s", output)

                # The sandbox prefixes output with ___RESULT___=, strip it
                result_marker = "___RESULT___="
                if result_marker in output:
                    json_str = output.split(result_marker, 1)[1].strip()
                else:
                    json_str = output

                try:
                    extracted = json.loads(json_str)
                    logger.info("Successfully extracted Lua context: %s", list(extracted.keys()) if isinstance(extracted, dict) else "non-dict result")
                    return extracted
                except json.JSONDecodeError as e:
                    logger.warning("Could not parse introspection output: %s", e)
                    return {"wf": None, "raw_output": output, "parse_error": str(e)}
            else:
                error_msg = response.error or "unknown error"
                logger.warning("Introspection script failed: %s", error_msg)
                return {"wf": None, "error": error_msg}

        except Exception as e:
            logger.exception("Exception during context extraction")
            return {"wf": None, "error": f"exception: {str(e)}"}
