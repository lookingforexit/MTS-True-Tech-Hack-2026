import json
import os
import requests
import streamlit as st

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
    
    /* 2. Скрываем "бегающего человечка" (индикатор загрузки) */
    [data-testid="stStatusWidget"] {
        display: none !important;
    }
    
    /* 3. Скрываем надпись "Made with Streamlit" в подвале */
    footer {
        display: none !important;
    }
    
    /* 4. СКРЫВАЕМ ОКНО ОШИБКИ СОЕДИНЕНИЯ (Connection Error / Connecting) */
    [data-testid="stConnectionStatus"] {
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
    clarification_mode = st.session_state.get("clarification_mode", "answer")
    if st.session_state.pending_session_id and clarification_mode == "answer":
        payload = {
            "session_id": st.session_state.pending_session_id,
            "clarification_answer": prompt,
        }
    else:
        payload = {"prompt": prompt}
        if st.session_state.pending_session_id and clarification_mode == "new_request":
            payload["mode"] = "new_request"
        if st.session_state.json_valid and st.session_state.context_data:
            payload["context"] = st.session_state.context_data

    resp = requests.post(f"{BACKEND_URL}/generate", json=payload, timeout=900)
    resp.raise_for_status()
    return resp.json()

def unwrap_lua(raw: str) -> str:
    if raw and raw.startswith("lua{") and raw.endswith("}lua"):
        return raw[4:-4].strip()
    return raw.strip() if raw else ""

def unwrap_text(raw: str) -> str:
    if raw and raw.startswith("text{") and raw.endswith("}text"):
        return raw[5:-5].strip()
    return raw.strip() if raw else ""



# ==========================================
# ОСНОВНОЙ ЧАТ
# ==========================================
st.title("🌊🥒 Ocean Cucumber")

if st.session_state.pending_session_id:
    st.info("💡 Сейчас можно либо ответить на уточнение, либо отправить новую задачу и сбросить pending clarification.", icon="⏳")
    st.radio(
        "Режим отправки",
        options=["answer", "new_request"],
        format_func=lambda value: "Ответить на уточнение" if value == "answer" else "Новая задача",
        key="clarification_mode",
        horizontal=True,
    )
    if st.button("Сбросить уточнение", use_container_width=True):
        st.session_state.pending_session_id = None
        st.session_state.clarification_mode = "answer"
        st.rerun()

for msg in st.session_state.messages:
    avatar = "🥒" if msg["role"] == "assistant" else "🧑‍💻"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ответьте на уточнение или отправьте новую задачу..." if st.session_state.pending_session_id else "Опишите задачу..."):
    if is_changed:
        st.toast("Вы не сохранили JSON!", icon="⚠️")
        st.stop()
    if not st.session_state.json_valid:
        st.toast("Ошибка в JSON!", icon="❌")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍💻"): st.markdown(prompt)

    with st.chat_message("assistant", avatar="🥒"):
        try:
            with st.spinner("Ocean Cucumber думает..."):
                data = call_backend(prompt)
        except Exception as e:
            st.error(f"Ошибка: {e}")
            st.stop()

        err = data.get("error")
        code_str = unwrap_lua(data.get("code"))
        question = unwrap_text(data.get("question"))
        session_id = data.get("session_id")
        clarification_mode = st.session_state.get("clarification_mode", "answer")

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

        if clarification_mode == "new_request" and not question:
            st.session_state.pending_session_id = None
        st.session_state.clarification_mode = "answer"

        st.session_state.messages.append({"role": "assistant", "content": "\n\n".join(ans_parts)})
