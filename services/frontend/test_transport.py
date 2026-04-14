from transport import parse_transport_content


def test_parse_lua_transport_content():
    kind, content = parse_transport_content("lua{return wf.vars.value}lua")
    assert kind == "lua"
    assert content == "return wf.vars.value"


def test_parse_text_transport_content():
    kind, content = parse_transport_content("text{Какое поле использовать?}text")
    assert kind == "text"
    assert content == "Какое поле использовать?"


def test_parse_plain_transport_content_is_backward_compatible():
    kind, content = parse_transport_content("plain text response")
    assert kind == "plain"
    assert content == "plain text response"
