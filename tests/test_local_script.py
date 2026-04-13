import json
import os
import re
import time
import uuid
import pytest

from generated.api.llm.v1 import llm_pb2
from generated.api.lua_validator.v1 import validator_pb2

def load_testcases():
    testcases_path = os.path.join(os.path.dirname(__file__), 'testcases.json')
    if not os.path.exists(testcases_path):
        return[]
    with open(testcases_path, 'r', encoding='utf-8') as f:
        cases = json.load(f)
    return cases if isinstance(cases, list) else [cases]


class TestLocalScript:
    
    @pytest.mark.parametrize("case", load_testcases(), ids=lambda c: c.get("id", "unnamed"))
    def test_code_generation_and_execution(self, case, llm_stub, validator_stub):
        session_id = uuid.uuid4().hex
        
        # --- ЭТАП 1: ГЕНЕРАЦИЯ КОДА (LLM) ---
        prompt_text = case.get("prompt", "")
        context_str = json.dumps(case.get("context", {}), ensure_ascii=False)
        clarifications = case.get("clarification_answers",[])
        answers_used = 0

        req = llm_pb2.SessionRequest(session_id=session_id, request=prompt_text, context=context_str)
        resp = llm_stub.StartOrContinue(req)

        max_iters = 15
        while resp.phase not in[llm_pb2.DONE, llm_pb2.ERROR] and max_iters > 0:
            if resp.phase == llm_pb2.CLARIFICATION_NEEDED:
                ans_text = clarifications[answers_used] if answers_used < len(clarifications) else "Пиши код без вопросов."
                resp = llm_stub.AnswerClarification(llm_pb2.AnswerRequest(session_id=session_id, answer=ans_text))
                answers_used += 1
            else:
                time.sleep(1)
                resp = llm_stub.GetSessionState(llm_pb2.GetStateRequest(session_id=session_id))
            max_iters -= 1

        assert max_iters > 0, "Таймаут генерации"
        if resp.phase == llm_pb2.ERROR and not resp.code:
            pytest.fail(f"Пайплайн упал без генерации кода. Ошибка: {resp.error}")
            
        assert resp.code, "Сгенерированный код пуст!"

        # --- ЭТАП 2: ЗАПУСК В ВАЛИДАТОРЕ И ПРОВЕРКА РЕЗУЛЬТАТА ---
        # Отправляем код и JSON контекста в lua-validator
        # Сервис сам создаст sandbox и настроит окружение
        # CONTEXT_JSON - специальная переменная окружения для Lua sandbox
        env_vars_json = json.dumps({
            "CONTEXT_JSON": json.dumps(case.get("context", {}), ensure_ascii=False)
        }, ensure_ascii=False)

        val_req = validator_pb2.ValidateRequest(
            code=resp.code,
            timeout_ms=5000,
            env_vars=env_vars_json
        )
        val_resp = validator_stub.Validate(val_req)

        # 3. Проверка на ошибки синтаксиса и падения во время выполнения (Runtime)
        assert val_resp.success, f"Код упал при выполнении!\nОшибка: {val_resp.error}\nВывод: {val_resp.output}\nСгенерированный код LLM:\n{resp.code}"

        # 4. Логическая проверка (Сравниваем с expected_value)
        if "expected_value" in case:
            expected = case["expected_value"]
            
            # Достаем результат, который напечатал Lua
            match = re.search(r"___RESULT___=(.*)", val_resp.output)
            assert match, f"Скрипт выполнился, но не вернул результат (нет return). Вывод: {val_resp.output}"
            
            actual_json_str = match.group(1).strip()
            
            try:
                actual = json.loads(actual_json_str)
            except json.JSONDecodeError:
                pytest.fail(f"Не удалось распарсить ответ Lua в Python: {actual_json_str}")

            # ФИНАЛЬНАЯ ПРОВЕРКА!
            assert actual == expected, f"НЕВЕРНЫЙ РЕЗУЛЬТАТ!\nОжидалось: {expected}\nПолучено: {actual}\n\nКод от LLM:\n{resp.code}"