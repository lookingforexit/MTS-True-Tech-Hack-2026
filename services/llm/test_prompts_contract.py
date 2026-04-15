from prompts import CLARIFIER_AGENT_PROMPT, SPEC_AGENT_PROMPT, make_generate_prompt, make_repair_prompt


def test_spec_prompt_mentions_return_value_and_special_input_path_states():
    assert "return_value" in SPEC_AGENT_PROMPT
    assert "__INPUT_PATH_NOT_APPLICABLE__" in SPEC_AGENT_PROMPT
    assert "__INPUT_PATH_NEEDS_CLARIFICATION__" in SPEC_AGENT_PROMPT
    assert "wf.InitVariables" in SPEC_AGENT_PROMPT


def test_clarifier_prompt_forbids_edge_case_questions():
    assert "edge cases" in CLARIFIER_AGENT_PROMPT
    assert "Ask exactly ONE specific clarification question" in CLARIFIER_AGENT_PROMPT


def test_generator_prompt_allows_only_expected_helpers():
    prompt = make_generate_prompt("en")
    assert "_utils.array.new()" in prompt
    assert "_utils.array.markAsArray(arr)" in prompt
    assert "DO NOT IMPORT, REQUIRE, LOAD, OR DELEGATE WORK TO ANY OTHER LIBRARY" in prompt
    assert "os.time(os.date(...))" in prompt


def test_repair_prompt_preserves_semantic_contract():
    prompt = make_repair_prompt("en")
    assert "Preserve `goal`, `input_path`, and `return_value`" in prompt
    assert "_utils.array.markAsArray(arr)" in prompt
    assert "Do not rewrite the task into another algorithm." in prompt
