import json
import os
import time
import uuid
import re
import pytest

from generated.api.llm.v1 import llm_pb2
from generated.api.lua_validator.v1 import validator_pb2

# ==========================================
# 1. ЗАГРУЗКА И ПОДГОТОВКА ДАННЫХ
# ==========================================

def load_testcases():
    testcases_path = os.path.join(os.path.dirname(__file__), 'testcases.json')
    if not os.path.exists(testcases_path):
        return[]
    with open(testcases_path, 'r', encoding='utf-8') as f:
        cases = json.load(f)
    return cases if isinstance(cases, list) else [cases]

def to_lua_table(obj):
    """Рекурсивно переводит Python dict/list в строку Lua-таблицы."""
    if isinstance(obj, dict):
        items = [f"[{json.dumps(str(k))}] = {to_lua_table(v)}" for k, v in obj.items()]
        return "{" + ", ".join(items) + "}"
    elif isinstance(obj, list):
        return "{" + ", ".join(to_lua_table(v) for v in obj) + "}"
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif obj is None:
        return "nil"
    return json.dumps(obj)

# ==========================================
# 2. ИЗОЛИРОВАННАЯ LUA-ПЕСОЧНИЦА (ГЕНЕРАТОР)
# ==========================================

def build_lua_sandbox(context_data: dict, generated_code: str) -> str:
    """
    Создает обертку для выполнения Lua-кода. 
    Вся "грязная" логика (моки, сериализация) спрятана здесь.
    """
    # Подготавливаем контекст (переменные wf)
    wf_lua_table = to_lua_table(context_data.get("wf", {"vars": {}, "initVariables": {}}))
    
    # Очищаем маркеры Markdown от LLM
    clean_code = re.sub(r"^(?:```lua|lua\{)\n?|\n?(?:```|\}lua)$", "", generated_code, flags=re.IGNORECASE).strip()

    return f"""
-- 1. МОКИРУЕМ СРЕДУ (wf и _utils)
wf = {wf_lua_table}
wf.get = function(self, key) 
    return (self.vars and self.vars[key]) or (self.initVariables and self.initVariables[key]) 
end
package.loaded.wf = wf

_utils = {{
    array = {{ new = function() return {{}} end, markAsArray = function(arr) return arr end }}
}}

-- 2. СЕРИАЛИЗАТОР (Чтобы Python понял ответ)
local function to_json(v)
    local t = type(v)
    if t == "nil" then return "null"
    elseif t == "boolean" or t == "number" then return tostring(v)
    elseif t == "string" then return string.format("%q", v):gsub("\\\n", "\\n")
    elseif t == "table" then
        local is_arr, max = true, 0
        for k, _ in pairs(v) do
            if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then is_arr = false break end
            if k > max then max = k end
        end
        local res = {{}}
        if is_arr then
            for i=1, max do table.insert(res, to_json(v[i])) end
            return "[" .. table.concat(res, ",") .. "]"
        else
            for k, val in pairs(v) do table.insert(res, to_json(tostring(k))..":"..to_json(val)) end
            return "{{" .. table.concat(res, ",") .. "}}"
        end
    end
    return '"' .. tostring(v) .. '"'
end

-- 3. ВЫПОЛНЯЕМ КОД МОДЕЛИ И ПЕРЕХВАТЫВАЕМ РЕЗУЛЬТАТ
local function run_llm_code()
{clean_code}
end

local success, result = pcall(run_llm_code)
if not success then
    print("RUNTIME_ERROR: " .. tostring(result))
    os.exit(1)
end

-- Выводим результат в консоль (stdout) с секретным маркером
print("___RESULT___=" .. to_json(result))
"""


# ==========================================
# 3. ОСНОВНОЙ КЛАСС ТЕСТИРОВАНИЯ
# ==========================================

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
        # 1. Заворачиваем код в нашу "песочницу"
        sandbox_script = build_lua_sandbox(case.get("context", {}), resp.code)

        # 2. Отправляем в контейнер lua-validator
        val_req = validator_pb2.ValidateRequest(code=sandbox_script, timeout_ms=5000)
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