"""Deterministic LLM pipeline with three modes: clarify, generate, repair."""

import re
import ollama
from pydantic import BaseModel
from prompts import CLARIFY_SYSTEM_PROMPT, GENERATE_SYSTEM_PROMPT, REPAIR_SYSTEM_PROMPT

MODEL = "qwen2.5-coder:1.5b-instruct-q4_K_M"
MAX_REPAIR_ITERATIONS = 1


class ClarifyResult(BaseModel):
    is_ambiguous: bool
    question: str | None = None


class GenerateResult(BaseModel):
    code: str


class RepairResult(BaseModel):
    code: str
    was_repaired: bool


class PipelineResult(BaseModel):
    needs_clarification: bool = False
    clarify_question: str | None = None
    code: str | None = None
    was_repaired: bool = False


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Synchronous call to Ollama."""
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        options={
            "temperature": 0.2,
            "num_predict": 2048,
        },
    )
    return response["message"]["content"]


def _extract_code_block(text: str) -> str:
    """Extract Lua code from markdown code blocks."""
    pattern = r"```lua\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: try to extract any code block
    pattern_any = r"```\s*\n(.*?)\n```"
    match = re.search(pattern_any, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # If no code block found, return the whole text (trimmed)
    return text.strip()


def clarify(request: str) -> ClarifyResult:
    """Mode 1: Check if the request is ambiguous."""
    response = _call_llm(CLARIFY_SYSTEM_PROMPT, f"Request: {request}")

    # Parse the response
    is_ambiguous = "AMBIGUITY: true" in response

    if is_ambiguous:
        # Extract the question
        question_match = re.search(r"QUESTION:\s*(.+)", response)
        question = question_match.group(1).strip() if question_match else None
        return ClarifyResult(is_ambiguous=True, question=question)

    return ClarifyResult(is_ambiguous=False)


def generate(request: str, context: str | None = None) -> GenerateResult:
    """Mode 2: Generate Lua code."""
    user_prompt = f"Request: {request}"
    if context:
        user_prompt += f"\n\nAdditional context: {context}"

    response = _call_llm(GENERATE_SYSTEM_PROMPT, user_prompt)
    code = _extract_code_block(response)
    return GenerateResult(code=code)


def repair(broken_code: str, errors: str, original_request: str) -> RepairResult:
    """Mode 3: Repair broken Lua code."""
    user_prompt = (
        f"Original request: {original_request}\n\n"
        f"Broken code:\n```lua\n{broken_code}\n```\n\n"
        f"Validation errors:\n{errors}\n\n"
        f"Fix the code."
    )

    response = _call_llm(REPAIR_SYSTEM_PROMPT, user_prompt)
    code = _extract_code_block(response)
    return RepairResult(code=code, was_repaired=True)


def run_pipeline(
    request: str,
    context: str | None = None,
    validate_fn=None,
) -> PipelineResult:
    """
    Run the deterministic pipeline:
    1. Clarify — check if request is ambiguous
    2. Generate — generate Lua code
    3. Validate — Python validation (external function)
    4. Repair — at most 1 repair iteration if validation fails

    Args:
        request: User's request
        context: Additional context (optional)
        validate_fn: Python function that validates the generated code.
                     Returns (is_valid: bool, errors: str)

    Returns:
        PipelineResult with the final code or a clarification question.
    """
    # Step 1: Clarify
    clarify_result = clarify(request)
    if clarify_result.is_ambiguous:
        return PipelineResult(
            needs_clarification=True,
            clarify_question=clarify_result.question,
        )

    # Step 2: Generate
    gen_result = generate(request, context)
    code = gen_result.code

    # Step 3: Validate (if validator provided)
    if validate_fn is not None:
        is_valid, errors = validate_fn(code)
        if not is_valid:
            # Step 4: Repair (max 1 iteration)
            repair_result = repair(code, errors, request)
            code = repair_result.code
            return PipelineResult(code=code, was_repaired=True)

    return PipelineResult(code=code)
