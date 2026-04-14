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

    /* Стандартный индикатор выполнения Streamlit в правом верхнем углу */
    [data-testid="stStatusWidget"] {
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
if "pending_request" not in st.session_state:
    st.session_state.pending_request = None

# Состояния для автосохранения JSON
default_json = '{\n  "wf": {\n    "vars": {}\n  }\n}'
if "context_json" not in st.session_state:
    st.session_state.context_json = default_json
if "context_data" not in st.session_state:
    st.session_state.context_data = {"wf": {"vars": {}}}
if "json_valid" not in st.session_state:
    st.session_state.json_valid = True
if "json_error" not in st.session_state:
    st.session_state.json_error = ""


# ==========================================
# БОКОВАЯ ПАНЕЛЬ: Ввод JSON-контекста
# ==========================================
with st.sidebar:
    st.header("⚙️ Контекст (JSON)")
    st.caption("Укажите переменные, которые будут доступны модели:")
    
    current_input = st.text_area(
        "JSON", 
        height=350, 
        label_visibility="collapsed",
        key="context_json",
    )

    try:
        parsed = json.loads(current_input)
        if not isinstance(parsed, dict):
            raise ValueError("JSON должен быть объектом")
        st.session_state.context_data = parsed
        st.session_state.json_valid = True
        st.session_state.json_error = ""
    except (json.JSONDecodeError, ValueError) as e:
        st.session_state.json_valid = False
        st.session_state.json_error = str(e)

    if st.session_state.json_valid:
        st.success("✅ JSON валиден и сохранен")
    else:
        st.error(f"❌ Ошибка JSON: {st.session_state.json_error}")


# ==========================================
# ФУНКЦИЯ ОТПРАВКИ НА БЭКЕНД
# ==========================================
def build_payload(prompt: str) -> dict:
    if st.session_state.pending_session_id:
        return {
            "session_id": st.session_state.pending_session_id,
            "clarification_answer": prompt,
        }

    payload = {"prompt": prompt}
    if st.session_state.json_valid and st.session_state.context_data:
        payload["context"] = st.session_state.context_data
    return payload


def call_backend(payload: dict) -> dict:
    resp = requests.post(f"{BACKEND_URL}/generate", json=payload, timeout=900)
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        return {"error": f"Пустой ответ от backend: HTTP {resp.status_code}"}

    data["_http_status"] = resp.status_code
    return data

# ==========================================
# ОСНОВНОЙ ЧАТ
# ==========================================
st.title("🌊🥒 Ocean Cucumber")

if st.session_state.pending_session_id:
    st.info("💡 Агент задал уточняющий вопрос. Пожалуйста, ответьте на него ниже.", icon="⏳")

chat_disabled = not st.session_state.json_valid or st.session_state.pending_request is not None
if not st.session_state.json_valid:
    st.warning("Исправьте ошибку JSON в боковой панели, затем отправьте сообщение.")
if st.session_state.pending_request is not None:
    st.info("Запрос уже отправлен, дождитесь ответа.", icon="⏳")

for msg in st.session_state.messages:
    avatar = "🥒" if msg["role"] == "assistant" else "🧑‍💻"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

if prompt := st.chat_input(
    "Ответьте на уточнение..." if st.session_state.pending_session_id else "Опишите задачу...",
    disabled=chat_disabled,
):
    st.session_state.pending_request = {
        "prompt": prompt,
        "payload": build_payload(prompt),
        "inflight": False,
    }
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

if st.session_state.pending_request is not None:
    with st.chat_message("assistant", avatar="🥒"):
        if st.session_state.pending_request.get("inflight"):
            st.info("Запрос уже обрабатывается, дождитесь ответа.", icon="⏳")
            st.stop()

        st.session_state.pending_request["inflight"] = True
        try:
            with st.spinner("Ocean Cucumber думает..."):
                data = call_backend(st.session_state.pending_request["payload"])
        except Exception as e:
            error_message = f"Ошибка: {e}"
            st.error(error_message)
            st.session_state.messages.append({"role": "assistant", "content": f"**{error_message}**"})
            st.session_state.pending_request = None
            st.rerun()

        err = data.get("error")
        answer_kind, answer_content = parse_transport_content(data.get("answer"))
        code_kind, code_content = parse_transport_content(data.get("code"))
        question_kind, question_content = parse_transport_content(data.get("question"))
        answer = answer_content.strip() if answer_kind in ("text", "plain") else ""
        code_str = code_content.strip() if code_kind in ("lua", "plain") else ""
        question = question_content.strip() if question_kind in ("text", "plain") else ""
        session_id = data.get("session_id")
        http_status = data.get("_http_status")

        ans_parts = []
        if err:
            st.error(err)
            ans_parts.append(f"**Ошибка:** {err}")
            if data.get("validation_error"):
                st.caption(data["validation_error"])
                ans_parts.append(f"**Validation error:** {data['validation_error']}")
            if data.get("validation_output"):
                st.text(data["validation_output"])
                ans_parts.append(f"**Validation output:**\n```text\n{data['validation_output']}\n```")
            if http_status in (404, 422):
                st.session_state.pending_session_id = None
        else:
            if answer:
                st.markdown(answer)
                ans_parts.append(answer)
                st.session_state.pending_session_id = None

            if code_str:
                st.code(code_str, language="lua")
                ans_parts.append(f"**Сгенерированный код:**\n```lua\n{code_str}\n```")
                st.session_state.pending_session_id = None

            if question:
                q = f"❓ **Уточнение:** {question}"
                st.markdown(q)
                ans_parts.append(q)
                st.session_state.pending_session_id = session_id

            if not answer and not code_str and not question and not err:
                fallback = "Пустой ответ от сервера. Попробуйте переформулировать задачу."
                st.markdown(fallback)
                ans_parts.append(fallback)

        st.session_state.messages.append({"role": "assistant", "content": "\n\n".join(ans_parts)})
        st.session_state.pending_request = None
        st.rerun()
