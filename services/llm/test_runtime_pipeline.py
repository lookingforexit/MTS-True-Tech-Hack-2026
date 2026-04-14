import json
import sys
import types


langchain_ollama = types.ModuleType("langchain_ollama")


class _BootstrapChatOllama:
    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, _messages):
        raise AssertionError("bootstrap model should be monkeypatched in tests")


langchain_ollama.ChatOllama = _BootstrapChatOllama
sys.modules.setdefault("langchain_ollama", langchain_ollama)

langchain_core = types.ModuleType("langchain_core")
langchain_core_messages = types.ModuleType("langchain_core.messages")


class _Message:
    def __init__(self, content: str):
        self.content = content


langchain_core_messages.HumanMessage = _Message
langchain_core_messages.SystemMessage = _Message
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.messages", langchain_core_messages)

langgraph_graph = types.ModuleType("langgraph.graph")
langgraph_graph.START = "start"


class _FakeStateGraph:
    def __init__(self, *_args, **_kwargs):
        pass

    def add_node(self, *_args, **_kwargs):
        return None

    def add_edge(self, *_args, **_kwargs):
        return None

    def add_conditional_edges(self, *_args, **_kwargs):
        return None

    def compile(self):
        class _Compiled:
            def invoke(self, state):
                return state

        return _Compiled()


langgraph_graph.StateGraph = _FakeStateGraph
sys.modules.setdefault("langgraph.graph", langgraph_graph)

checker_client = types.ModuleType("checker_client")


class _FakeCheckerClient:
    def __init__(self, *args, **kwargs):
        pass


checker_client.LuaCheckerClient = _FakeCheckerClient
sys.modules.setdefault("checker_client", checker_client)

validator_client = types.ModuleType("validator_client")


class _FakeValidatorClient:
    def __init__(self, *args, **kwargs):
        pass


validator_client.LuaValidatorClient = _FakeValidatorClient
sys.modules.setdefault("validator_client", validator_client)

import graph


class _DummyResponse:
    def __init__(self, content: str):
        self.content = content


class _DummyLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _messages):
        return _DummyResponse(self._content)


def test_invalid_spec_json_fallback_never_approves_generation(monkeypatch):
    monkeypatch.setattr(graph, "_llm_zero", _DummyLLM("not json at all"))

    state = {
        "request": "Write a binary search function",
        "raw_context": {"wf": {"vars": {}, "initVariables": {}}},
        "dialog_language": "en",
        "clarification_history": [],
    }
    spec_state = graph.spec_node(state)
    clarified = graph.clarifier_node({**state, **spec_state})

    parsed_spec = json.loads(spec_state["spec_json"])
    assert parsed_spec["spec_parse_failed"] is True
    assert clarified["spec_approved"] is False
    assert clarified["clarification_question"] == "What exactly should the final Lua code do?"


def test_repeat_clarification_becomes_controlled_error():
    state = {
        "request": "Sort users by age descending",
        "raw_context": {"wf": {"vars": {}, "initVariables": {}}},
        "dialog_language": "en",
        "clarification_history": [
            {
                "question": "What is the exact Lua path to the users data, for example `wf.vars.users`?",
                "answer": "Sort users by age descending",
            }
        ],
        "spec_json": json.dumps(
            {
                "goal": "Sort users by age descending",
                "input_path": "__INPUT_PATH_NEEDS_CLARIFICATION__",
                "output_type": "filtered_array",
                "transformation": "Sort by age descending",
                "return_value": "sorted users array",
                "spec_parse_failed": False,
                "clarification_required": True,
                "clarification_target": "input_path",
                "clarification_question": "What is the exact Lua path to the users data, for example `wf.vars.users`?",
                "need_clarification": True,
                "clarification_reason": "input_path is required but still unresolved",
            }
        ),
    }

    result = graph.clarifier_node(state)
    assert result["phase"] == "error"
    assert "same question was already asked" in result["error"]
