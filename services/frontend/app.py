import json
import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8080")

# --- Конфигурация страницы ---
st.set_page_config(
    page_title="Ocean Cucumber — AI для генерации Lua",
    page_icon="🌊",
    layout="wide",  # Делаем шире, чтобы и чат, и боковая панель смотрелись хорошо
)

# --- Инициализация истории сообщений ---
if "messages" not in st.session_state:
    st.session_state.messages =[
        {
            "role": "assistant",
            "content": (
                "👋 Привет! Я **Ocean Cucumber** — твой помощник для написания Lua-скриптов.\n\n"
                "Опиши задачу, а переменные (`wf.vars`) укажи в боковой панели слева."
            ),
        }
    ]

if "pending_session_id" not in st.session_state:
    st.session_state.pending_session_id = None


# ==========================================
# БОКОВАЯ ПАНЕЛЬ: Ввод JSON-контекста
# ==========================================
with st.sidebar:
    st.header("⚙️ Контекст (JSON)")
    st.markdown("Укажите переменные, которые будут доступны модели:")
    
    default_json = '{\n  "wf": {\n    "vars": {}\n  }\n}'
    context_input = st.text_area("JSON", value=default_json, height=400, label_visibility="collapsed")
    
    context_data = None
    is_json_valid = False
    
    # Локальная проверка JSON на валидность
    if context_input.strip():
        try:
            context_data = json.loads(context_input)
            is_json_valid = True
            st.success("✅ JSON валиден")
        except json.JSONDecodeError as e:
            st.error(f"❌ Ошибка JSON: {e}")


# ==========================================
# ФУНКЦИЯ ОТПРАВКИ НА БЭКЕНД
# ==========================================
def call_backend(prompt: str) -> dict:
    """POST /generate: отправляет промпт и (если это начало сессии) контекст."""
    if st.session_state.pending_session_id:
        # Если мы отвечаем на уточняющий вопрос, шлем только session_id и ответ
        payload = {
            "session_id": st.session_state.pending_session_id,
            "clarification_answer": prompt,
        }
    else:
        # Если это новый запрос, шлем промпт и наш JSON из боковой панели
        payload = {"prompt": prompt}
        if is_json_valid and context_data:
            # requests автоматически конвертирует context_data в JSON,
            # а Go-бэкенд примет его в поле Context json.RawMessage
            payload["context"] = context_data

    resp = requests.post(
        f"{BACKEND_URL}/generate",
        json=payload,
        timeout=900,
    )
    resp.raise_for_status()
    return resp.json()


# ==========================================
# ОСНОВНОЙ ЧАТ
# ==========================================
st.title("🌊🥒 Ocean Cucumber")

# Отображение всех сообщений из истории
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Поле ввода для пользователя
if prompt := st.chat_input("Опишите задачу для Lua-скрипта..."):
    # Если JSON с ошибкой, не даем отправить новый запрос
    if not st.session_state.pending_session_id and not is_json_valid:
        st.error("Пожалуйста, исправьте ошибки в JSON слева перед отправкой запроса.")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Ocean Cucumber думает..."):
                data = call_backend(prompt)
        except requests.HTTPError as e:
            detail = str(e)
            if e.response is not None:
                try:
                    body = e.response.json()
                    detail = body.get("error", body.get("Error", detail))
                except Exception:
                    detail = e.response.text[:500] if e.response.text else detail
            st.error(f"Ошибка бэкенда ({BACKEND_URL}): {detail}")
            st.session_state.messages.append({"role": "assistant", "content": f"Ошибка HTTP: {detail}"})
            st.stop()
        except requests.RequestException as e:
            st.error(f"Не удалось связаться с бэкендом ({BACKEND_URL}): {e}")
            st.session_state.messages.append({"role": "assistant", "content": f"Ошибка сети: {e}"})
            st.stop()

        # Разбор ответа от бэкенда
        answer_parts =[]
        err = data.get("error")
        code_str = data.get("code") or ""
        question = data.get("question")
        session_id = data.get("session_id")

        if err and not code_str and not question:
            st.error(err)
            answer_parts.append(f"**Ошибка:** {err}")
            st.session_state.pending_session_id = None
        else:
            if err and (code_str or question):
                st.warning(err)

            if code_str:
                answer_parts.append("**Сгенерированный код:**")
                st.code(code_str, language="lua")
                # Для истории сохраняем код в markdown формате
                answer_parts.append(f"```lua\n{code_str}\n```")
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

        full_answer = "\n".join(answer_parts).strip()
        st.session_state.messages.append({"role": "assistant", "content": full_answer})