import json
import os

import requests
import streamlit as st

# BACKEND_URL: support both Docker internal and local dev.
# In Docker Compose the service is reachable as "http://backend:8080".
# Locally the user should set BACKEND_URL=http://localhost:8080.
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8080")

# --- Конфигурация страницы ---
st.set_page_config(
    page_title="Ocean Cucumber — AI для генерации Lua",
    page_icon="🌊",
    layout="wide",
)

# --- Инициализация истории сообщений ---
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


# ==========================================
# БОКОВАЯ ПАНЕЛЬ: Ввод JSON-контекста
# ==========================================
with st.sidebar:
    st.header("⚙️ Контекст (JSON)")
    st.markdown("Укажите переменные, которые будут доступны модели.\n"
                "Можно оставить пустым — контекст необязателен.")

    default_json = '{\n  "wf": {\n    "vars": {}\n  }\n}'
    context_input = st.text_area(
        "JSON",
        value=default_json,
        height=400,
        label_visibility="collapsed",
    )

    # Determine context state:
    #   - stripped empty → no context sent (None)
    #   - valid JSON (including {}) → sent as-is
    #   - invalid JSON → error shown, but request still allowed if user proceeds
    context_data = None
    context_raw_sent = False  # True when we actually include context in payload
    is_json_valid = True
    json_error_msg = ""

    stripped = context_input.strip()
    if stripped == "":
        # Empty field — no context sent. This is fine.
        is_json_valid = True
        context_raw_sent = False
    else:
        try:
            context_data = json.loads(stripped)
            context_raw_sent = True
            is_json_valid = True
            st.success("✅ JSON валиден")
        except json.JSONDecodeError as e:
            json_error_msg = str(e)
            is_json_valid = False
            st.error(f"❌ Ошибка JSON: {e}")
            st.info("Запрос будет отправлен без контекста. Исправьте JSON, чтобы добавить контекст.")


# ==========================================
# ФУНКЦИЯ ОТПРАВКИ НА БЭКЕНД
# ==========================================
def call_backend(prompt: str, include_context: bool, ctx: dict | None) -> dict:
    """POST /generate: отправляет промпт и опционально контекст."""
    if st.session_state.pending_session_id:
        # Отвечаем на уточняющий вопрос — только session_id + ответ
        payload = {
            "session_id": st.session_state.pending_session_id,
            "clarification_answer": prompt,
        }
    else:
        # Новый запрос — prompt + optional context
        payload = {"prompt": prompt}
        if include_context and ctx is not None:
            payload["context"] = ctx

    resp = requests.post(
        f"{BACKEND_URL}/generate",
        json=payload,
        timeout=900,
    )
    resp.raise_for_status()
    return resp.json()


def check_backend_health() -> bool:
    """Quick health check against the backend."""
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


# ==========================================
# ОСНОВНОЙ ЧАТ
# ==========================================
st.title("🌊🥒 Ocean Cucumber")

# Backend connectivity indicator
if not check_backend_health():
    st.warning(
        f"⚠️ Бэкенд недоступен по адресу **{BACKEND_URL}**.\n\n"
        f"Убедитесь, что сервис backend запущен.\n"
        f"Для локального запуска: `BACKEND_URL=http://localhost:8080 streamlit run app.py`"
    )

# Отображение всех сообщений из истории
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Поле ввода для пользователя
if prompt := st.chat_input("Опишите задачу для Lua-скрипта..."):
    # If context JSON is invalid, we still allow the request (without context).
    # Show a warning but don't block.
    if not st.session_state.pending_session_id and not is_json_valid:
        st.warning(f"Контекст не будет отправлен из-за ошибки JSON: {json_error_msg}")

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Ocean Cucumber думает..."):
                data = call_backend(
                    prompt=prompt,
                    include_context=context_raw_sent,
                    ctx=context_data,
                )
        except requests.HTTPError as e:
            detail = str(e)
            if e.response is not None:
                try:
                    body = e.response.json()
                    detail = body.get("error", body.get("Error", detail))
                except Exception:
                    detail = e.response.text[:500] if e.response.text else detail
            st.error(f"Ошибка бэкенда ({BACKEND_URL}): {detail}")
            st.session_state.messages.append(
                {"role": "assistant", "content": f"❌ **Ошибка HTTP:** {detail}"}
            )
            st.stop()
        except requests.ConnectionError as e:
            st.error(
                f"Не удалось подключиться к бэкенду ({BACKEND_URL}).\n\n"
                f"Проверьте, что backend запущен и адрес верный.\n"
                f"Детали: {e}"
            )
            st.session_state.messages.append(
                {"role": "assistant", "content": f"❌ **Ошибка подключения:** не удалось связаться с {BACKEND_URL}"}
            )
            st.stop()
        except requests.Timeout as e:
            st.error(
                f"Превышено время ожидания ответа от бэкенда ({BACKEND_URL}).\n"
                f"Генерация может занимать до 15 минут. Попробуйте позже."
            )
            st.session_state.messages.append(
                {"role": "assistant", "content": "❌ **Таймаут:** бэкенд не ответил вовремя. Попробуйте снова."}
            )
            st.stop()
        except requests.RequestException as e:
            st.error(f"Неизвестная ошибка при запросе к бэкенду: {e}")
            st.session_state.messages.append(
                {"role": "assistant", "content": f"❌ **Ошибка сети:** {e}"}
            )
            st.stop()

        # Разбор ответа от бэкенда
        err = data.get("error")
        code_str = data.get("code") or ""
        question = data.get("question")
        session_id = data.get("session_id")

        if err and not code_str and not question:
            # Pure error — nothing to show
            st.error(err)
            st.session_state.messages.append(
                {"role": "assistant", "content": f"❌ **Ошибка:** {err}"}
            )
            st.session_state.pending_session_id = None
        else:
            if err and (code_str or question):
                # Warning alongside useful content
                st.warning(err)

            if code_str:
                st.code(code_str, language="lua")
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"**Сгенерированный код:**\n\n```lua\n{code_str}\n```"}
                )
                st.session_state.pending_session_id = None

            if question:
                st.markdown(f"❓ **Уточнение:** {question}")
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"❓ **Уточнение:** {question}"}
                )
                if session_id:
                    st.session_state.pending_session_id = session_id

            if not code_str and not question and not err:
                fallback = "Пустой ответ от сервера. Попробуйте переформулировать задачу."
                st.markdown(fallback)
                st.session_state.messages.append(
                    {"role": "assistant", "content": fallback}
                )
