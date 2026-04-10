import json
from pathlib import Path
import pytest

def load_test_cases():
    cases = []
    testcases_dir = Path(__file__).parent / "testcases"
    for file_path in sorted(testcases_dir.glob("*.json")):
        with open(file_path, "r", encoding="utf-8") as f:
            case = json.load(f)
            case["_file"] = file_path.name
            cases.append(case)
    return cases

def pytest_generate_tests(metafunc):
    """Динамически создаёт параметризованные тесты для каждой функции с именем test_*_case."""
    if "case" in metafunc.fixturenames:
        cases = load_test_cases()
        ids = [f"{c.get('id', c['_file'])}: {c.get('description', '')}" for c in cases]
        metafunc.parametrize("case", cases, ids=ids)

def normalize_result(result):
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, (int, float)):
        return result
    if isinstance(result, list):
        return [normalize_result(v) for v in result]
    if isinstance(result, dict):
        return {k: normalize_result(v) for k, v in result.items()}
    return result

class TestLocalScript:
    def test_generated_code_matches_reference(self, agent_client, validator_client, case):
        # 1. Генерация
        code = agent_client.generate(case["prompt"])
        assert code, "Agent returned empty code"

        # 2. Определяем эталонный результат
        ref = case["reference"]
        if ref["type"] == "value":
            expected = ref["value"]
        elif ref["type"] == "code":
            ref_exec = validator_client.execute(ref["value"], case["context"])
            assert "error" not in ref_exec, f"Reference code execution failed: {ref_exec.get('error')}"
            expected = ref_exec.get("result")
        else:
            pytest.fail(f"Unknown reference type: {ref['type']}")

        # 3. Выполняем сгенерированный код
        gen_exec = validator_client.execute(code, case["context"])
        assert "error" not in gen_exec, f"Generated code execution failed: {gen_exec.get('error')}"
        got = gen_exec.get("result")

        # 4. Сравнение с нормализацией
        assert normalize_result(got) == normalize_result(expected), \
            f"Result mismatch.\nExpected: {expected}\nGot: {got}"