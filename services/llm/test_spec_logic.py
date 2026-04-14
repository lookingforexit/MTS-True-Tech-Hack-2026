import json

from spec_logic import (
    INPUT_PATH_NEEDS_CLARIFICATION,
    INPUT_PATH_NOT_APPLICABLE,
    evaluate_spec,
)


def _context(payload):
    return {"wf": payload}


def test_case_1_recall_time_path_resolves_without_question():
    spec = evaluate_spec(
        {
            "goal": "Convert recallTime to unix format",
            "input_path": "recallTime",
            "output_type": "single_value",
            "transformation": "Parse the input time string deterministically and convert it to unix timestamp",
            "return_value": "unix timestamp parsed from recallTime",
        },
        request="Convert the time in variable recallTime to unix format",
        raw_context=_context({"initVariables": {"recallTime": "2024-10-01T10:00:00Z"}, "vars": {}}),
        dialog_language="en",
    )

    assert spec["input_path"] == "wf.initVariables.recallTime"
    assert spec["clarification_required"] is False
    assert "wf.InitVariables" not in json.dumps(spec)


def test_case_2_greeting_named_object_resolves_without_question():
    spec = evaluate_spec(
        {
            "goal": "Generate a greeting string for the user",
            "input_path": "user",
            "output_type": "single_value",
            "transformation": "Build the greeting from the visible user fields",
            "return_value": "greeting string in the required format",
        },
        request="Generate a greeting string for the user using object user",
        raw_context=_context(
            {
                "vars": {
                    "user": {
                        "first_name": "Ivan",
                        "last_name": "Ivanov",
                        "role": "admin",
                    }
                },
                "initVariables": {},
            }
        ),
        dialog_language="en",
    )

    assert spec["input_path"] == "wf.vars.user"
    assert spec["clarification_required"] is False
    assert spec["return_value"] == "greeting string in the required format"


def test_case_3_sort_named_array_resolves_without_question():
    spec = evaluate_spec(
        {
            "goal": "Sort users by age descending",
            "input_path": "users",
            "output_type": "filtered_array",
            "transformation": "Sort by age descending",
            "return_value": "sorted users array",
        },
        request="Sort users array by age descending",
        raw_context=_context({"vars": {"users": [{"age": 30}, {"age": 20}]}, "initVariables": {}}),
        dialog_language="en",
    )

    serialized = json.dumps(spec).lower()
    assert spec["input_path"] == "wf.vars.users"
    assert spec["clarification_required"] is False
    assert "nil" not in serialized
    assert "empty" not in serialized


def test_case_4_fibonacci_is_self_contained():
    spec = evaluate_spec(
        {
            "goal": "Compute the 10th Fibonacci number",
            "input_path": "",
            "output_type": "single_value",
            "transformation": "Compute Fibonacci up to index 10",
            "return_value": "10th Fibonacci number",
        },
        request="Write a function and return the 10th Fibonacci number",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="en",
    )

    assert spec["input_path"] == INPUT_PATH_NOT_APPLICABLE
    assert spec["clarification_required"] is False
    assert spec["return_value"] == "10th Fibonacci number"


def test_case_5_unknown_users_path_requires_input_path_clarification():
    spec = evaluate_spec(
        {
            "goal": "Sort users by age descending",
            "input_path": "",
            "output_type": "filtered_array",
            "transformation": "Sort by age descending",
            "return_value": "sorted users array",
        },
        request="Sort users by age descending",
        raw_context=_context({"vars": {"people": {"users": []}}, "initVariables": {"users": []}}),
        dialog_language="en",
    )

    assert spec["input_path"] == INPUT_PATH_NEEDS_CLARIFICATION
    assert spec["clarification_required"] is True
    assert spec["clarification_target"] == "input_path"


def test_case_6_binary_search_prioritizes_return_value_over_input_path():
    spec = evaluate_spec(
        {
            "goal": "Write a binary search function",
            "input_path": "",
            "output_type": "single_value",
            "transformation": "Perform binary search on a sorted array",
            "return_value": "",
        },
        request="Write a binary search function",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="en",
    )

    assert spec["input_path"] == INPUT_PATH_NOT_APPLICABLE
    assert spec["clarification_required"] is True
    assert spec["clarification_target"] == "return_value"


def test_case_7_red_black_tree_node_needs_no_input_or_structure_questions():
    spec = evaluate_spec(
        {
            "goal": "Implement a red-black tree node structure",
            "input_path": "",
            "output_type": "new_structure",
            "transformation": "Create a Lua table for a red-black tree node",
            "return_value": "Lua table representing a red-black tree node",
        },
        request="Implement a red-black tree node structure",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="en",
    )

    serialized = json.dumps(spec).lower()
    assert spec["input_path"] == INPUT_PATH_NOT_APPLICABLE
    assert spec["clarification_required"] is False
    assert spec["return_value"] == "Lua table representing a red-black tree node"
    assert "color" not in serialized
    assert "left" not in serialized
    assert "right" not in serialized
    assert "parent" not in serialized


def test_case_8_input_path_answer_absent_is_respected_for_self_contained_task():
    spec = evaluate_spec(
        {
            "goal": "Compute the 10th Fibonacci number",
            "input_path": "",
            "output_type": "single_value",
            "transformation": "Compute Fibonacci up to index 10",
            "return_value": "10th Fibonacci number",
        },
        request="Write a function and return the 10th Fibonacci number",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="en",
        clarification_history=[
            {
                "question": "What is the exact Lua path to the input data, for example `wf.vars.users`?",
                "answer": "There is no input data here",
                "target": "input_path",
            }
        ],
    )

    assert spec["input_path"] == INPUT_PATH_NOT_APPLICABLE
    assert spec["clarification_required"] is False


def test_case_10_invalid_spec_json_fallback_is_safe():
    spec = evaluate_spec(
        None,
        request="Write a binary search function",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="en",
        parse_failed=True,
    )

    assert spec["spec_parse_failed"] is True
    assert spec["clarification_required"] is True
    assert spec["clarification_target"] == "goal"


def test_case_11_forbidden_question_topics_are_not_present_in_spec():
    spec = evaluate_spec(
        {
            "goal": "Generate a greeting string for the user",
            "input_path": "wf.vars.user",
            "output_type": "single_value",
            "transformation": "Build the greeting from visible fields",
            "return_value": "greeting string in the required format",
        },
        request="Generate a greeting string for the user using object user",
        raw_context=_context(
            {
                "vars": {
                    "user": {
                        "first_name": "Ivan",
                        "last_name": "Ivanov",
                        "role": "admin",
                    }
                }
            }
        ),
        dialog_language="en",
    )

    serialized = json.dumps(spec).lower()
    assert "nil" not in serialized
    assert "empty" not in serialized
    assert "invalid format" not in serialized
    assert "style" not in serialized
    assert "optimization" not in serialized
