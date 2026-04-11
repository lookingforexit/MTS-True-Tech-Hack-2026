import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8080")

# Конфигурация страницы
st.set_page_config(
    page_title="Ocean Cucumber — AI для генерации Lua",
    page_icon="🌊🔞s",
    layout="centered",
)

st.title("🌊🥒🔞 Ocean Cucumber")

# --- Инициализация истории сообщений ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 Привет! Я **Ocean Cucumber** — твой помощник для написания Lua-скриптов.\n\n"
                "Опиши задачу (на русском или английском), и я сгенерирую готовый код в формате `lua{...}lua`."
            ),
        }
    ]

if "pending_session_id" not in st.session_state:
    st.session_state.pending_session_id = None


def call_backend(prompt: str) -> dict:
    """POST /generate: обычный запрос или ответ на уточнение (если ждём session_id)."""
    if st.session_state.pending_session_id:
        payload = {
            "session_id": st.session_state.pending_session_id,
            "clarification_answer": prompt,
        }
    else:
        payload = {"prompt": prompt}

    resp = requests.post(
        f"{BACKEND_URL}/generate",
        json=payload,
        timeout=900,
    )
    resp.raise_for_status()
    return resp.json()


# --- Отображение всех сообщений из истории ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Поле ввода для пользователя ---
if prompt := st.chat_input("Опишите задачу для Lua-скрипта..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Sea Cucumber думает..."):
                data = call_backend(prompt)
        except requests.HTTPError as e:
            detail = str(e)
            if e.response is not None:
                try:
                    body = e.response.json()
                    detail = body.get("error", body.get("Error", detail))
                except Exception:
                    if e.response.text:
                        detail = e.response.text[:500]
            st.error(f"Ошибка бэкенда ({BACKEND_URL}): {detail}")
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": f"Ошибка HTTP: {detail}",
                }
            )
            st.stop()
        except requests.RequestException as e:
            st.error(f"Не удалось связаться с бэкендом ({BACKEND_URL}): {e}")
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": f"Ошибка сети: {e}",
                }
            )
            st.stop()

        answer_parts = []
        err = data.get("error")
        code_str = data.get("code") or ""
        question = data.get("question")
        session_id = data.get("session_id")

        if err and not code_str and not question:
            st.error(err)
            answer_parts.append(err)
            st.session_state.pending_session_id = None
        else:
            if err and (code_str or question):
                st.warning(err)

            if code_str:
                answer_parts.append("**Сгенерированный код:**")
                st.code(code_str, language="lua")
                answer_parts.append(code_str)
                st.session_state.pending_session_id = None

            if question:
                q = f"\n\n❓ **Уточнение:** {question}"
                st.markdown(q)
                answer_parts.append(q)
                if session_id:
                    st.session_state.pending_session_id = session_id

            if not code_str and not question and not err:
                fallback = "Пустой ответ от сервера. Попробуйте переформулировать задачу."
                st.markdown(fallback)
                answer_parts.append(fallback)

        full_answer = "".join(answer_parts).strip()
        st.session_state.messages.append({"role": "assistant", "content": full_answer})
