import json

from spec_logic import (
    INPUT_PATH_NEEDS_CLARIFICATION,
    INPUT_PATH_NOT_APPLICABLE,
    evaluate_spec,
)


def _context(payload):
    return {"wf": payload}


def test_spec_resolves_greeting_without_clarification():
    spec = evaluate_spec(
        {
            "goal": "Сгенерировать строку приветствия для пользователя",
            "input_path": "user",
            "output_type": "single_value",
            "transformation": "Собрать строку из first_name, last_name и role",
            "return_value": "строка приветствия формата 'Привет, [first_name] [last_name]! Твоя роль: [role].'",
        },
        request="Сгенерируй строку приветствия для пользователя, используя объект user",
        raw_context=_context(
            {
                "vars": {
                    "user": {
                        "first_name": "Иван",
                        "last_name": "Иванов",
                        "role": "admin",
                    }
                }
            }
        ),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is False
    assert spec["input_path"] == "wf.vars.user"
    assert spec["return_value"] == "строка приветствия формата 'Привет, [first_name] [last_name]! Твоя роль: [role].'"


def test_spec_resolves_users_sort_without_edge_case_questions():
    spec = evaluate_spec(
        {
            "goal": "Отсортировать массив пользователей по убыванию возраста",
            "input_path": "users",
            "output_type": "filtered_array",
            "transformation": "Отсортировать по age по убыванию",
            "return_value": "массив пользователей, отсортированный по убыванию возраста",
        },
        request="Отсортируй массив пользователей users по убыванию возраста",
        raw_context=_context({"vars": {"users": [{"age": 30}, {"age": 20}]}}),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is False
    assert spec["input_path"] == "wf.vars.users"
    assert "nil" not in json.dumps(spec, ensure_ascii=False).lower()


def test_spec_marks_input_path_not_applicable_for_fibonacci():
    spec = evaluate_spec(
        {
            "goal": "Вычислить 10-е число Фибоначчи",
            "input_path": "",
            "output_type": "single_value",
            "transformation": "Вычислить число Фибоначчи по индексу 10",
            "return_value": "10-е число Фибоначчи",
        },
        request="Напиши функцию и верни 10-е число Фибоначчи",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is False
    assert spec["input_path"] == INPUT_PATH_NOT_APPLICABLE
    assert spec["return_value"] == "10-е число Фибоначчи"


def test_spec_prioritizes_return_value_over_input_path():
    spec = evaluate_spec(
        {
            "goal": "Реализовать бинарный поиск на отсортированном массиве",
            "input_path": "",
            "output_type": "single_value",
            "transformation": "Найти элемент бинарным поиском",
            "return_value": "",
        },
        request="Напиши функцию поиска на отсортированном массиве",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is True
    assert spec["clarification_target"] == "return_value"
    assert spec["input_path"] == INPUT_PATH_NOT_APPLICABLE


def test_spec_requires_input_path_only_when_path_is_missing():
    spec = evaluate_spec(
        {
            "goal": "Отсортировать пользователей по возрасту",
            "input_path": INPUT_PATH_NEEDS_CLARIFICATION,
            "output_type": "filtered_array",
            "transformation": "Отсортировать по age",
            "return_value": "массив пользователей, отсортированный по возрасту",
        },
        request="Отсортируй пользователей по возрасту",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is True
    assert spec["clarification_target"] == "input_path"
    assert spec["input_path"] == INPUT_PATH_NEEDS_CLARIFICATION


def test_spec_does_not_ask_about_red_black_tree_node_details():
    spec = evaluate_spec(
        {
            "goal": "Реализовать структуру узла в красно-черном дереве",
            "input_path": INPUT_PATH_NOT_APPLICABLE,
            "output_type": "new_structure",
            "transformation": "Создать Lua-таблицу узла дерева",
            "return_value": "Lua-таблица, описывающая узел красно-черного дерева",
        },
        request="Реализуй структуру узла в красно-черном дереве",
        raw_context=_context({"vars": {}, "initVariables": {}}),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is False
    assert spec["input_path"] == INPUT_PATH_NOT_APPLICABLE
    serialized = json.dumps(spec, ensure_ascii=False).lower()
    assert "left" not in serialized
    assert "right" not in serialized
    assert "parent" not in serialized


def test_spec_resolves_recall_time_path():
    spec = evaluate_spec(
        {
            "goal": "Конвертировать время в unix timestamp",
            "input_path": "recallTime",
            "output_type": "single_value",
            "transformation": "Преобразовать строку времени в unix timestamp",
            "return_value": "unix timestamp, полученный из строки времени",
        },
        request="Конвертируй время в переменной recallTime в unix-формат",
        raw_context=_context({"initVariables": {"recallTime": "2024-10-01T10:00:00Z"}, "vars": {}}),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is False
    assert spec["input_path"] == "wf.initVariables.recallTime"
    assert spec["return_value"] == "unix timestamp, полученный из строки времени"


def test_spec_does_not_ask_for_obvious_greeting_fields():
    spec = evaluate_spec(
        {
            "goal": "Сгенерировать строку приветствия для пользователя",
            "input_path": "wf.vars.user",
            "output_type": "single_value",
            "transformation": "Собрать приветствие из данных пользователя",
            "return_value": "строка приветствия формата 'Привет, [first_name] [last_name]! Твоя роль: [role].'",
        },
        request="Сгенерируй строку приветствия для пользователя, используя объект user",
        raw_context=_context(
            {
                "vars": {
                    "user": {
                        "first_name": "Иван",
                        "last_name": "Иванов",
                        "role": "admin",
                    }
                },
                "initVariables": {},
            }
        ),
        dialog_language="ru",
    )

    assert spec["clarification_required"] is False
    assert spec["clarification_question"] is None

