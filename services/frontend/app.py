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
    /* Слегка стилизуем кнопку очистки */
    .btn-clear {
        margin-top: 20px;
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

# Визуальная подсказка, если ждем ответа на вопрос
if st.session_state.pending_session_id:
    st.info("💡 Агент задал уточняющий вопрос. Пожалуйста, ответьте на него ниже.", icon="⏳")

# Отображение всех сообщений из истории с кастомными аватарками
for msg in st.session_state.messages:
    avatar = "🥒" if msg["role"] == "assistant" else "🧑‍💻"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# Динамический плейсхолдер для поля ввода
input_placeholder = "Ответьте на уточнение..." if st.session_state.pending_session_id else "Опишите задачу для Lua-скрипта..."

# Поле ввода для пользователя
if prompt := st.chat_input(input_placeholder):
    
    # Валидации перед отправкой
    if is_changed:
        st.toast("Вы не сохранили JSON!", icon="⚠️")
        st.error("Пожалуйста, нажмите «Сохранить JSON» в боковой панели перед отправкой запроса.")
        st.stop()
        
    if not st.session_state.json_valid:
        st.toast("Ошибка в JSON!", icon="❌")
        st.error("В JSON есть ошибки. Исправьте их перед отправкой запроса.")
        st.stop()

    # Добавляем сообщение пользователя
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    # Обрабатываем ответ
    with st.chat_message("assistant", avatar="🥒"):
        try:
            with st.spinner("Ocean Cucumber думает..."):
                data = call_backend(prompt=prompt)
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
            st.error(f"Неизвестная ошибка при запросе к бэкенду: {e}")
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