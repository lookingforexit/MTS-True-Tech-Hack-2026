import os
import pytest
import grpc

from gen.api.llm.v1 import llm_pb2_grpc
from gen.api.lua_validator.v1 import validator_pb2_grpc

@pytest.fixture(scope="session")
def llm_stub():
    target = os.getenv("LLM_TARGET", "localhost:50051")
    channel = grpc.insecure_channel(target)
    yield llm_pb2_grpc.LLMServiceStub(channel)
    channel.close()

@pytest.fixture(scope="session")
def validator_stub():
    target = os.getenv("VALIDATOR_TARGET", "localhost:50052")
    channel = grpc.insecure_channel(target)
    yield validator_pb2_grpc.LuaValidatorServiceStub(channel)
    channel.close()
