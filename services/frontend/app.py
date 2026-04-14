import json
import os
import requests
import streamlit as st

from transport import parse_transport_content

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8080")

# --- Конфигурация страницы ---
st.set_page_config(
    page_title="Ocean Cucumber — AI для генерации Lua",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Кастомный CSS для улучшения визуала ---
st.markdown("""
    <style>
    /* Делаем шрифт в текстовом поле JSON моноширинным */
    .stTextArea textarea {
        font-family: 'Fira Code', 'Courier New', monospace !important;
        font-size: 13px !important;
    }
            
    /* Кнопка Deploy */
    [data-testid="stHeader"] button[kind="header"] {
        display: none !important;
    }
    
    /* 3. Скрываем надпись "Made with Streamlit" в подвале */
    footer {
        display: none !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- Инициализация состояния ---
if "messages" not in st.session_state:
    st.session_state.messages = [
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

# Состояния для умного сохранения JSON
default_json = '{\n  "wf": {\n    "vars": {}\n  }\n}'
if "saved_json" not in st.session_state:
    st.session_state.saved_json = default_json
if "context_data" not in st.session_state:
    st.session_state.context_data = {"wf": {"vars": {}}}
if "json_valid" not in st.session_state:
    st.session_state.json_valid = True


# ==========================================
# БОКОВАЯ ПАНЕЛЬ: Ввод JSON-контекста
# ==========================================
with st.sidebar:
    st.header("⚙️ Контекст (JSON)")
    st.caption("Укажите переменные, которые будут доступны модели:")
    
    # Текстовое поле всегда отображает текущий ввод пользователя
    current_input = st.text_area(
        "JSON", 
        value=st.session_state.saved_json, 
        height=350, 
        label_visibility="collapsed"
    )
    
    # Проверяем, изменил ли пользователь текст по сравнению с сохраненным
    is_changed = current_input != st.session_state.saved_json
    
    if is_changed:
        st.warning("⚠️ Внесены изменения. Сохраните их!")
        # Кнопка появляется только при изменениях
        if st.button("💾 Сохранить JSON", type="primary", use_container_width=True):
            try:
                # Пытаемся распарсить
                parsed = json.loads(current_input)
                # Если успешно - обновляем состояния
                st.session_state.context_data = parsed
                st.session_state.saved_json = current_input
                st.session_state.json_valid = True
                # Перезагружаем интерфейс, чтобы скрыть кнопку и показать Success
                st.rerun()
            except json.JSONDecodeError as e:
                st.session_state.json_valid = False
                st.error(f"❌ Ошибка JSON: {e}")
    else:
        # Если изменений нет, просто показываем статус
        if st.session_state.json_valid:
            st.success("✅ JSON валиден и сохранен")
        else:
            st.error("❌ В сохраненном JSON есть ошибки")


# ==========================================
# ФУНКЦИЯ ОТПРАВКИ НА БЭКЕНД
# ==========================================
def call_backend(prompt: str) -> dict:
    if st.session_state.pending_session_id:
        payload = {
            "session_id": st.session_state.pending_session_id,
            "clarification_answer": prompt,
        }
    else:
        payload = {"prompt": prompt}
        if st.session_state.json_valid and st.session_state.context_data:
            payload["context"] = st.session_state.context_data

    resp = requests.post(f"{BACKEND_URL}/generate", json=payload, timeout=900)
    resp.raise_for_status()
    return resp.json()

# ==========================================
# ОСНОВНОЙ ЧАТ
# ==========================================
st.title("🌊🥒 Ocean Cucumber")

if st.session_state.pending_session_id:
    st.info("💡 Агент задал уточняющий вопрос. Пожалуйста, ответьте на него ниже.", icon="⏳")

chat_disabled = is_changed or not st.session_state.json_valid
if is_changed:
    st.warning("Сначала сохраните JSON в боковой панели, затем отправьте сообщение.")
elif not st.session_state.json_valid:
    st.warning("Исправьте ошибку JSON в боковой панели, затем отправьте сообщение.")

for msg in st.session_state.messages:
    avatar = "🥒" if msg["role"] == "assistant" else "🧑‍💻"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

if prompt := st.chat_input(
    "Ответьте на уточнение..." if st.session_state.pending_session_id else "Опишите задачу...",
    disabled=chat_disabled,
):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍💻"): st.markdown(prompt)

    with st.chat_message("assistant", avatar="🥒"):
        try:
            with st.spinner("Ocean Cucumber думает..."):
                data = call_backend(prompt)
        except Exception as e:
            error_message = f"Ошибка: {e}"
            st.error(error_message)
            st.session_state.messages.append({"role": "assistant", "content": f"**{error_message}**"})
            st.stop()

        err = data.get("error")
        code_kind, code_content = parse_transport_content(data.get("code"))
        question_kind, question_content = parse_transport_content(data.get("question"))
        code_str = code_content.strip() if code_kind in ("lua", "plain") else ""
        question = question_content.strip() if question_kind in ("text", "plain") else ""
        session_id = data.get("session_id")

        ans_parts =[]
        if err:
            st.error(err)
            ans_parts.append(f"**Ошибка:** {err}")
            st.session_state.pending_session_id = None
        else:
            if code_str:
                st.code(code_str, language="lua")
                ans_parts.append(f"**Сгенерированный код:**\n```lua\n{code_str}\n```")
                st.session_state.pending_session_id = None

            if question:
                q = f"❓ **Уточнение:** {question}"
                st.markdown(q)
                ans_parts.append(q)
                st.session_state.pending_session_id = session_id

            if not code_str and not question and not err:
                fallback = "Пустой ответ от сервера. Попробуйте переформулировать задачу."
                st.markdown(fallback)

        st.session_state.messages.append({"role": "assistant", "content": "\n\n".join(ans_parts)})
