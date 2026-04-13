.PHONY: generate-python

PROTO_ROOT := ../../proto
PY_OUT := gen
PY_PACKAGES := \
	$(PY_OUT) \
	$(PY_OUT)/api \
	$(PY_OUT)/api/llm \
	$(PY_OUT)/api/llm/v1 \
	$(PY_OUT)/api/lua_validator \
	$(PY_OUT)/api/lua_validator/v1

# Run from services/tests after installing:
#   grpcio-tools
# This reads the shared proto tree and writes only to services/tests/gen.
generate-python:
	mkdir -p $(PY_PACKAGES)
	touch $(addsuffix /__init__.py,$(PY_PACKAGES))
	python3 -m grpc_tools.protoc \
		-I $(PROTO_ROOT) \
		--python_out=$(PY_OUT) --grpc_python_out=$(PY_OUT) \
		$(PROTO_ROOT)/api/llm/v1/llm.proto \
		$(PROTO_ROOT)/api/lua_validator/v1/validator.proto
