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
    def test_pipeline_execution(self, case, llm_stub, validator_stub):
        session_id = uuid.uuid4().hex
        
        prompt_text = case.get("prompt", "")
        context_data = case.get("context", {})
        context_str = json.dumps(context_data, ensure_ascii=False)
        
        refinements = case.get("refinements",[])
        refinements_used = 0

        req = llm_pb2.SessionRequest(session_id=session_id, request=prompt_text, context=context_str)
        resp = llm_stub.StartOrContinue(req)

        def exhaust_llm_loop(current_resp):
            max_iters = 15
            while current_resp.phase not in[llm_pb2.DONE, llm_pb2.ERROR] and max_iters > 0:
                if current_resp.phase == llm_pb2.CLARIFICATION_NEEDED:
                    print(f"\n\n{'='*50}")
                    print(f"🤖 АГЕНТ ЗАДАЕТ ВОПРОС (Тест: {case.get('id')}):")
                    print(current_resp.clarification_question)
                    print(f"{'='*50}")
                    
                    ans_text = input("👉 Введите ваш ответ: ")
                    
                    current_resp = llm_stub.AnswerClarification(
                        llm_pb2.AnswerRequest(session_id=session_id, answer=ans_text)
                    )
                else:
                    time.sleep(1)
                    current_resp = llm_stub.GetSessionState(llm_pb2.GetStateRequest(session_id=session_id))
                max_iters -= 1
            
            assert max_iters > 0, "Таймаут генерации (зацикливание)"
            if current_resp.phase == llm_pb2.ERROR and not current_resp.code:
                pytest.fail(f"Пайплайн упал: {current_resp.error}")
            assert current_resp.code, "Сгенерированный код пуст!"
            return current_resp

        resp = exhaust_llm_loop(resp)

        while refinements_used < len(refinements):
            refine_prompt = refinements[refinements_used]
            refine_req = llm_pb2.SessionRequest(session_id=session_id, request=refine_prompt)
            resp = llm_stub.StartOrContinue(refine_req)
            resp = exhaust_llm_loop(resp)
            refinements_used += 1

        final_code = resp.code

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