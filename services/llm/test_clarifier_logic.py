from spec_logic import (
    INPUT_PATH_NEEDS_CLARIFICATION,
    INPUT_PATH_NOT_APPLICABLE,
    build_clarifier_decision,
    evaluate_spec,
)


def test_clarifier_stays_silent_when_spec_is_complete():
    spec = evaluate_spec(
        {
            "goal": "Generate a greeting string for the user",
            "input_path": "wf.vars.user",
            "output_type": "single_value",
            "transformation": "Build the greeting from the visible user fields",
            "return_value": "greeting string in the required format",
        },
        request="Generate a greeting string for the user using object user",
        raw_context={"wf": {"vars": {"user": {"first_name": "Ivan", "last_name": "Ivanov", "role": "admin"}}}},
        dialog_language="en",
    )

    assert build_clarifier_decision(spec) == {"status": "approved", "question": None, "reason": None}


def test_clarifier_asks_targeted_binary_search_return_question():
    spec = evaluate_spec(
        {
            "goal": "Write a binary search function",
            "input_path": INPUT_PATH_NOT_APPLICABLE,
            "output_type": "single_value",
            "transformation": "Perform binary search on a sorted array",
            "return_value": "",
        },
        request="Write a binary search function",
        raw_context={"wf": {"vars": {}, "initVariables": {}}},
        dialog_language="en",
    )

    decision = build_clarifier_decision(spec)
    assert decision["status"] == "question"
    assert decision["question"] == "What should the binary search return: index, element, or true/false?"


def test_clarifier_asks_exactly_one_targeted_input_path_question():
    spec = evaluate_spec(
        {
            "goal": "Sort users by age descending",
            "input_path": INPUT_PATH_NEEDS_CLARIFICATION,
            "output_type": "filtered_array",
            "transformation": "Sort by age descending",
            "return_value": "sorted users array",
        },
        request="Sort users by age descending",
        raw_context={"wf": {"vars": {"people": {"users": []}}, "initVariables": {"users": []}}},
        dialog_language="en",
    )

    decision = build_clarifier_decision(spec)
    assert decision["status"] == "question"
    assert decision["question"] == "What is the exact Lua path to the users data, for example `wf.vars.users`?"


def test_clarifier_blocks_repeated_question_without_new_information():
    spec = evaluate_spec(
        {
            "goal": "Sort users by age descending",
            "input_path": INPUT_PATH_NEEDS_CLARIFICATION,
            "output_type": "filtered_array",
            "transformation": "Sort by age descending",
            "return_value": "sorted users array",
        },
        request="Sort users by age descending",
        raw_context={"wf": {"vars": {"people": {"users": []}}, "initVariables": {"users": []}}},
        dialog_language="en",
    )

    decision = build_clarifier_decision(
        spec,
        clarification_history=[
            {
                "question": "What is the exact Lua path to the users data, for example `wf.vars.users`?",
                "answer": "Sort users by age descending",
            }
        ],
    )
    assert decision["status"] == "blocked"
    assert decision["question"] is None


def test_clarifier_accepts_input_path_answer_without_exact_path_when_context_resolves_it():
    spec = evaluate_spec(
        {
            "goal": "Sort users by age descending",
            "input_path": INPUT_PATH_NEEDS_CLARIFICATION,
            "output_type": "filtered_array",
            "transformation": "Sort by age descending",
            "return_value": "sorted users array",
        },
        request="Sort users by age descending",
        raw_context={"wf": {"vars": {"users": [{"age": 30}]}, "initVariables": {}}},
        dialog_language="en",
        clarification_history=[
            {
                "question": "What is the exact Lua path to the users data, for example `wf.vars.users`?",
                "answer": "use the users array",
                "target": "input_path",
            }
        ],
    )

    assert spec["input_path"] == "wf.vars.users"
    assert build_clarifier_decision(spec)["status"] == "approved"


def test_clarifier_does_not_ask_about_edge_cases_or_structure_details():
    spec = evaluate_spec(
        {
            "goal": "Implement a red-black tree node structure",
            "input_path": INPUT_PATH_NOT_APPLICABLE,
            "output_type": "new_structure",
            "transformation": "Create a Lua table for a red-black tree node",
            "return_value": "Lua table representing a red-black tree node",
        },
        request="Implement a red-black tree node structure",
        raw_context={"wf": {"vars": {}, "initVariables": {}}},
        dialog_language="en",
    )

    assert build_clarifier_decision(spec) == {"status": "approved", "question": None, "reason": None}


def test_clarifier_never_mentions_forbidden_topics():
    spec = evaluate_spec(
        {
            "goal": "Sort users by age descending",
            "input_path": INPUT_PATH_NEEDS_CLARIFICATION,
            "output_type": "filtered_array",
            "transformation": "Sort by age descending",
            "return_value": "sorted users array",
        },
        request="Sort users by age descending",
        raw_context={"wf": {"vars": {"people": {"users": []}}, "initVariables": {"users": []}}},
        dialog_language="en",
    )

    question = build_clarifier_decision(spec)["question"].lower()
    assert "nil" not in question
    assert "empty" not in question
    assert "invalid format" not in question
    assert "color" not in question
    assert "style" not in question
    assert "optimization" not in question
