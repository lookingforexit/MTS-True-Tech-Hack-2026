# FROM python:3.11-slim

# WORKDIR /app

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# COPY tests/requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# COPY proto/ ./proto/
# COPY tests/ ./tests/

# RUN mkdir -p /app/tests/generated && \
#     touch /app/tests/generated/__init__.py && \
#     python -m grpc_tools.protoc -I=/app/proto \
#         --python_out=/app/tests/generated \
#         --grpc_python_out=/app/tests/generated \
#         /app/proto/api/llm/v1/llm.proto \
#         /app/proto/api/lua_validator/v1/validator.proto

# ENV PYTHONPATH=/app/tests/generated:/app/tests

# WORKDIR /app/tests

# CMD ["pytest", "-v", "test_local_script.py", "--html=reports/report.html", "--self-contained-html"]


FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Установка uv (копирование бинарного файла из официального образа)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Настройка uv для использования системного Python (без создания виртуального окружения)
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

# Копирование только файла с зависимостями для эффективного кэширования слоёв
COPY tests/requirements.txt ./tests/requirements.txt

# Установка Python-зависимостей через uv
RUN uv pip install --no-cache-dir -r tests/requirements.txt

# Копирование остальных исходных файлов
COPY proto/ ./proto/
COPY tests/ ./tests/

# Генерация gRPC/protobuf файлов
RUN mkdir -p /app/tests/generated && \
    touch /app/tests/generated/__init__.py && \
    python -m grpc_tools.protoc -I=/app/proto \
        --python_out=/app/tests/generated \
        --grpc_python_out=/app/tests/generated \
        /app/proto/api/llm/v1/llm.proto \
        /app/proto/api/lua_validator/v1/validator.proto

# Установка переменных окружения для импорта модулей
ENV PYTHONPATH=/app/tests/generated:/app/tests

WORKDIR /app/tests

# Команда по умолчанию — запуск pytest
CMD ["pytest", "-v", "test_local_script.py", "--html=reports/report.html", "--self-contained-html"]