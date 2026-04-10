import streamlit as st
import time

# Конфигурация страницы
st.set_page_config(
    page_title="Ocean Cucumber — AI для генерации Lua",
    page_icon="🌊",
    layout="centered"
)

st.title("🌊🥒 Ocean Cucumber")

# --- Инициализация истории сообщений ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 Привет! Я **Ocean Cucumber** — твой помощник для написания Lua-скриптов.\n\n"
                "Опиши задачу (на русском или английском), и я сгенерирую готовый код в формате `lua{...}lua`."
            )
        }
    ]

# --- Функция-заглушка вместо реального вызова бэкенда ---
def mock_generate(prompt: str) -> dict:
    """
    Имитирует ответ агента.
    Возвращает словарь с полями:
        - code: строка с Lua-кодом (может быть пустой)
        - question: уточняющий вопрос (если есть)
    """
    time.sleep(1.5)  # Имитация задержки генерации

    lower_prompt = prompt.lower()

    if "email" in lower_prompt or "последний" in lower_prompt:
        return {
            "code": '{"lastEmail": "lua{return wf.vars.emails[#wf.vars.emails]}lua"}',
            "question": None
        }
    elif "факториал" in lower_prompt or "factorial" in lower_prompt:
        return {
            "code": '{"factorial": "lua{function factorial(n) if n<=1 then return 1 else return n*factorial(n-1) end end return factorial(5)}lua"}',
            "question": None
        }
    elif "время" in lower_prompt or "time" in lower_prompt:
        return {
            "code": "",
            "question": "В каком формате приходят исходные данные времени? (например, Unix timestamp или строка 'YYYYMMDD')"
        }
    else:
        # Заглушка по умолчанию
        return {
            "code": '{"result": "lua{-- Вставьте ваш код здесь\nreturn wf.vars.someValue}lua"}',
            "question": "Это базовая заглушка. Уточните, какие данные нужно обработать и откуда их брать (wf.vars или wf.initVariables)?"
        }

# --- Отображение всех сообщений из истории ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Поле ввода для пользователя ---
if prompt := st.chat_input("Опишите задачу для Lua-скрипта..."):
    # Добавляем сообщение пользователя в историю и отображаем
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Генерация ответа ассистента
    with st.chat_message("assistant"):
        with st.spinner("Sea Cucumber думает..."):
            response_data = mock_generate(prompt)

        answer_parts = []

        if response_data.get("code"):
            code_str = response_data["code"]
            answer_parts.append("**Сгенерированный код:**")
            # Показываем код в красивом блоке с подсветкой JSON
            st.code(code_str, language="json")
            answer_parts.append(code_str)

        if response_data.get("question"):
            q = f"\n\n❓ **Уточнение:** {response_data['question']}"
            st.markdown(q)
            answer_parts.append(q)

        if not response_data.get("code") and not response_data.get("question"):
            fallback = "Не удалось сгенерировать код. Попробуйте переформулировать задачу."
            st.markdown(fallback)
            answer_parts.append(fallback)

        # Сохраняем полный текст ответа в историю
        full_answer = "".join(answer_parts).strip()
        st.session_state.messages.append({"role": "assistant", "content": full_answer})
