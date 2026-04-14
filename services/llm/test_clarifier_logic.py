from spec_logic import (
    INPUT_PATH_NEEDS_CLARIFICATION,
    INPUT_PATH_NOT_APPLICABLE,
    build_clarifier_decision,
    evaluate_spec,
)


def test_clarifier_stays_silent_when_spec_is_complete():
    spec = evaluate_spec(
        {
            "goal": "Сгенерировать строку приветствия для пользователя",
            "input_path": "wf.vars.user",
            "output_type": "single_value",
            "transformation": "Собрать приветствие из полей user",
            "return_value": "строка приветствия формата 'Привет, [first_name] [last_name]! Твоя роль: [role].'",
        },
        request="Сгенерируй строку приветствия для пользователя, используя объект user",
        raw_context={"wf": {"vars": {"user": {"first_name": "Иван", "last_name": "Иванов", "role": "admin"}}}},
        dialog_language="ru",
    )

    decision = build_clarifier_decision(spec)
    assert decision == {"status": "approved", "question": None}


def test_clarifier_asks_only_about_return_value():
    spec = evaluate_spec(
        {
            "goal": "Реализовать бинарный поиск на отсортированном массиве",
            "input_path": INPUT_PATH_NOT_APPLICABLE,
            "output_type": "single_value",
            "transformation": "Найти элемент бинарным поиском",
            "return_value": "",
        },
        request="Напиши функцию поиска на отсортированном массиве",
        raw_context={"wf": {"vars": {}, "initVariables": {}}},
        dialog_language="ru",
    )

    decision = build_clarifier_decision(spec)
    assert decision["status"] == "question"
    assert decision["question"] == "Что должна возвращать функция поиска: индекс, сам элемент или `true/false`?"


def test_clarifier_asks_only_about_input_path():
    spec = evaluate_spec(
        {
            "goal": "Отсортировать пользователей по возрасту",
            "input_path": INPUT_PATH_NEEDS_CLARIFICATION,
            "output_type": "filtered_array",
            "transformation": "Отсортировать по age",
            "return_value": "массив пользователей, отсортированный по возрасту",
        },
        request="Отсортируй пользователей по возрасту",
        raw_context={"wf": {"vars": {}, "initVariables": {}}},
        dialog_language="ru",
    )

    decision = build_clarifier_decision(spec)
    assert decision["status"] == "question"
    assert decision["question"] == "Укажи точный путь к входным данным в контексте, например `wf.vars.users`."


def test_clarifier_does_not_ask_about_edge_cases_or_structure_details():
    spec = evaluate_spec(
        {
            "goal": "Реализовать структуру узла в красно-черном дереве",
            "input_path": INPUT_PATH_NOT_APPLICABLE,
            "output_type": "new_structure",
            "transformation": "Создать Lua-таблицу узла дерева",
            "return_value": "Lua-таблица, описывающая узел красно-черного дерева",
        },
        request="Реализуй структуру узла в красно-черном дереве",
        raw_context={"wf": {"vars": {}, "initVariables": {}}},
        dialog_language="ru",
    )

    decision = build_clarifier_decision(spec)
    assert decision == {"status": "approved", "question": None}


def test_clarifier_never_mentions_nil_empty_or_invalid_format():
    spec = evaluate_spec(
        {
            "goal": "Отсортировать массив пользователей по убыванию возраста",
            "input_path": "wf.vars.users",
            "output_type": "filtered_array",
            "transformation": "Отсортировать по age по убыванию",
            "return_value": "массив пользователей, отсортированный по убыванию возраста",
        },
        request="Отсортируй массив пользователей users по убыванию возраста",
        raw_context={"wf": {"vars": {"users": [{"age": 30}, {"age": 20}]}}},
        dialog_language="ru",
    )

    decision = build_clarifier_decision(spec)
    question = (decision["question"] or "").lower()
    assert "nil" not in question
    assert "пуст" not in question
    assert "формат" not in question
    assert "color" not in question
