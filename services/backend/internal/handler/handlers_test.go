package handler

import "testing"

func TestWrapLuaTransport(t *testing.T) {
	raw := "return wf.vars.value"
	if got := wrapLuaTransport(raw); got != "lua{return wf.vars.value}lua" {
		t.Fatalf("unexpected wrapped code: %q", got)
	}

	alreadyWrapped := "lua{return 1}lua"
	if got := wrapLuaTransport(alreadyWrapped); got != alreadyWrapped {
		t.Fatalf("wrapper should not be duplicated: %q", got)
	}
}

func TestWrapTextTransport(t *testing.T) {
	raw := "Какое поле использовать для фильтрации?"
	if got := wrapTextTransport(raw); got != "text{Какое поле использовать для фильтрации?}text" {
		t.Fatalf("unexpected wrapped text: %q", got)
	}

	alreadyWrapped := "text{Which field should be used?}text"
	if got := wrapTextTransport(alreadyWrapped); got != alreadyWrapped {
		t.Fatalf("wrapper should not be duplicated: %q", got)
	}
}
