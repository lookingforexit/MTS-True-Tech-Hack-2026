import json
import os
import re
import uuid
import pytest

from gen.api.llm.v1 import llm_pb2
from gen.api.lua_validator.v1 import validator_pb2

def load_testcases():
    testcases_path = os.path.join(os.path.dirname(__file__), 'testcases.json')
    if not os.path.exists(testcases_path): return[]
    with open(testcases_path, 'r', encoding='utf-8') as f:
        cases = json.load(f)
    return cases if isinstance(cases, list) else [cases]

class TestLocalScript:
    
    @pytest.mark.parametrize("case", load_testcases(), ids=lambda c: c.get("id", "unnamed"))
    def test_pipeline_execution(self, case, llm_stub, validator_stub):
        session_id = uuid.uuid4().hex
        
        prompt_text = case.get("prompt", "")
        context_data = case.get("context", {})
        context_str = json.dumps(context_data, ensure_ascii=False)
        
        pipeline_state = llm_pb2.PipelineState(
            session_id=session_id,
            request=prompt_text
        )
        if context_data:
            pipeline_state.context = context_str

        req = llm_pb2.SessionRequest(pipeline_state=pipeline_state)
        
        resp = llm_stub.StartOrContinue(req)
        current_state = resp.pipeline_state

        def exhaust_llm_loop(state):
            max_iters = 10
            while state.phase not in ["done", "error"] and max_iters > 0:
                if state.phase == "clarification_needed":
                    print(f"\n{'='*50}")
                    print(f"🤖 АГЕНТ ЗАДАЕТ ВОПРОС (Тест: {case.get('id')}):")
                    print(state.clarification_question)
                    print(f"{'='*50}")
                    
                    ans_text = input("👉 Введите ваш ответ: ")
                    
                    ans_req = llm_pb2.AnswerRequest(
                        session_id=session_id, 
                        answer=ans_text,
                        pipeline_state=state
                    )
                    resp = llm_stub.AnswerClarification(ans_req)
                    state = resp.pipeline_state
                else:
                    pytest.fail(f"Неожиданная фаза от сервера: {state.phase}")
                    
                max_iters -= 1
            
            assert max_iters > 0, "Таймаут генерации (зацикливание вопросов)"
            if state.phase == "error" and not state.code:
                pytest.fail(f"Пайплайн упал: {state.error}")
            assert state.code, "Сгенерированный код пуст!"
            return state

        current_state = exhaust_llm_loop(current_state)
        final_code = current_state.code

        # --- Validation ---
        env_vars_json = json.dumps({
            "CONTEXT_JSON": json.dumps(context_data, ensure_ascii=False)
        }, ensure_ascii=False)

        val_req = validator_pb2.ValidateRequest(code=final_code, timeout_ms=5000, env_vars=env_vars_json)
        val_resp = validator_stub.Validate(val_req)

        assert val_resp.success, f"Код упал!\nОшибка: {val_resp.error}\nВывод: {val_resp.output}\nКод:\n{final_code}"

        if "expected_value" in case:
            expected = case["expected_value"]
            match = re.search(r"___RESULT___=(.*)", val_resp.output)
            assert match, f"Скрипт не вернул результат. Вывод: {val_resp.output}"
            
            actual_json_str = match.group(1).strip()
            try:
                actual = json.loads(actual_json_str)
            except json.JSONDecodeError:
                pytest.fail(f"Ошибка парсинга ответа: {actual_json_str}")

            assert actual == expected, f"НЕВЕРНЫЙ РЕЗУЛЬТАТ!\nОжидалось: {expected}\nПолучено: {actual}\nКод:\n{final_code}"
